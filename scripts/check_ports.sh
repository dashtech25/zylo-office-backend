#!/bin/bash
# Contrôle des ports interdits (T-003) : 3006 et 3007 ne doivent figurer dans aucun
# fichier de configuration ni dans la documentation de démarrage.
#
# Usage : scripts/check_ports.sh [dossier_frontend]
#   Sans argument, contrôle le dépôt backend. Avec le dossier du dépôt frontend,
#   contrôle aussi les fichiers de configuration du frontend.
#
# Intention : ces ports ont été utilisés par la documentation et la baseline de tests
# avant la table unique (docs/process/ports.md). Un retour de ces valeurs dans un
# fichier de configuration recrée une divergence entre README, .env et code.
# Les audits, revues et plans (docs/audit, docs/plans, docs/questions) citent ces
# ports par nature : ils ne sont pas contrôlés.

set -euo pipefail

BACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INTERDITS='3006|3007'

# Fichiers de configuration et de démarrage du backend (chemins relatifs au dépôt).
FICHIERS_BACK=(
  README.md
  CLAUDE.md
  Dockerfile
  .env.example
  app/core/config.py
  app/main.py
)

# Fichiers de configuration du frontend (chemins relatifs au dépôt frontend).
FICHIERS_FRONT=(
  README.md
  package.json
  .env.local.example
  Dockerfile
  playwright.config.ts
  src/core/api/client.ts
)

trouve=0

controle() {
  local racine="$1"; shift
  local f
  for f in "$@"; do
    [ -f "$racine/$f" ] || continue
    if grep -nE "\b($INTERDITS)\b" "$racine/$f"; then
      trouve=1
    fi
  done
}

controle "$BACK_ROOT" "${FICHIERS_BACK[@]}"

if [ $# -ge 1 ]; then
  FRONT_ROOT="$(cd "$1" && pwd)"
  controle "$FRONT_ROOT" "${FICHIERS_FRONT[@]}"
fi

if [ "$trouve" = 1 ]; then
  echo "ECHEC : port interdit (3006 ou 3007) dans un fichier de configuration. Voir docs/process/ports.md." >&2
  exit 1
fi
echo "OK : aucun port interdit (3006, 3007) dans les fichiers contrôlés."
