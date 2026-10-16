#!/bin/sh
# Одна резервная копия (8.3 п. 3): база (pg_dump) и файлы. Файлы хранятся под именем
# по содержимому и не меняются, поэтому копия файлов — жёсткие ссылки на предыдущую
# плюс новые файлы: ежедневная копия не занимает место заново.
# Хранятся KEEP_DAILY ежедневных и KEEP_MONTHLY ежемесячных (первая копия месяца).
set -eu
root=/backups
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
stamp=$(date +%Y-%m-%d_%H%M%S)
target="$root/daily/$stamp"
work="$target.part"

report() { # ok message
  size=$(du -sb "$target" 2>/dev/null | cut -f1 || echo 0)
  daily=$(find "$root/daily" -mindepth 1 -maxdepth 1 -type d ! -name '*.part' 2>/dev/null | wc -l)
  monthly=$(find "$root/monthly" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
  printf '{"ok": %s, "started_at": "%s", "finished_at": "%s", "path": "%s", "size": %s, "message": "%s", "kept": {"daily": %s, "monthly": %s}}\n' \
    "$1" "$started" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$target" "${size:-0}" "$2" "$daily" "$monthly" > "$root/last.json.tmp"
  mv "$root/last.json.tmp" "$root/last.json"
}

fail() {
  rm -rf "$work"
  report false "$1"
  echo "backup: $1" >&2
  exit 1
}

mkdir -p "$root/daily" "$root/monthly"
rm -rf "$root"/daily/*.part
mkdir -p "$work"
echo "backup: $stamp"
pg_dump -Fc -f "$work/db.dump" || fail "Не удалось выгрузить базу данных."
previous=$(find "$root/daily" -mindepth 1 -maxdepth 1 -type d ! -name '*.part' | sort | tail -n 1)
if [ -n "$previous" ] && [ -d "$previous/files" ]; then
  rsync -a --delete --link-dest="$previous/files" /data/ "$work/files/" || fail "Не удалось скопировать файлы."
else
  rsync -a --delete /data/ "$work/files/" || fail "Не удалось скопировать файлы."
fi
rm -rf "$target"
mv "$work" "$target"

month=$(date +%Y-%m)
[ -d "$root/monthly/$month" ] || cp -al "$target" "$root/monthly/$month"

find "$root/daily" -mindepth 1 -maxdepth 1 -type d | sort -r | tail -n +$((KEEP_DAILY + 1)) | xargs -r rm -rf
find "$root/monthly" -mindepth 1 -maxdepth 1 -type d | sort -r | tail -n +$((KEEP_MONTHLY + 1)) | xargs -r rm -rf

report true ""
echo "backup: done $target"
