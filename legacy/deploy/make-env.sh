#!/bin/sh
# A .env for a new server: .env.example with random passwords and keys.
#
#   deploy/make-env.sh https://plans.example.com [plans.example.com]
#
# The first argument is the address users open (DWG3D_PUBLIC_URL), the second
# the domain Caddy gets a certificate for (DWG3D_SITE; default: plain HTTP).
# An existing .env is never overwritten. The Keycloak client secret is read by
# the realm import on the first start only: when the realm already exists,
# set the same secret on the client "dwg3d" in the Keycloak console.
set -eu
cd "$(dirname "$0")/.."
[ $# -ge 1 ] || { sed -n '4,5p' "$0"; exit 2; }
[ ! -e .env ] || { echo ".env уже есть — не перезаписываю" >&2; exit 1; }

rand() {
    if command -v openssl >/dev/null 2>&1; then openssl rand -hex "$1"
    else od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'; fi
}

url=${1%/}
site=${2:-:80}
umask 077
sed -e "s|^DWG3D_PUBLIC_URL=.*|DWG3D_PUBLIC_URL=$url|" \
    -e "s|^DWG3D_SITE=.*|DWG3D_SITE=$site|" \
    -e "s|^KEYCLOAK_ADMIN_PASSWORD=.*|KEYCLOAK_ADMIN_PASSWORD=$(rand 12)|" \
    -e "s|^DWG3D_ADMIN_PASSWORD=.*|DWG3D_ADMIN_PASSWORD=$(rand 8)|" \
    -e "s|^DWG3D_OIDC_CLIENT_SECRET=.*|DWG3D_OIDC_CLIENT_SECRET=$(rand 24)|" \
    -e "s|^DWG3D_SECRET=.*|DWG3D_SECRET=$(rand 32)|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand 16)|" \
    -e "s|^DWG3D_S3_SECRET_KEY=.*|DWG3D_S3_SECRET_KEY=$(rand 24)|" \
    .env.example > .env
if [ "$site" != ":80" ]; then
    sed -i -e "s|^DWG3D_HTTP_PORT=.*|DWG3D_HTTP_PORT=80|" -e "s|^DWG3D_HTTPS_PORT=.*|DWG3D_HTTPS_PORT=443|" .env
fi
echo "Готово: .env (пароли — в самом файле; первый вход — DWG3D_ADMIN_USER / DWG3D_ADMIN_PASSWORD)"
