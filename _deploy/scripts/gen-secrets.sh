#!/bin/sh
# Prints random passwords and secrets for .env:  scripts/gen-secrets.sh >> .env
set -e
gen() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }
echo "POSTGRES_PASSWORD=$(gen 32)"
echo "DWG3D_S3_SECRET_KEY=$(gen 40)"
echo "KEYCLOAK_ADMIN_PASSWORD=$(gen 24)"
echo "DWG3D_OIDC_CLIENT_SECRET=$(gen 40)"
echo "DWG3D_ADMIN_PASSWORD=$(gen 16)"
echo "DWG3D_SECRET=$(gen 48)"
