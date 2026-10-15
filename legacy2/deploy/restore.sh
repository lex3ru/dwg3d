#!/bin/sh
# Restore the stack from a backup made by deploy/backup.sh.
#
#   deploy/restore.sh <directory of one backup>     # e.g. deploy/backups/20261005-120000
#
# For a clean server: put deploy/.env in place first (the same secrets as the
# server the backup came from — TWIN_SECRET decrypts stored sessions, the
# passwords of the databases are set from it). The databases in the backup
# REPLACE the current ones; the file storage is replaced too.
set -eu
cd "$(dirname "$0")"
[ $# -eq 1 ] && [ -d "$1" ] || { sed -n '2,9p' "$0"; exit 2; }
source=$(cd "$1" && pwd)
ls "$source"/*.dump >/dev/null 2>&1 || { echo "restore: в $source нет файлов *.dump" >&2; exit 1; }
compose="docker compose -f docker-compose.yml"

echo "restore: останавливаю сервисы, оставляю базу"
$compose up -d --wait db >/dev/null 2>&1
$compose stop $($compose config --services | grep -vx -e db -e db-init) >/dev/null 2>&1 || true

for dump in "$source"/*.dump; do
    name=$(basename "$dump" .dump)
    $compose exec -T db psql -q -U twin -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$name\" WITH (FORCE)"
done
# roles, empty databases and their passwords as deploy/.env says
$compose run --rm db-init >/dev/null
for dump in "$source"/*.dump; do
    name=$(basename "$dump" .dump)
    $compose exec -T db pg_restore -U twin -d "$name" --no-owner --role="$name" --exit-on-error < "$dump"
    echo "restore: $name"
done

if [ -f "$source/s3.tar.gz" ]; then
    $compose up -d s3
    $compose exec -T s3 sh -c 'rm -rf /data/* /data/.[!.]* 2>/dev/null; tar -xzf - -C /data' < "$source/s3.tar.gz"
    $compose restart s3 >/dev/null
    echo "restore: s3"
fi

$compose up -d
echo "restore: готово. Проверьте «Состояние системы» под администратором."
