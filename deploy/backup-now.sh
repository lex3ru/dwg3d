#!/usr/bin/env bash
# Резервная копия сейчас, не дожидаясь расписания.
set -euo pipefail
cd "$(dirname "$0")"
docker compose exec -T backup backup.sh
