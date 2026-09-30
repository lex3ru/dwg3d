#!/bin/sh
# A backup right now (the backup service makes one a day by itself).
set -e
cd "$(dirname "$0")/.."
docker compose exec backup python -m dwg3d backup /backups --keep "${DWG3D_BACKUP_KEEP:-14}"
