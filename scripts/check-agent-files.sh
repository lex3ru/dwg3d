#!/bin/sh
# Проверки контекстных файлов для ИИ-агентов (локально и в CI):
#  - копии навыков в .claude/skills совпадают с .agents/skills;
#  - у каждого SKILL.md корректные name (совпадает с папкой) и description;
#  - AGENTS.md есть и не длиннее 200 строк;
#  - CLAUDE.md, если есть, импортирует AGENTS.md;
#  - у файлов задач есть шапка с id и допустимым status.
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1
fail=0

err()  { echo "ОШИБКА: $*" >&2; fail=1; }
warn() { echo "ВНИМАНИЕ: $*" >&2; }

# YAML-шапка файла (строки между первыми двумя ---), без \r
frontmatter() {
  tr -d '\r' < "$1" | awk 'NR == 1 && $0 != "---" { exit } NR > 1 && $0 == "---" { exit } NR > 1 { print }'
}

# 1. Копии навыков
sh scripts/sync-skills.sh --check || fail=1

# 2. Шапки навыков
for f in .agents/skills/*/SKILL.md; do
  [ -f "$f" ] || continue
  dir=$(basename "$(dirname "$f")")
  name=$(frontmatter "$f" | sed -n 's/^name:[[:space:]]*//p' | head -n 1 | tr -d "\"'")
  desc=$(frontmatter "$f" | sed -n 's/^description:[[:space:]]*//p' | head -n 1)
  [ "$name" = "$dir" ] || err "$f: name '$name' не совпадает с папкой '$dir'"
  printf '%s' "$name" | grep -Eq '^[a-z0-9]+(-[a-z0-9]+)*$' || err "$f: name — только a-z, 0-9 и одиночные дефисы"
  [ -n "$desc" ] || err "$f: нет description"
done

# 3. AGENTS.md
if [ -f AGENTS.md ]; then
  lines=$(wc -l < AGENTS.md | tr -d ' ')
  if [ "$lines" -gt 200 ]; then
    err "AGENTS.md: $lines строк при лимите 200 — вынесите подробности в docs/ или навыки"
  elif [ "$lines" -gt 150 ]; then
    warn "AGENTS.md: $lines строк — приближается к лимиту"
  fi
  if grep -q 'ЗАПОЛНИТЬ' AGENTS.md; then
    warn "AGENTS.md: остались заглушки ЗАПОЛНИТЬ"
  fi
else
  err "нет AGENTS.md"
fi

# 4. CLAUDE.md
if [ -f CLAUDE.md ] && ! grep -q '^@AGENTS.md' CLAUDE.md; then
  err "CLAUDE.md не импортирует AGENTS.md (нужна строка @AGENTS.md) — Claude Code не увидит общие правила"
fi

# 5. Файлы задач
for f in docs/tasks/*.md; do
  [ -f "$f" ] || continue
  case "$(basename "$f")" in README.md|_template.md) continue ;; esac
  frontmatter "$f" | grep -q '^id:' || err "$f: в шапке нет id"
  frontmatter "$f" | grep -Eq '^status:[[:space:]]*(in-progress|blocked|done)[[:space:]]*$' \
    || err "$f: status должен быть in-progress, blocked или done"
done

[ "$fail" -eq 0 ] && echo "Контекстные файлы в порядке."
exit "$fail"
