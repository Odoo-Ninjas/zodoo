#!/usr/bin/env bash
set -euo pipefail

# === Config (override via env or args) ===
CDN_PATH="${1:-${CDN_PATH:-/vscode-cdn}}"
UNPKG_PATH="${2:-${UNPKG_PATH:-/vscode-unpkg}}"

# Likely path for VS Code .deb (server side used by serve-web / code-tunnel)
PRODUCT_JSON="/usr/share/code/resources/app/product.json"

if [[ ! -f "$PRODUCT_JSON" ]]; then
  echo "ERROR: product.json not found at $PRODUCT_JSON"
  echo "If you installed VS Code elsewhere, adjust PRODUCT_JSON."
  exit 1
fi

echo "Patching:"
echo "  product.json: $PRODUCT_JSON"
echo "  assetUrl     => $CDN_PATH"
echo "  nlsBaseUrl   => $UNPKG_PATH"

cp -a "$PRODUCT_JSON" "${PRODUCT_JSON}.bak.$(date +%Y%m%d%H%M%S)"

if command -v jq >/dev/null 2>&1; then
  # Use jq (robust)
  TMP="$(mktemp)"
  jq \
    --arg asset "$CDN_PATH" \
    --arg nls   "$UNPKG_PATH" \
    '
    .extensionsGallery = (.extensionsGallery // {}) |
    .extensionsGallery.assetUrl = $asset |
    .nlsBaseUrl = $nls
    ' "$PRODUCT_JSON" > "$TMP"
  mv "$TMP" "$PRODUCT_JSON"
else
  echo "jq not found, using sed fallback."
  # Ensure the keys exist; if not, append minimal structure
  grep -q '"extensionsGallery"' "$PRODUCT_JSON" || \
    sed -i 's#^{#{\n  "extensionsGallery": {},#' "$PRODUCT_JSON"

  # assetUrl (create or replace)
  if grep -q '"assetUrl"[[:space:]]*:' "$PRODUCT_JSON"; then
    sed -i "s#\"assetUrl\"[[:space:]]*:[[:space:]]*\"[^\"]*\"#\"assetUrl\": \"${CDN_PATH//\//\\/}\"#g" "$PRODUCT_JSON"
  else
    sed -i "s#\"extensionsGallery\"[[:space:]]*:[[:space:]]*{#\"extensionsGallery\": { \"assetUrl\": \"${CDN_PATH//\//\\/}\",#g" "$PRODUCT_JSON"
  fi

  # nlsBaseUrl (create or replace)
  if grep -q '"nlsBaseUrl"[[:space:]]*:' "$PRODUCT_JSON"; then
    sed -i "s#\"nlsBaseUrl\"[[:space:]]*:[[:space:]]*\"[^\"]*\"#\"nlsBaseUrl\": \"${UNPKG_PATH//\//\\/}\"#g" "$PRODUCT_JSON"
  else
    # add top-level key before the last }
    sed -i "s#}\$#  , \"nlsBaseUrl\": \"${UNPKG_PATH//\//\\/}\"\n}#g" "$PRODUCT_JSON"
  fi
fi

echo "Done. Backup at ${PRODUCT_JSON}.bak.*"
echo "Restart your VS Code Web service, then verify asset requests hit ${CDN_PATH} and ${UNPKG_PATH} on your domain."
