#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./open_local.sh <id> <port>
# Example:
#   ./open_local.sh mydb 8069
#
# <id> is kept for compatibility with your current call-site,
# but no marker file is needed anymore.

ID="${1:-}"
PORT="${2:-}"
if [[ -z "${PORT}" ]]; then
  echo "Usage: $0 <id> <port>" >&2
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

# Prefer Chrome if it's running; else Safari if it's running; else open default browser.
res="$(activate_or_open_in_chrome || true)"
if [[ "$res" == "FOUND" || "$res" == "OPENED" ]]; then
  echo "Chrome: $res -> $URL"
  exit 0
fi

res="$(activate_or_open_in_safari || true)"
if [[ "$res" == "FOUND" || "$res" == "OPENED" ]]; then
  echo "Safari: $res -> $URL"
  exit 0
fi

echo "No supported browser running; opening default: $URL"
open "$URL"