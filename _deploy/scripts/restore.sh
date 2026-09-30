#!/bin/sh
# Restores a backup:  scripts/restore.sh backups/db/dwg3d-YYYYmmdd-HHMMSS.dump
# The database is replaced by the dump (pg_restore of the application image:
# the dumps are made by its pg_dump), the files of backups/files are uploaded
# back into the storage. The application is stopped meanwhile and started
# again afterwards, also when the restore fails.
set -e
cd "$(dirname "$0")/.."
DUMP="$1"
[ -f "$DUMP" ] || { echo "usage: $0 backups/db/<dump file>"; exit 1; }
DIR=$(cd "$(dirname "$DUMP")" && pwd)
NAME=$(basename "$DUMP")
docker compose stop web api worker keycloak backup
trap 'docker compose up -d' EXIT
docker compose run --rm --no-deps -v "$DIR":/dump:ro backup \
  sh -c 'pg_restore --clean --if-exists --no-owner --dbname "$(echo "$DWG3D_DATABASE_URL" | sed "s/+psycopg//")" "/dump/$0"' "$NAME"
docker compose run --rm --no-deps -v "$PWD/backups/files":/restore:ro api python -m dwg3d files restore /restore
echo "Восстановлено из $DUMP"
