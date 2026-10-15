#!/bin/sh
# The restore check (docs/ACCEPTANCE.md, 12.3): a backup of one stack restored on a clean one, and compared.
#
#   tools/acceptance/restore-test.sh [source project] [source n] [target project] [target n] [work dir]
#   default: twin-accept 1 twin-restore 2 /tmp/twin-restore-test
#
# The target must not exist yet (it stands for a clean server): its containers and volumes are made
# anew and left running for a look; remove them with
#   tools/acceptance/stack.sh twin-restore 2 compose down -v
# Nothing should write to the source meanwhile. The time printed is from the backup in hand to a
# restored stack that answers and signs in.
set -eu
cd "$(dirname "$0")/../.."
src=${1:-twin-accept} sn=${2:-1} dst=${3:-twin-restore} dn=${4:-2} work=${5:-/tmp/twin-restore-test}
stack() { tools/acceptance/stack.sh "$@"; }
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$dst")" ]; then
    echo "стенд $dst уже есть — это не чистый сервер; удалите: tools/acceptance/stack.sh $dst $dn compose down -v" >&2
    exit 1
fi
rm -rf "$work" && mkdir -p "$work"

echo "== резервная копия $src"
stack "$src" "$sn" deploy/backup.sh "$work/backups"
copy=$(ls -1d "$work"/backups/*/ | tail -1)
du -sh "$copy"
python3 tools/acceptance/compare.py snapshot "$src" "$work/source.json"

echo "== восстановление на чистый стенд $dst"
t0=$(date +%s)
stack "$dst" "$dn" deploy/restore.sh "$copy"
stack "$dst" "$dn" compose up -d --wait >/dev/null
until [ "$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' "$dst-kc-init-1" 2>/dev/null)" = "exited 0" ]; do sleep 2; done
port=$((8090 + dn))
until curl -sf "http://localhost:$port/api/system/health" >/dev/null 2>&1 || curl -s -o /dev/null -w '%{http_code}' \
        "http://localhost:$port/auth/login" | grep -q 302; do sleep 2; done
t1=$(date +%s)
echo "восстановлено за $((t1 - t0)) с"

echo "== сверка"
python3 tools/acceptance/compare.py snapshot "$dst" "$work/restored.json"
status=0
python3 tools/acceptance/compare.py diff "$work/source.json" "$work/restored.json" || status=1
python3 tools/acceptance/compare.py check "$dst" || status=1
echo "== вход на восстановленный стенд"
TWIN_URL="http://localhost:$port" uv run --quiet --with httpx python - <<'EOF' || status=1
import asyncio, sys
sys.path.insert(0, "tools/acceptance")
from common import load_state, sign_in
async def main():
    s = load_state()
    c = await sign_in("load-admin", s["admin"]["password"])
    b = s["buildings"][0]
    tree = (await c.get(f"/api/buildings/v1/buildings/{b}/tree")).json()["floors"]
    n = (await c.get("/api/assets/v1/assets", params={"building_id": b, "limit": 1})).json()["total"]
    u = await sign_in("load-u01", s["users"]["load-u01"])
    mine = (await u.get("/api/access/v1/me/scopes")).status_code
    print(f"администратор вошёл; здание 1: этажей {len(tree)}, объектов {n}; load-u01 вошёл, его права → {mine}")
asyncio.run(main())
EOF
echo "итого: восстановление $((t1 - t0)) с; $( [ $status = 0 ] && echo 'расхождений нет' || echo 'ЕСТЬ РАСХОЖДЕНИЯ')"
exit $status
