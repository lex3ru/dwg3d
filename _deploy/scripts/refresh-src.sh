#!/bin/sh
# (For developers) copies the current sources of the repository into src/:
# run from the repository before handing _deploy over.
set -e
cd "$(dirname "$0")/.."
REPO=..
rm -rf src && mkdir -p src
rsync -a --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude tests \
      --exclude 'dev_users*' "$REPO/backend/" src/backend/
rsync -a --exclude node_modules --exclude dist "$REPO/frontend/" src/frontend/
git -C "$REPO" rev-parse --short HEAD > src/VERSION 2>/dev/null || true
echo "src/ refreshed: $(cat src/VERSION 2>/dev/null)"
