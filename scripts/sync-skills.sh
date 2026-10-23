#!/bin/sh
# Копирует общие навыки из .agents/skills (их читает Codex и другие агенты)
# в .claude/skills (их читает Claude Code). Править нужно только .agents/skills.
#   sh scripts/sync-skills.sh           синхронизировать
#   sh scripts/sync-skills.sh --check   только проверить (для CI); код 1 при расхождении
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC="$ROOT/.agents/skills"
DST="$ROOT/.claude/skills"
MARK=".synced-from-agents"
MODE="${1:-sync}"
status=0

[ -d "$SRC" ] || { echo "Нет каталога $SRC" >&2; exit 1; }

# Для --check нужен diff с опцией -x (GNU или BSD). В busybox её нет, и без
# этой проверки все навыки выглядели бы расходящимися.
if [ "$MODE" = "--check" ] && ! diff -r -x "$MARK" "$SRC" "$SRC" >/dev/null 2>&1; then
  echo "Нужен diff с опцией -x (GNU diffutils или BSD diff), в busybox её нет" >&2
  exit 1
fi

for dir in "$SRC"/*/; do
  [ -f "${dir}SKILL.md" ] || continue
  name=$(basename "$dir")
  if [ "$MODE" = "--check" ]; then
    if ! diff -r -x "$MARK" "${dir%/}" "$DST/$name" >/dev/null 2>&1; then
      echo "Расходится: .claude/skills/$name — запустите scripts/sync-skills" >&2
      status=1
    fi
  else
    rm -rf "${DST:?}/$name"
    mkdir -p "$DST"
    cp -R "${dir%/}" "$DST/$name"
    echo "Копия навыка из .agents/skills/$name. Не редактируйте: правьте оригинал и запустите scripts/sync-skills." > "$DST/$name/$MARK"
  fi
done

# Копии навыков, которых больше нет в .agents/skills
if [ -d "$DST" ]; then
  for dir in "$DST"/*/; do
    [ -f "${dir}$MARK" ] || continue
    name=$(basename "$dir")
    [ -d "$SRC/$name" ] && continue
    if [ "$MODE" = "--check" ]; then
      echo "Лишняя копия: .claude/skills/$name" >&2
      status=1
    else
      rm -rf "${DST:?}/$name"
      echo "Удалена устаревшая копия: .claude/skills/$name"
    fi
  done
fi

exit $status
