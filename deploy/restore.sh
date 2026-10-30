#!/usr/bin/env bash
# Восстановление из резервной копии (8.3 п. 4):
#
#   ./deploy/restore.sh <каталог копии>     например backups/daily/2026-10-16_020000
#
# Заменяет базу и файлы содержимым копии и запускает систему снова. Всё, что изменилось после
# копии, теряется — скрипт переспрашивает. Текущая база не трогается, пока копия не
# восстановлена целиком рядом с ней (backup/restore-db.sh): битая копия — ошибка, а система
# работает на прежних данных. Прежняя база удаляется только после удачного запуска.
set -euo pipefail
copy="${1:?укажите каталог копии, например backups/daily/2026-10-16_020000}"
copy="$(cd "$copy" && pwd)"
cd "$(dirname "$0")"
[ -f "$copy/db.dump" ] && [ -d "$copy/files" ] || { echo "В $copy нет db.dump и files/ — это не копия." >&2; exit 1; }
set -a; . ./.env; set +a

read -r -p "Заменить данные системы копией $(basename "$copy")? Изменения после неё пропадут. [да/нет] " answer
[ "$answer" = "да" ] || { echo "Отменено."; exit 1; }

restore_db() { docker compose run --rm -T --no-deps -v "$copy:/restore:ro" --entrypoint restore-db.sh backup "$@"; }

# копия — в отдельную базу, пока система работает; не восстановилась — данные не тронуты.
# Не pg_restore --clean поверх текущей: он удаляет только то, что есть в копии, и таблицы,
# появившиеся после неё (откат неудачного обновления, R-037), не давали удалить схему
restore_db load /restore/db.dump || { echo "Данные системы не тронуты." >&2; exit 1; }

docker compose stop app worker caddy
restore_db swap
docker compose run --rm -T --no-deps -v "$copy:/restore:ro" --user 0 --entrypoint sh app -c '
  set -e
  find /data -mindepth 1 -delete
  cp -a /restore/files/. /data/
  chown -R 10001 /data
'
if ! docker compose up -d --wait; then
  echo "Система не запустилась с копией. Причина — в журнале: docker compose logs --tail 200 app" >&2
  echo "Прежняя база сохранена как app_before_restore (файлы — уже из копии). Вернуть её:" >&2
  echo "  cd $(pwd) && docker compose stop app worker && docker compose run --rm -T --no-deps --entrypoint restore-db.sh backup undo && docker compose up -d" >&2
  exit 1
fi
restore_db drop-before
echo "Восстановлено из $(basename "$copy")."
