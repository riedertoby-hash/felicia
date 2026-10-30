#!/bin/sh
# Daily encrypted database backup. Run via cron on the host, e.g.:
#   15 2 * * * /opt/felicia/scripts/backup.sh
# Needs: BACKUP_DIR, BACKUP_PASSPHRASE_FILE (gpg symmetric), docker compose in /opt/felicia.
set -eu
cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y-%m-%d_%H%M)
FILE="$BACKUP_DIR/felicia_$STAMP.sql.gz.gpg"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" --no-owner "$POSTGRES_DB"' \
  | gzip \
  | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-file "$BACKUP_PASSPHRASE_FILE" -o "$FILE"
find "$BACKUP_DIR" -name 'felicia_*.sql.gz.gpg' -mtime +"$KEEP_DAYS" -delete
echo "Backup: $FILE"
