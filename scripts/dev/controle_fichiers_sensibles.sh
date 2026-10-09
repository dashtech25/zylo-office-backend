#!/bin/bash
# Contrôle des fichiers qui ne doivent jamais être suivis par git (T-001).
#
# Intention : un dump de base ou un fichier .env dans l'historique git est une
# fuite irréversible sans réécriture. Ce script est la source unique des règles ;
# il sert :
#   - au hook de commit (.githooks/pre-commit, mode --staged) : bloque l'ajout ;
#   - aux tests (tests/test_controle_fichiers_sensibles.py, mode --index) : bloque
#     un fichier déjà suivi, y compris si le hook n'est pas activé sur un clone.
#
# Usage (depuis n'importe quel répertoire du dépôt) :
#   scripts/dev/controle_fichiers_sensibles.sh --index    # fichiers suivis (git ls-files)
#   scripts/dev/controle_fichiers_sensibles.sh --staged   # fichiers à committer
#
# Sortie : 0 si aucun fichier interdit ; 1 avec la liste sinon.
#
# Règles :
#   - dumps de base : *.sql, *.sql.gz, *.sql.bz2, *.sql.xz, *.dump, *.pgdump ;
#   - fichiers d'environnement : .env et .env.* (sauf .env.example), à toute profondeur ;
#   - clés privées : *.pem, *.key, *.p12, id_rsa, id_ed25519 (à toute profondeur).
# Limite : contrôle par nom de fichier. Il ne lit pas le contenu (un secret dans un
# fichier au nom anodin n'est pas détecté).

set -eu

mode="${1:-}"
case "$mode" in
  --index)  liste="$(git ls-files)" ;;
  --staged) liste="$(git diff --cached --name-only --diff-filter=ACMR)" ;;
  *) echo "usage : $0 --index|--staged" >&2; exit 2 ;;
esac

interdits=""
while IFS= read -r f; do
  [ -n "$f" ] || continue
  base="${f##*/}"
  raison=""
  case "$base" in
    *.sql|*.sql.gz|*.sql.bz2|*.sql.xz|*.dump|*.pgdump)
      raison="dump de base" ;;
    .env.example)
      raison="" ;;
    .env|.env.*)
      raison="fichier d'environnement" ;;
    *.pem|*.key|*.p12|id_rsa|id_ed25519)
      raison="clé privée ou certificat" ;;
  esac
  if [ -n "$raison" ]; then
    interdits="${interdits}  ${f} (${raison})"$'\n'
  fi
done <<EOF
$liste
EOF

if [ -n "$interdits" ]; then
  printf 'Fichiers interdits dans git (%s) :\n%s' "$mode" "$interdits" >&2
  echo "Retirer de l'index : git rm --cached <fichier> (le fichier reste sur disque)." >&2
  exit 1
fi
exit 0
