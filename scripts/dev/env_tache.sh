#!/bin/bash
# Environnement isolé par tâche (T-004 : worktree ; T-003 : ports ; T-005 : bases).
#
# Usage :
#   scripts/dev/env_tache.sh creer     <NNN> <back|front> [branche]
#   scripts/dev/env_tache.sh supprimer <NNN> <back|front>
#
# NNN : numéro de la tâche, 3 chiffres (ex. 004). n = NNN.
# Ports réservés au worktree (table docs/process/ports.md) :
#   back 3100+n, front dev 3200+n, front prod 3300+n.
# Base de test (back seulement) : zylo_t<NNN>_test, créée vide.
# Worktree : office/worktrees/T-<NNN>-<back|front>, à partir du tag base-T004.
#
# Variable obligatoire pour `creer back` et `supprimer back` :
#   ZYLO_PG_ADMIN_URL = URL d'un rôle PostgreSQL ayant le droit CREATEDB
#   (ex. postgresql://<rôle>:<motdepasse>@localhost:5432/postgres).
#   Elle n'est jamais écrite dans ce script ni dans git.
#
# Intention de chaque garde :
#  - le numéro et le type sont validés avant toute action ;
#  - le préflight (droits, base absente, port libre, tag présent) est fait AVANT
#    la moindre création : un échec ne laisse ni worktree ni base derrière lui ;
#  - seules les bases zylo_t<NNN>_test sont créées ou supprimées : les noms
#    zylo, zylo_office, zylo_dev, zylo_liquid, zylo_recette sont refusés ;
#  - la suppression passe par `git worktree remove` sans --force : un worktree
#    avec des modifications non commitées n'est jamais effacé ;
#  - les branches ne sont jamais supprimées par ce script.

set -euo pipefail

die() { echo "ERREUR : $*" >&2; exit 1; }

# Racine : scripts/dev/ est dans le dépôt backend, qui est lui-même dans office/.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACK_REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
OFFICE="$(cd "$BACK_REPO/.." && pwd)"
FRONT_REPO="$OFFICE/zylo-office-frontend"
WT_ROOT="$OFFICE/worktrees"
INTERDITES="zylo zylo_office zylo_dev zylo_liquid zylo_recette"

[ $# -ge 3 ] || die "usage : $0 creer|supprimer <NNN> <back|front> [branche]"
CMD="$1"; NNN="$2"; KIND="$3"; BRANCHE="${4:-}"

case "$CMD" in creer|supprimer) ;; *) die "commande inconnue : $CMD" ;; esac
[[ "$NNN" =~ ^[0-9]{3}$ ]] || die "NNN doit faire 3 chiffres (reçu : $NNN)"
case "$KIND" in
  back)  REPO="$BACK_REPO" ;;
  front) REPO="$FRONT_REPO" ;;
  *) die "type inconnu : $KIND (back ou front)" ;;
esac

n=$((10#$NNN))
PORT_BACK=$((3100 + n))
PORT_FRONT_DEV=$((3200 + n))
PORT_FRONT_PROD=$((3300 + n))
DB="zylo_t${NNN}_test"
WT="$WT_ROOT/T-$NNN-$KIND"

# Garde de nom : une base de développement ne peut jamais passer ici.
for interdite in $INTERDITES; do
  [ "$DB" != "$interdite" ] || die "nom de base interdit : $DB"
done

port_libre() {
  # Un port est libre si aucun processus n'écoute dessus (ss -H : sans en-tête).
  [ -z "$(ss -ltnH "sport = :$1" 2>/dev/null)" ]
}

# Exécute une requête SQL sur le serveur d'administration (ZYLO_PG_ADMIN_URL).
pg() {
  psql "$ZYLO_PG_ADMIN_URL" -X -q -t -A -c "$1"
}

# URL de la base de test : même hôte et même rôle que l'URL d'administration.
url_base_test() {
  local racine="${ZYLO_PG_ADMIN_URL%/*}"
  echo "${racine}/${DB}" | sed 's#^postgresql://#postgresql+asyncpg://#'
}

if [ "$CMD" = "creer" ]; then
  # ---- Préflight : aucune modification avant que tout soit vérifié ----
  [ ! -e "$WT" ] || die "le worktree existe déjà : $WT"
  git -C "$REPO" rev-parse -q --verify "refs/tags/base-T004" >/dev/null \
    || die "tag base-T004 absent dans $REPO (T-004 n'est pas terminée)"
  if [ -n "$BRANCHE" ]; then
    git -C "$REPO" show-ref --verify -q "refs/heads/$BRANCHE" \
      && die "la branche $BRANCHE existe déjà"
  fi
  if [ "$KIND" = "back" ]; then
    port_libre "$PORT_BACK" || die "port $PORT_BACK occupé"
    [ -n "${ZYLO_PG_ADMIN_URL:-}" ] || die "ZYLO_PG_ADMIN_URL non défini (voir l'en-tête)"
    [ "$(pg "select rolcreatedb from pg_roles where rolname = current_user")" = "t" ] \
      || die "le rôle n'a pas CREATEDB. Un superutilisateur doit lancer : CREATE DATABASE $DB OWNER <rôle>;"
    [ "$(pg "select count(*) from pg_database where datname = '$DB'")" = "0" ] \
      || die "la base $DB existe déjà"
  else
    port_libre "$PORT_FRONT_DEV" || die "port $PORT_FRONT_DEV occupé"
    port_libre "$PORT_FRONT_PROD" || die "port $PORT_FRONT_PROD occupé"
  fi

  # ---- Création ----
  db_creee=0
  if [ "$KIND" = "back" ]; then
    pg "CREATE DATABASE \"$DB\"" >/dev/null
    db_creee=1
  fi
  if [ -n "$BRANCHE" ]; then
    git -C "$REPO" worktree add -q -b "$BRANCHE" "$WT" base-T004 \
      || { [ "$db_creee" = 1 ] && pg "DROP DATABASE \"$DB\"" >/dev/null; die "git worktree add a échoué (base retirée)"; }
  else
    git -C "$REPO" worktree add -q --detach "$WT" base-T004 \
      || { [ "$db_creee" = 1 ] && pg "DROP DATABASE \"$DB\"" >/dev/null; die "git worktree add a échoué (base retirée)"; }
  fi

  # Fichiers d'environnement du worktree : ignorés par git (.env* sauf .env.example).
  if [ "$KIND" = "back" ]; then
    # Le backend lit .env (app/core/config.py) ; conftest.py lit TEST_DATABASE_URL.
    umask 077
    {
      # T-002 : hors development, config.py refuse les secrets de repli ; le worktree
      # est un environnement local, donc ENVIRONMENT=development est posé explicitement
      # (sinon alembic upgrade head échouerait à l'import de app.core.config).
      echo "ENVIRONMENT=development"
      echo "PORT=$PORT_BACK"
      echo "CORS_ORIGINS=[\"http://localhost:$PORT_FRONT_DEV\",\"http://127.0.0.1:$PORT_FRONT_DEV\"]"
      echo "DATABASE_URL=$(url_base_test)"
      echo "TEST_DATABASE_URL=$(url_base_test)"
    } > "$WT/.env"
  else
    # Le frontend lit .env.local ; l'API de ce worktree est le backend du même n.
    printf 'NEXT_PUBLIC_API_URL=http://localhost:%s\nPORT=%s\n' "$PORT_BACK" "$PORT_FRONT_DEV" > "$WT/.env.local"
  fi

  echo "Worktree créé : $WT (base : base-T004${BRANCHE:+, branche $BRANCHE})"
  if [ "$KIND" = "back" ]; then
    echo "  backend : port $PORT_BACK ; base de test : $DB (vide, sans migrations)"
    echo "  reste à faire : venv (.venv, python -m venv + pip install -r requirements.txt), alembic upgrade head"
  else
    echo "  frontend dev : port $PORT_FRONT_DEV ; prod : $PORT_FRONT_PROD ; API : $PORT_BACK"
    echo "  reste à faire : node_modules (npm ci) dans le worktree"
  fi

else
  # ---- Suppression ----
  [ -d "$WT" ] || die "aucun worktree à supprimer : $WT"
  git -C "$REPO" worktree remove "$WT" \
    || die "git refuse de supprimer $WT (modifications non commitées ?) : rien n'a été effacé"
  git -C "$REPO" worktree prune
  if [ "$KIND" = "back" ]; then
    if [ -n "${ZYLO_PG_ADMIN_URL:-}" ] && [ "$(pg "select count(*) from pg_database where datname = '$DB'")" = "1" ]; then
      pg "DROP DATABASE \"$DB\"" >/dev/null
      echo "Base de test supprimée : $DB"
    else
      echo "Base $DB : rien à supprimer (ou ZYLO_PG_ADMIN_URL absent)"
    fi
  fi
  echo "Worktree supprimé : $WT"
  [ -z "$BRANCHE" ] || echo "Branche conservée (non supprimée par ce script)."
fi
