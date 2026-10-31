#!/bin/sh
# Daily encrypted database backup. Run via cron on the host, e.g.:
#   15 2 * * * /opt/felicia/scripts/backup.sh
# Needs: BACKUP_DIR, BACKUP_PASSPHRASE_FILE (gpg symmetric), docker compose in /opt/felicia.
# Optional: RCLONE_REMOTE (e.g. swissbackup:felicia) for an offsite copy.
# Restore: gpg -d felicia_X.sql.gz.gpg | gunzip | docker compose exec -T db psql -U postgres felicia
#   (then: ALTER DATABASE/tables owner back to the app role if restored into a fresh database)
set -eu
cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y-%m-%d_%H%M)
FILE="$BACKUP_DIR/felicia_$STAMP.sql.gz.gpg"
docker compose exec -T db sh -c 'pg_dump -U postgres --no-owner "$APP_DB_NAME"' \
  | gzip \
  | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-file "$BACKUP_PASSPHRASE_FILE" -o "$FILE"
# media files (logos, product images)
MEDIA_FILE="$BACKUP_DIR/felicia_media_$STAMP.tar.gz.gpg"
docker compose exec -T web tar -czf - -C /app media \
  | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-file "$BACKUP_PASSPHRASE_FILE" -o "$MEDIA_FILE"
find "$BACKUP_DIR" -name 'felicia_*.gpg' -mtime +"$KEEP_DAYS" -delete
# Optional offsite copy (e.g. Infomaniak Swiss Backup via rclone), stays in Switzerland
if [ -n "${RCLONE_REMOTE:-}" ]; then
  rclone copy "$BACKUP_DIR" "$RCLONE_REMOTE" --include 'felicia_*.gpg' --max-age 48h
fi
echo "Backup: $FILE $MEDIA_FILE"
