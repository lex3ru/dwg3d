#!/bin/sh
# Another stack beside the working one, for acceptance runs: its own containers, volumes and ports.
#
#   tools/acceptance/stack.sh <name> <n> <command…>
#
# <name> becomes the compose project, <n> (1, 2, …) shifts the ports: the interface on 8090+n, the
# database on 5433+n and so on. The command is run with that environment — a compose command
# (`compose up -d --wait`, `compose down -v`) or any script that calls compose, such as
# deploy/restore.sh. Secrets come from deploy/.env, as for the working stack.
#
#   tools/acceptance/stack.sh twin-accept 1 compose up -d --wait
#   tools/acceptance/stack.sh twin-restore 2 deploy/restore.sh deploy/backups/<copy>
set -eu
[ $# -ge 3 ] || { sed -n '2,13p' "$0"; exit 2; }
name=$1 n=$2
shift 2
cd "$(dirname "$0")/../.."
export COMPOSE_PROJECT_NAME="$name"
export TWIN_HTTP_PORT=$((8090 + n)) TWIN_HTTPS_PORT=$((8453 + n)) TWIN_DB_PORT=$((5433 + n))
export TWIN_NATS_PORT=$((4223 + n)) TWIN_KEYCLOAK_PORT=$((8181 + n)) TWIN_S3_PORT=$((9002 + n))
export TWIN_PUBLIC_URL="http://localhost:$TWIN_HTTP_PORT" TWIN_URL="http://localhost:$TWIN_HTTP_PORT"
if [ "$1" = compose ]; then
    shift
    exec docker compose -f deploy/docker-compose.yml "$@"
fi
exec "$@"
