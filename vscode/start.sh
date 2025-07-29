#!/bin/bash

# Run wmctrl to maximize VS Code window after a short delay
(
  sleep 5
  DISPLAY=$DISPLAY wmctrl -r "Visual Studio Code" -b add,maximized_vert,maximized_horz
) &

# Now run VS Code in the foreground (last process)
exec /usr/bin/code --verbose --no-sandbox --user-data-dir=/tmp/vscode-data "$HOST_SRC_PATH"