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
# Base de test (back seulement) : zylo_t<NNN>_test, migrée à `alembic upgrade head`,
# propriétaire zylo_office (le rôle zylo_office n'est pas modifié).
# Worktree : office/worktrees/T-<NNN>-<back|front>, à partir du tag base-T004.
#
# Serveur d'administration (back seulement) : variable ZYLO_PG_ADMIN_URL.
#   Par défaut : rôle Unix courant via la socket locale (auth peer, sans mot de passe),
#   soit postgresql://<utilisateur>@/postgres?host=/var/run/postgresql.
#   Ce rôle doit avoir CREATEDB (ou être superutilisateur pour fixer le propriétaire).
#   Aucun mot de passe n'est écrit dans ce script ni dans git.
#   Les migrations et les tests se connectent avec ce même rôle d'administration :
#   le mot de passe de zylo_office n'est jamais utilisé ni stocké par ce script.
#   Le venv utilisé pour alembic est celui du dépôt backend (.venv).
#
# Intention de chaque garde :
#  - le numéro et le type sont validés avant toute action ;
#  - le préflight (droits, base absente, port libre, tag présent, alembic présent)
#    est fait AVANT la moindre création : un échec ne laisse ni worktree ni base ;
#  - seules les bases zylo_t<NNN>_test (motif zylo_t[0-9]{3}_test) sont créées ou
#    supprimées : les noms zylo, zylo_office, zylo_dev, zylo_liquid, zylo_recette
#    ne correspondent pas au motif et sont refusés ;
#  - si les migrations échouent, le worktree et la base créés sont retirés ;
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
PG_ADMIN_PAR_DEFAUT="postgresql://$(id -un)@/postgres?host=/var/run/postgresql"
ZYLO_PG_ADMIN_URL="${ZYLO_PG_ADMIN_URL:-$PG_ADMIN_PAR_DEFAUT}"
PROPRIETAIRE="zylo_office"
ALEMBIC="$BACK_REPO/.venv/bin/alembic"

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
# Intention : la formule de T-003 (back 3100+n, front 3200+n, prod 3300+n) ne
# produit des plages disjointes que pour n < 100. Au-delà, 3100+n tombe dans
# la plage front (3200+n) d'un autre numéro. On refuse plutôt que de collisionner.
[ "$n" -lt 100 ] || die "NNN doit être inférieur à 100 : au-delà, la formule de ports de T-003 collisionne (décision à prendre)"
PORT_BACK=$((3100 + n))
PORT_FRONT_DEV=$((3200 + n))
PORT_FRONT_PROD=$((3300 + n))
DB="zylo_t${NNN}_test"
WT="$WT_ROOT/T-$NNN-$KIND"

# Garde de nom : seul le motif zylo_t<NNN>_test passe ; une base de développement
# ne peut jamais passer ici, même si le motif évoluait.
verifie_nom_base() {
  [[ "$1" =~ ^zylo_t[0-9]{3}_test$ ]] || die "nom de base hors motif zylo_t[0-9]{3}_test : $1"
  for interdite in $INTERDITES; do
    [ "$1" != "$interdite" ] || die "nom de base interdit : $1"
  done
}
verifie_nom_base "$DB"

port_libre() {
  # Un port est libre si aucun processus n'écoute dessus (ss -H : sans en-tête).
  [ -z "$(ss -ltnH "sport = :$1" 2>/dev/null)" ]
}

# Exécute une requête SQL sur le serveur d'administration (ZYLO_PG_ADMIN_URL).
pg() {
  psql "$ZYLO_PG_ADMIN_URL" -X -q -t -A -c "$1"
}

# URL de la base de test : même hôte, même rôle et même query string que l'URL
# d'administration ; seul le nom de base change.
url_base_test() {
  local base="${ZYLO_PG_ADMIN_URL%%\?*}"
  local query=""
  [[ "$ZYLO_PG_ADMIN_URL" == *\?* ]] && query="?${ZYLO_PG_ADMIN_URL#*\?}"
  echo "${base%/*}/${DB}${query}" | sed 's#^postgresql://#postgresql+asyncpg://#'
}

# Migrations sur la base de la tâche uniquement : DATABASE_URL est passé en
# variable d'environnement (elle prime sur le .env du worktree).
appliquer_migrations() {
  ( cd "$WT" && DATABASE_URL="$(url_base_test)" "$ALEMBIC" upgrade head )
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
    [ -x "$ALEMBIC" ] || die "alembic introuvable : $ALEMBIC (venv du dépôt backend : python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)"
    [ "$(pg "select rolcreatedb from pg_roles where rolname = current_user")" = "t" ] \
      || die "le rôle n'a pas CREATEDB. Un superutilisateur doit lancer : CREATE DATABASE $DB OWNER $PROPRIETAIRE;"
    [ "$(pg "select count(*) from pg_database where datname = '$DB'")" = "0" ] \
      || die "la base $DB existe déjà"
    # Propriétaire : zylo_office si le rôle courant peut le fixer (membre ou superutilisateur),
    # sinon le rôle courant. Aucun ALTER ROLE ni GRANT n'est émis.
    PROPRIETAIRE_BASE="$(pg "select case when exists (select 1 from pg_roles where rolname = '$PROPRIETAIRE') and pg_has_role(current_user, '$PROPRIETAIRE', 'MEMBER') then '$PROPRIETAIRE' else current_user end")"
  else
    port_libre "$PORT_FRONT_DEV" || die "port $PORT_FRONT_DEV occupé"
    port_libre "$PORT_FRONT_PROD" || die "port $PORT_FRONT_PROD occupé"
  fi

  # ---- Création ----
  db_creee=0
  if [ "$KIND" = "back" ]; then
    pg "CREATE DATABASE \"$DB\" OWNER \"$PROPRIETAIRE_BASE\"" >/dev/null
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

    # Migrations : en cas d'échec, on retire le worktree (sans --force) et la base.
    if ! appliquer_migrations; then
      git -C "$REPO" worktree remove "$WT" 2>/dev/null \
        || echo "ATTENTION : worktree $WT conservé (retrait refusé)" >&2
      git -C "$REPO" worktree prune
      pg "DROP DATABASE \"$DB\"" >/dev/null
      die "alembic upgrade head a échoué sur $DB (worktree et base retirés)"
    fi
  else
    # Le frontend lit .env.local ; l'API de ce worktree est le backend du même n.
    printf 'NEXT_PUBLIC_API_URL=http://localhost:%s\nPORT=%s\n' "$PORT_BACK" "$PORT_FRONT_DEV" > "$WT/.env.local"
  fi

  echo "Worktree créé : $WT (base : base-T004${BRANCHE:+, branche $BRANCHE})"
  if [ "$KIND" = "back" ]; then
    echo "  backend : port $PORT_BACK ; base de test : $DB (propriétaire $PROPRIETAIRE_BASE, migrée à head)"
    echo "  venv : $BACK_REPO/.venv (partagé ; lancer depuis le worktree : $BACK_REPO/.venv/bin/pytest)"
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
    verifie_nom_base "$DB"
    if [ "$(pg "select count(*) from pg_database where datname = '$DB'")" = "1" ]; then
      pg "DROP DATABASE \"$DB\"" >/dev/null
      echo "Base de test supprimée : $DB"
    else
      echo "Base $DB : absente, rien à supprimer"
    fi
  fi
  echo "Worktree supprimé : $WT"
  [ -z "$BRANCHE" ] || echo "Branche conservée (non supprimée par ce script)."
fi
