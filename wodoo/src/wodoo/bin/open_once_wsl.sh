#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-}"
if [[ -z "$PORT" ]]; then
  echo "Usage: $0 <port>" >&2
  exit 1
fi

URL="http://localhost:${PORT}"

# Convert WSL path safely
WIN_URL="$URL"

powershell.exe -NoProfile -Command "
  \$url = '$WIN_URL'

  # Try Chrome first
  \$chrome = Get-Process chrome -ErrorAction SilentlyContinue
  if (\$chrome) {
    Start-Process chrome \$url
    exit
  }

  # Then Edge
  \$edge = Get-Process msedge -ErrorAction SilentlyContinue
  if (\$edge) {
    Start-Process msedge \$url
    exit
  }

  # Fallback: default browser
  Start-Process \$url
"