#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./open_local.sh <id> <port> [browser]
# Example:
#   ./open_local.sh mydb 8069 firefox
#
# browser: chrome | firefox | safari (optional, auto-detects if omitted)
# <id> is kept for compatibility with your current call-site,
# but no marker file is needed anymore.

ID="${1:-}"
PORT="${2:-}"
BROWSER="${3:-}"
if [[ -z "${PORT}" ]]; then
  echo "Usage: $0 <id> <port> [chrome|firefox|safari]" >&2
  exit 1
fi

URL="http://localhost:${PORT}"

activate_or_open_in_chrome() {
  local running
  running=$(/usr/bin/osascript -e 'tell application "System Events" to return (exists process "Google Chrome")' 2>/dev/null || echo "false")
  if [[ "$running" != "true" ]]; then
    echo "NOT_RUNNING"
    return
  fi
  open -a "Google Chrome" "$URL"
  /usr/bin/osascript -e 'tell application "Google Chrome" to activate' 2>/dev/null || true
  echo "OPENED"
}

activate_or_open_in_firefox() {
  local running
  running=$(/usr/bin/osascript -e 'tell application "System Events" to return (exists process "Firefox")' 2>/dev/null || echo "false")
  if [[ "$running" != "true" ]]; then
    echo "NOT_RUNNING"
    return
  fi
  # open -a umgeht den Standardbrowser und öffnet direkt in Firefox
  open -a Firefox "$URL"
  /usr/bin/osascript -e 'tell application "Firefox" to activate' 2>/dev/null || true
  echo "OPENED"
}

activate_or_open_in_safari() {
  local running
  running=$(/usr/bin/osascript -e 'tell application "System Events" to return (exists process "Safari")' 2>/dev/null || echo "false")
  if [[ "$running" != "true" ]]; then
    echo "NOT_RUNNING"
    return
  fi
  open -a Safari "$URL"
  /usr/bin/osascript -e 'tell application "Safari" to activate' 2>/dev/null || true
  echo "OPENED"
}

open_in_browser() {
  local name="$1"
  local fn="$2"
  local res
  res="$($fn || true)"
  if [[ "$res" == "FOUND" || "$res" == "OPENED" ]]; then
    echo "$name: $res -> $URL"
    exit 0
  fi
}

case "$(echo "${BROWSER}" | tr '[:upper:]' '[:lower:]')" in
  chrome)
    open_in_browser "Chrome" activate_or_open_in_chrome
    echo "Chrome not running; opening default: $URL"
    open "$URL"
    ;;
  firefox)
    open_in_browser "Firefox" activate_or_open_in_firefox
    echo "Firefox not running; opening default: $URL"
    open "$URL"
    ;;
  safari)
    open_in_browser "Safari" activate_or_open_in_safari
    echo "Safari not running; opening default: $URL"
    open "$URL"
    ;;
  *)
    # Auto-detect: prefer Chrome, then Firefox, then Safari
    open_in_browser "Chrome"  activate_or_open_in_chrome
    open_in_browser "Firefox" activate_or_open_in_firefox
    open_in_browser "Safari"  activate_or_open_in_safari
    echo "No supported browser running; opening default: $URL"
    open "$URL"
    ;;
esac
