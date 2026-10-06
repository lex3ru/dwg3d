#!/bin/sh
# deploy/.env for a new server: .env.example with random passwords and keys.
#
#   deploy/make-env.sh https://twin.example.com [twin.example.com]
#
# The first argument is the address users open (TWIN_PUBLIC_URL), the second
# the domain Caddy gets a certificate for (TWIN_SITE; default: plain HTTP).
# An existing .env is never overwritten. The Keycloak client secret is read by
# the realm import on the first start only: when the realm already exists,
# set the same secret on the client "twin" in the Keycloak console.
set -eu
cd "$(dirname "$0")"
[ $# -ge 1 ] || { sed -n '4,5p' "$0"; exit 2; }
[ ! -e .env ] || { echo "deploy/.env уже есть — не перезаписываю" >&2; exit 1; }

rand() {
    if command -v openssl >/dev/null 2>&1; then openssl rand -hex "$1"
    else od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'; fi
}

url=${1%/}
site=${2:-:80}
umask 077
exprs=""
set_var() { exprs="$exprs
s|^$1=.*|$1=$2|"; }
set_var TWIN_PUBLIC_URL "$url"
set_var TWIN_SITE "$site"
set_var KEYCLOAK_ADMIN_PASSWORD "$(rand 12)"
set_var TWIN_ADMIN_PASSWORD "$(rand 8)"
set_var TWIN_OIDC_CLIENT_SECRET "$(rand 24)"
set_var TWIN_SECRET "$(rand 32)"
set_var POSTGRES_PASSWORD "$(rand 16)"
set_var TWIN_S3_SECRET_KEY "$(rand 24)"
set_var TWIN_DB_PASSWORD_KEYCLOAK "$(rand 16)"
set_var TWIN_DB_PASSWORD_GATEWAY "$(rand 16)"
set_var TWIN_DB_PASSWORD_PING "$(rand 16)"
set_var TWIN_DB_PASSWORD_IMPORT "$(rand 16)"
set_var TWIN_DB_PASSWORD_BUILDINGS "$(rand 16)"
set_var TWIN_DB_PASSWORD_ACCESS "$(rand 16)"
set_var TWIN_DB_PASSWORD_PEOPLE "$(rand 16)"
set_var TWIN_DB_PASSWORD_CATALOG "$(rand 16)"
set_var TWIN_DB_PASSWORD_ASSETS "$(rand 16)"
set_var TWIN_DB_PASSWORD_JOURNAL "$(rand 16)"
set_var TWIN_DB_PASSWORD_PLANNING "$(rand 16)"
# -- passwords of new databases go above this line --
set_var TWIN_SVC_SECRET_BUILDINGS "$(rand 24)"
set_var TWIN_SVC_SECRET_ASSETS "$(rand 24)"
set_var TWIN_SVC_SECRET_ACCESS "$(rand 24)"
# -- secrets of new service accounts go above this line --
sed -e "$exprs" .env.example > .env
if [ "$site" != ":80" ]; then
    sed -i -e "s|^TWIN_HTTP_PORT=.*|TWIN_HTTP_PORT=80|" -e "s|^TWIN_HTTPS_PORT=.*|TWIN_HTTPS_PORT=443|" .env
fi
echo "Готово: deploy/.env (пароли — в самом файле; первый вход — TWIN_ADMIN_USER / TWIN_ADMIN_PASSWORD)"
