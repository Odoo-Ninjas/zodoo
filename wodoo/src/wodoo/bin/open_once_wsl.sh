#!/usr/bin/env bash
set -euo pipefail

# Usage: script.sh <id> <port>
ID="${1:-}"
PORT="${2:-}"

if [[ -z "$ID" || -z "$PORT" ]]; then
  echo "Usage: $(basename "$0") <id> <port>" >&2
  exit 2
fi

URL="http://localhost:${PORT}"
MARKER="/tmp/odoo_browser_opened_${ID}"
LOCK="/tmp/odoo_browser_opened_${ID}.lock"

# Prevent races (script triggered multiple times quickly)
exec 9>"$LOCK"
if command -v flock >/dev/null 2>&1; then
  if ! flock -n 9; then
    echo "Already running for id=${ID}; skipping."
    exit 0
  fi
fi

open_windows_url() {
  # Opens with default browser on Windows
  powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass \
    -Command "Start-Process '$URL'" >/dev/null 2>&1
}

activate_browser_and_open() {
  # Try to bring an existing browser window to front (Chrome/Edge/Firefox),
  # then open URL (usually focuses existing window and opens a new tab).
  powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command @"
`$url = '$URL'

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class Win32 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
}
'@

function Focus-ProcessWindow([string]`$name) {
  `$p = Get-Process -Name `$name -ErrorAction SilentlyContinue |
       Where-Object { `$_.MainWindowHandle -ne 0 } |
       Select-Object -First 1
  if (`$p) {
    [Win32]::ShowWindowAsync(`$p.MainWindowHandle, 9) | Out-Null  # SW_RESTORE
    [Win32]::SetForegroundWindow(`$p.MainWindowHandle) | Out-Null
    return `$true
  }
  return `$false
}

`$focused = (Focus-ProcessWindow 'chrome') -or (Focus-ProcessWindow 'msedge') -or (Focus-ProcessWindow 'firefox')

# Open URL in default browser (will reuse focused browser if it's default; otherwise still opens)
Start-Process `$url | Out-Null

exit 0
"@ >/dev/null 2>&1
}

if [[ ! -f "$MARKER" ]]; then
  echo "Opening browser once (Windows): $URL"
  open_windows_url
  touch "$MARKER"
else
  echo "Browser already opened once. Activating (if possible) and opening: $URL"
  if ! activate_browser_and_open; then
    # Fallback
    open_windows_url
  fi
fi
