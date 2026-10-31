#!/bin/bash
# One-time setup of a fresh Ubuntu 24.04 server (e.g. Infomaniak VPS Cloud / Public Cloud, Swiss data centre).
# Run as root:  bash server-setup.sh shop.feldzutisch.ch admin@feldzutisch.ch
# Before: point the domain's DNS A/AAAA record to the server and allow ports 22, 80, 443 in the provider firewall.
set -euo pipefail

DOMAIN="${1:?Domain fehlt, z.B. shop.feldzutisch.ch}"
ADMIN_EMAIL="${2:?E-Mail des ersten Super-Admins fehlt}"
APP_DIR=/opt/felicia
REPO_URL="${REPO_URL:-git@github.com:riedertoby-hash/felicia.git}"

echo "== System aktualisieren und absichern"
apt-get update && apt-get -y upgrade
apt-get install -y ca-certificates curl git ufw fail2ban unattended-upgrades gnupg rclone
dpkg-reconfigure -f noninteractive unattended-upgrades
ufw default deny incoming && ufw default allow outgoing
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart ssh

echo "== Docker installieren"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

echo "== Code holen (Deploy-Key muss im GitHub-Repository hinterlegt sein)"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "== Konfiguration (.env) anlegen, falls nicht vorhanden"
if [ ! -f .env ]; then
  SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
  FKEY=$(docker run --rm python:3.13-slim sh -c "pip -q install cryptography >/dev/null 2>&1 && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'")
  DBPASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  cat > .env <<ENV
DOMAIN=$DOMAIN
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=$SECRET
DJANGO_ALLOWED_HOSTS=$DOMAIN
DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN
FIELD_ENCRYPTION_KEYS=$FKEY
DEFAULT_TENANT_SLUG=feldzutisch
POSTGRES_DB=felicia
POSTGRES_USER=felicia
POSTGRES_PASSWORD=$DBPASS
POSTGRES_HOST=db
POSTGRES_SSLMODE=disable
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=mail.infomaniak.com
EMAIL_PORT=587
EMAIL_USE_TLS=1
EMAIL_HOST_USER=noreply@$DOMAIN
EMAIL_HOST_PASSWORD=BITTE-SETZEN
DEFAULT_FROM_EMAIL=Feld zu Tisch <noreply@$DOMAIN>
MFA_TOTP_ISSUER=Feld zu Tisch
ENV
  chmod 600 .env
  echo "!! .env angelegt. Bitte EMAIL_HOST_PASSWORD eintragen und FIELD_ENCRYPTION_KEYS sicher aufbewahren"
  echo "!! (ohne diesen Schlüssel sind gespeicherte IBANs nicht mehr lesbar)."
fi

echo "== Starten"
docker compose up -d --build
sleep 20
docker compose exec -T web python manage.py setup_marketplace --name "Feld zu Tisch" --domain "$DOMAIN" \
  --admin-email "$ADMIN_EMAIL" || true

echo "== Tägliches Backup um 02:15 einrichten"
if [ ! -f /root/.felicia-backup-pass ]; then
  python3 -c "import secrets; print(secrets.token_urlsafe(40))" > /root/.felicia-backup-pass
  chmod 600 /root/.felicia-backup-pass
  echo "!! Backup-Passphrase in /root/.felicia-backup-pass – zusätzlich ausserhalb des Servers aufbewahren."
fi
cat > /etc/cron.d/felicia-backup <<CRON
15 2 * * * root cd $APP_DIR && BACKUP_DIR=/var/backups/felicia BACKUP_PASSPHRASE_FILE=/root/.felicia-backup-pass RCLONE_REMOTE=\${RCLONE_REMOTE:-} ./scripts/backup.sh >> /var/log/felicia-backup.log 2>&1
CRON

echo "== Fertig. Super-Admin setzt sein Passwort über «Passwort vergessen» auf https://$DOMAIN/konto/password/reset/"
echo "   Offsite-Backup (empfohlen): Infomaniak Swiss Backup als rclone-Remote einrichten (rclone config)"
echo "   und RCLONE_REMOTE=swissbackup:felicia in /etc/cron.d/felicia-backup setzen."
