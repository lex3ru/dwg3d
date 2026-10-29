#!/usr/bin/env bash
# Восстановление из резервной копии (8.3 п. 4):
#
#   ./deploy/restore.sh <каталог копии>     например backups/daily/2026-10-16_020000
#
# Останавливает приложение, заменяет базу и файлы содержимым копии, запускает снова.
# Всё, что изменилось после копии, теряется — скрипт переспрашивает.
set -euo pipefail
copy="${1:?укажите каталог копии, например backups/daily/2026-10-16_020000}"
copy="$(cd "$copy" && pwd)"
cd "$(dirname "$0")"
[ -f "$copy/db.dump" ] && [ -d "$copy/files" ] || { echo "В $copy нет db.dump и files/ — это не копия." >&2; exit 1; }
set -a; . ./.env; set +a

read -r -p "Заменить данные системы копией $(basename "$copy")? Изменения после неё пропадут. [да/нет] " answer
[ "$answer" = "да" ] || { echo "Отменено."; exit 1; }

docker compose stop app worker caddy
# база пересоздаётся пустой: pg_restore --clean удаляет только то, что есть в копии, а таблицы,
# которые появились после неё (откат неудачного обновления, R-037), не дают удалить схему —
# восстановление падало на полпути
docker compose run --rm -T --no-deps -v "$copy:/restore:ro" --entrypoint sh backup -c '
  set -e
  dropdb --force --if-exists "$PGDATABASE"
  createdb "$PGDATABASE"
  pg_restore --no-owner --exit-on-error -d "$PGDATABASE" /restore/db.dump
'
docker compose run --rm -T --no-deps -v "$copy:/restore:ro" --user 0 --entrypoint sh app -c '
  set -e
  find /data -mindepth 1 -delete
  cp -a /restore/files/. /data/
  chown -R 10001 /data
'
docker compose up -d --wait
echo "Восстановлено из $(basename "$copy")."
