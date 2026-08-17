#!/usr/bin/env bash
set -euo pipefail

APP_ROOT=/srv/explore
APP_USER=deploy
APP_GROUP=www-data
DB_NAME=tripanion_explore
DB_USER=explore_app
ENV_FILE="$APP_ROOT/app/backend/.env"

install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 \
  "$APP_ROOT" "$APP_ROOT/app" "$APP_ROOT/app/backend" \
  "$APP_ROOT/app/frontend" "$APP_ROOT/backups"

if ! dpkg-query -W postgresql-16-postgis-3 libgdal34t64 >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    postgresql-16-postgis-3 libgdal34t64
fi

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
  DB_PASSWORD="$(openssl rand -hex 24)"
  sudo -u postgres psql -v ON_ERROR_STOP=1 \
    -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD' NOSUPERUSER NOCREATEDB NOCREATEROLE;"
else
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Die Datenbankrolle existiert, aber $ENV_FILE fehlt; Passwort wird nicht automatisch ersetzt." >&2
    exit 1
  fi
  DB_PASSWORD="$(sed -n 's#^DATABASE_URL=postgresql://[^:]*:\([^@]*\)@.*#\1#p' "$ENV_FILE")"
fi

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
  sudo -u postgres createdb --owner="$DB_USER" --encoding=UTF8 "$DB_NAME"
fi
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS postgis;"

if [[ ! -f "$ENV_FILE" ]]; then
  DJANGO_SECRET_KEY="$(openssl rand -hex 48)"
  install -o root -g "$APP_GROUP" -m 0640 /dev/null "$ENV_FILE"
  {
    printf 'DATABASE_URL=postgresql://%s:%s@127.0.0.1:5432/%s\n' "$DB_USER" "$DB_PASSWORD" "$DB_NAME"
    printf 'REDIS_URL=redis://127.0.0.1:6379/1\n'
    printf 'DJANGO_SECRET_KEY=%s\n' "$DJANGO_SECRET_KEY"
    printf 'DJANGO_DEBUG=false\n'
    printf 'DJANGO_ALLOWED_HOSTS=explore.tripanion.com,127.0.0.1,localhost\n'
    printf 'CORS_ALLOWED_ORIGINS=https://explore.tripanion.com\n'
    printf 'CSRF_TRUSTED_ORIGINS=https://explore.tripanion.com\n'
    printf 'DJANGO_SECURE_COOKIES=true\n'
    printf 'DJANGO_HSTS_SECONDS=86400\n'
    printf 'API_ANON_RATE=120/minute\n'
    printf 'API_RESEARCH_RATE=30/hour\n'
    printf 'WIKIMEDIA_USER_AGENT=TripanionExplore/0.1+https://explore.tripanion.com\n'
  } >> "$ENV_FILE"
fi

python3 -m venv "$APP_ROOT/venv"
"$APP_ROOT/venv/bin/pip" install --upgrade pip
"$APP_ROOT/venv/bin/pip" install -r "$APP_ROOT/app/backend/requirements.txt"

chown -R "$APP_USER:$APP_GROUP" "$APP_ROOT/app" "$APP_ROOT/venv"
chmod 0750 "$APP_ROOT" "$APP_ROOT/app" "$APP_ROOT/app/backend" "$APP_ROOT/app/frontend"
chmod 0640 "$ENV_FILE"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
runuser -u "$APP_USER" -- "$APP_ROOT/venv/bin/python" "$APP_ROOT/app/backend/manage.py" migrate --noinput
runuser -u "$APP_USER" -- "$APP_ROOT/venv/bin/python" "$APP_ROOT/app/backend/manage.py" collectstatic --noinput
