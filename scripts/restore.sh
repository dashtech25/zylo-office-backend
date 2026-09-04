#!/bin/bash
# Restauration d'un dump généré par backup.sh sur une base cible.
#
# ATTENTION : ce script écrase le contenu de la base cible. À utiliser sur une
# base vide/de test, jamais directement sur une base de production sans
# validation explicite.
#
# Usage : ./scripts/restore.sh <fichier.sql.gz> <nom_de_base_cible>

set -euo pipefail

DUMP_FILE="${1:?Usage: restore.sh <fichier.sql.gz> <nom_de_base_cible>}"
TARGET_DB="${2:?Usage: restore.sh <fichier.sql.gz> <nom_de_base_cible>}"
DB_USER="${POSTGRES_USER:-zylo_office}"
DB_HOST="${POSTGRES_HOST:-localhost}"

if [ ! -f "$DUMP_FILE" ]; then
  echo "[restore] ERREUR : fichier introuvable : $DUMP_FILE" >&2
  exit 1
fi

echo "[restore] Restauration de $DUMP_FILE vers la base '$TARGET_DB'"
gunzip -c "$DUMP_FILE" | psql -h "$DB_HOST" -U "$DB_USER" -d "$TARGET_DB"
echo "[restore] Terminé."
