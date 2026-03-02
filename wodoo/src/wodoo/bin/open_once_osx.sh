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
  /usr/bin/osascript <<'APPLESCRIPT' "${URL}"
on run argv
  set theUrl to item 1 of argv
  tell application "Google Chrome"
    if not (running) then return "NOT_RUNNING"

    repeat with w in windows
      repeat with t in tabs of w
        if (URL of t as text) is theUrl then
          set active tab index of w to (index of t)
          set index of w to 1
          activate
          return "FOUND"
        end if
      end repeat
    end repeat

    -- Not found: open a new tab (prefer existing window)
    if (count of windows) is 0 then
      make new window
    end if
    tell window 1
      set newTab to make new tab with properties {URL:theUrl}
      set active tab index to (index of newTab)
    end tell
    activate
    return "OPENED"
  end tell
end run
APPLESCRIPT
}

activate_or_open_in_firefox() {
  /usr/bin/osascript <<'APPLESCRIPT' "${URL}"
on run argv
  set theUrl to item 1 of argv
  tell application "Firefox"
    if not (running) then return "NOT_RUNNING"
    activate
    -- Firefox hat keine direkte Tab-URL-Abfrage via AppleScript,
    -- daher öffnen wir einfach die URL über open location
    open location theUrl
    return "OPENED"
  end tell
end run
APPLESCRIPT
}

activate_or_open_in_safari() {
  /usr/bin/osascript <<'APPLESCRIPT' "${URL}"
on run argv
  set theUrl to item 1 of argv
  tell application "Safari"
    if not (running) then return "NOT_RUNNING"

    repeat with w in windows
      repeat with t in tabs of w
        try
          if (URL of t as text) is theUrl then
            set current tab of w to t
            set index of w to 1
            activate
            return "FOUND"
          end if
        end try
      end repeat
    end repeat

    -- Not found: open a new tab (prefer existing window)
    if (count of windows) is 0 then
      make new document
    end if
    tell window 1
      set newTab to make new tab with properties {URL:theUrl}
      set current tab to newTab
    end tell
    activate
    return "OPENED"
  end tell
end run
APPLESCRIPT
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
