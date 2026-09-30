#!/bin/sh
# Builds the images and saves them into images/ — for a server without
# internet access or without the sources: copy the folder, then load-images.sh.
set -e
cd "$(dirname "$0")/.."
docker compose build
mkdir -p images
. ./.env 2>/dev/null || true
TAG=${DWG3D_TAG:-latest}
for img in "${DWG3D_IMAGE_API:-dwg3d-api}:$TAG" "${DWG3D_IMAGE_WEB:-dwg3d-web}:$TAG" \
           postgres:17-alpine rustfs/rustfs:1.0.0 quay.io/keycloak/keycloak:26.7.4; do
  docker image inspect "$img" >/dev/null 2>&1 || docker pull "$img"
done
docker save "${DWG3D_IMAGE_API:-dwg3d-api}:$TAG" "${DWG3D_IMAGE_WEB:-dwg3d-web}:$TAG" \
  postgres:17-alpine rustfs/rustfs:1.0.0 quay.io/keycloak/keycloak:26.7.4 | gzip > images/dwg3d-images.tar.gz
ls -lh images/
