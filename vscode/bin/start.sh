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

(
while true;
do
  dest_path=$CODE_DATADIR/User/settings.json
  if ! grep -q ROBO  $dest_path; then
    echo Updating settings.json
    cp /home/$USERNAME/.config/Code/User/settings.json $dest_path
  fi
  sleep 1
done
) &
# /usr/bin/code \
#   --verbose \
#   --no-sandbox \
#   --user-data-dir=/tmp/vscode-data \
#   --disable-gpu &
# --folder-uri "file:///${HOST_SRC_PATH}" \
# &
#--folder-uri "file:///${HOST_SRC_PATH}" \
# --without-connection-token \
# --accept-server-license-terms \
cd "${HOST_SRC_PATH}"
/usr/bin/code \
  "${HOST_SRC_PATH}" \
  --no-sandbox \
  --user-data-dir=/tmp/vscode-data \
  serve-web \
  --disable-gpu \
  --user-data-dir=/tmp/vscode-data \
  --host 0.0.0.0 \
  --port 8080 \
  --server-base-path=/webcode/ \
  &
wait
