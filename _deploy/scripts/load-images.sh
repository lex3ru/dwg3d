#!/bin/sh
# Loads the images saved by save-images.sh:  scripts/load-images.sh [images/dwg3d-images.tar.gz]
set -e
cd "$(dirname "$0")/.."
gunzip -c "${1:-images/dwg3d-images.tar.gz}" | docker load
