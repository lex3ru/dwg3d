#!/bin/sh
# База из резервной копии (8.3 п. 4) — для deploy/restore.sh, в контейнере backup. Текущая
# база не трогается, пока копия не восстановлена целиком: копия — в отдельную базу, затем
# подмена переименованием (оба переименования — одной транзакцией), прежняя база удаляется
# только после удачного запуска системы. Битая копия не стоит данных (R-037).
#
#   restore-db.sh load <db.dump>   копия → база <имя>_restore; система может работать
#   restore-db.sh swap             <имя> → <имя>_before_restore, <имя>_restore → <имя>
#   restore-db.sh undo             обратно: прежняя база снова <имя>
#   restore-db.sh drop-before      удалить <имя>_before_restore — система запустилась
set -eu
# без «NOTICE: database … does not exist, skipping» от --if-exists
export PGOPTIONS="-c client_min_messages=warning"
db="$PGDATABASE"
new="${db}_restore"
old="${db}_before_restore"

sql() { psql -X -q -v ON_ERROR_STOP=1 -d postgres -c "$1"; }
exists() { [ "$(psql -X -tA -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$1'")" = 1 ]; }
# переименовать базу можно, только когда к ней никто не подключён
disconnect() { sql "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE datname IN ('$1', '$2') AND pid <> pg_backend_pid()" >/dev/null; }

case "${1:-}" in
  load)
    dump="${2:?укажите файл копии базы}"
    if exists "$old"; then
      echo "Есть база $old — прежняя база незавершённого восстановления. Если она не нужна:" >&2
      echo "  docker compose exec db dropdb -U $PGUSER $old" >&2
      exit 1
    fi
    dropdb --if-exists "$new"
    createdb "$new"
    if ! pg_restore --no-owner --exit-on-error -d "$new" "$dump"; then
      dropdb "$new"
      echo "Копия базы не восстановилась — текущая база не тронута." >&2
      exit 1
    fi
    ;;
  swap)
    disconnect "$db" "$new"
    sql "ALTER DATABASE \"$db\" RENAME TO \"$old\"; ALTER DATABASE \"$new\" RENAME TO \"$db\""
    ;;
  undo)
    disconnect "$db" "$old"
    sql "ALTER DATABASE \"$db\" RENAME TO \"$new\"; ALTER DATABASE \"$old\" RENAME TO \"$db\""
    dropdb "$new"
    ;;
  drop-before)
    dropdb --if-exists "$old"
    ;;
  *)
    echo "restore-db.sh load <db.dump> | swap | undo | drop-before" >&2
    exit 2
    ;;
esac
