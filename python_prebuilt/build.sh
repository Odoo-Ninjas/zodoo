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

# Read registry URL: env var first (so callers like
# zodoo's _ensure_prebuilt_python_image can pass it without the
# script having to read user-level settings), then ~/.odoo/settings
# as fallback for manual invocations.
REGISTRY_URL="${ZODOO_REGISTRY_URL:-}"
if [ -z "$REGISTRY_URL" ] && [ -f "${HOME}/.odoo/settings" ]; then
  REGISTRY_URL=$(grep -E "^ZODOO_REGISTRY_URL=" "${HOME}/.odoo/settings" 2>/dev/null | head -1 | cut -d= -f2 || true)
fi
if [ -z "$REGISTRY_URL" ]; then
  echo "ZODOO_REGISTRY_URL not set (env or ~/.odoo/settings)" >&2
  exit 1
fi

# Docker image references must not carry a URL scheme. A setting like
# "https://registry.example.com" would produce an invalid tag; fail early
# with a clear message instead of a cryptic "invalid reference format".
case "$REGISTRY_URL" in
  http://*|https://*)
    echo "ZODOO_REGISTRY_URL must not contain a URL scheme (http:// or https://): '$REGISTRY_URL'" >&2
    echo "Set it to a bare host[:port][/path], e.g. ZODOO_REGISTRY_URL=registry.zebroo.de" >&2
    exit 1
    ;;
esac
REGISTRY_URL="${REGISTRY_URL%/}"

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
