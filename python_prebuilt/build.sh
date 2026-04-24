#!/bin/bash
# Builds and pushes the prebuilt Python image for this host's native architecture.
# Usage: build.sh <PYTHON_VERSION> [--push] [--base-image IMG]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_VERSION="${1:-}"
shift || true
PUSH=0
BASE_IMAGE="ubuntu:22.04"
while [ $# -gt 0 ]; do
  case "$1" in
    --push) PUSH=1 ;;
    --base-image) BASE_IMAGE="$2"; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
  shift
done

if [ -z "$PYTHON_VERSION" ]; then
  echo "Usage: $0 <PYTHON_VERSION> [--push] [--base-image IMG]" >&2
  exit 1
fi

# Read registry URL from zodoo settings
REGISTRY_URL=$(grep -E "^ZODOO_REGISTRY_URL=" ~/.odoo/settings | head -1 | cut -d= -f2)
if [ -z "$REGISTRY_URL" ]; then
  echo "ZODOO_REGISTRY_URL not set in ~/.odoo/settings" >&2
  exit 1
fi

ARCH=$(uname -m | sed "s/x86_64/amd64/;s/aarch64/arm64/")
TAG="${REGISTRY_URL}/zodoo/python:${PYTHON_VERSION}-${ARCH}"

echo "Building $TAG (base=$BASE_IMAGE, arch=$ARCH)..."
docker build \
  --build-arg "ODOO_PYTHON_VERSION=${PYTHON_VERSION}" \
  --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
  -t "$TAG" \
  "$SCRIPT_DIR"

if [ "$PUSH" = "1" ]; then
  echo "Pushing $TAG..."
  docker push "$TAG"
fi

echo "Done: $TAG"
