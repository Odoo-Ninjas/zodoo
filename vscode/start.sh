#!/bin/bash

# Run wmctrl to maximize VS Code window after a short delay
(
  sleep 5
  while true; do
    window_id=$(wmctrl -l | awk 'NR==1 {print $1}')
    if [ -n "$window_id" ]; then
      echo "🟢 Found window: $window_id — maximizing..."
      wmctrl -i -r "$window_id" -b add,maximized_vert,maximized_horz
    fi
    sleep 1
  done
) &

# Now run VS Code in the foreground (last process)
echo "Starting up vscode..."

echo $ROBO_ODOO_HOST > /tmp/123
exec /usr/bin/code --verbose --no-sandbox --user-data-dir=/tmp/vscode-data "$HOST_SRC_PATH"