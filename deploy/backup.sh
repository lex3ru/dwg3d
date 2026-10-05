#!/bin/sh
# A backup of the whole stack: every database and the file storage.
#
#   deploy/backup.sh [directory]        # default: TWIN_BACKUP_DIR of deploy/.env, else deploy/backups
#
# Makes <directory>/<date-time>/ with <database>.dump for each database
# (services and Keycloak) and s3.tar.gz. The stack keeps running. Events in
# transit (NATS) are not saved: after a restore each service's reconciliation
# brings its copies of others' data back in line (docs/DATA_MODEL.md, 11).
# Keeps the last TWIN_BACKUP_KEEP backups (default 14).
set -eu
cd "$(dirname "$0")"
compose="docker compose -f docker-compose.yml"
# a setting: from the environment, else from deploy/.env, else the default
setting() { eval "v=\${$1:-}"; [ -n "$v" ] || v=$(sed -n "s/^$1=//p" .env 2>/dev/null | tail -1); printf '%s' "${v:-$2}"; }

root=${1:-$(setting TWIN_BACKUP_DIR ./backups)}
target="$root/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$target"

databases=$($compose exec -T db psql -U twin -d postgres -Atc \
    "select datname from pg_database where not datistemplate and datname <> 'postgres' order by 1")
[ -n "$databases" ] || { echo "backup: баз не найдено — стек запущен?" >&2; exit 1; }
for name in $databases; do
    $compose exec -T db pg_dump -U twin -Fc "$name" > "$target/$name.dump"
    echo "backup: $name ($(du -h "$target/$name.dump" | cut -f1))"
done

$compose exec -T s3 tar -czf - -C /data . > "$target/s3.tar.gz"
echo "backup: s3 ($(du -h "$target/s3.tar.gz" | cut -f1))"

keep=$(setting TWIN_BACKUP_KEEP 14)
ls -1d "$root"/[0-9]*-[0-9]* 2>/dev/null | sort -r | tail -n +$((keep + 1)) | while read -r old; do
    rm -rf "$old"
    echo "backup: удалена старая копия $old"
done
echo "backup: готово — $target"
