#!/bin/bash
# Sauvegarde locale de la base PostgreSQL de Zylo Office.
#
# Contexte africain (refonte.md §13) : la connexion internet est souvent
# instable — cette sauvegarde ne dépend d'AUCUN service distant, elle doit
# fonctionner même hors ligne. La sauvegarde externe (upload vers un stockage
# distant une fois la connexion disponible) est un point d'extension séparé,
# non implémenté ici, à brancher à la fin de ce script sans le modifier.
#
# Usage : ./scripts/backup.sh
# Cron suggéré (quotidien, 2h du matin) :
#   0 2 * * * /chemin/vers/zylo-office-backend/scripts/backup.sh >> /var/log/zylo-office-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="${ZYLO_BACKUP_DIR:-$(dirname "$0")/../backups}"
RETENTION_DAYS="${ZYLO_BACKUP_RETENTION_DAYS:-7}"
DB_NAME="${POSTGRES_DB:-zylo_office}"
DB_USER="${POSTGRES_USER:-zylo_office}"
DB_HOST="${POSTGRES_HOST:-localhost}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DUMP_FILE="$BACKUP_DIR/zylo_office_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[backup] Sauvegarde de la base '$DB_NAME' vers $DUMP_FILE"
pg_dump -h "$DB_HOST" -U "$DB_USER" "$DB_NAME" | gzip > "$DUMP_FILE"

# Vérification d'intégrité minimale : le dump gzip doit être décompressible.
if ! gzip -t "$DUMP_FILE"; then
  echo "[backup] ERREUR : le dump généré est corrompu, suppression." >&2
  rm -f "$DUMP_FILE"
  exit 1
fi
echo "[backup] Dump vérifié (intègre)."

# Rotation locale — ne conserve que les N derniers jours.
find "$BACKUP_DIR" -name "zylo_office_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete
echo "[backup] Rotation appliquée (rétention : ${RETENTION_DAYS} jours)."

# Point d'extension pour la sauvegarde externe (grande_phases.md §12) : une
# fois la connexion disponible, un futur appel d'upload viendrait ici, par
# exemple : aws s3 cp "$DUMP_FILE" s3://.../ — non implémenté dans ce socle.
