#!/bin/bash
export USERNAME=user1

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
  if [[ -e $CODE_DATADIR/User/settings.json ]]; then
    dest_path=$CODE_DATADIR/User/settings.json
    if ! grep -q ROBO  $dest_path; then
      echo Updating settings.json
      cp /opt/settings.json.template $dest_path
    fi
  fi
  sleep 1
done
) &

/usr/bin/code \
  --verbose \
  --no-sandbox \
  --extensions-dir=$EXTENSIONS_DIR \
  --user-data-dir=$CODE_DATADIR \
  --disable-gpu \
  "${HOST_SRC_PATH}" \
  &
/usr/bin/code  \
  --no-sandbox \
  --extensions-dir=$EXTENSIONS_DIR \
  --user-data-dir=$CODE_DATADIR \
  serve-web \
  --host 0.0.0.0 \
  --port 8080 \
  --server-base-path=/webcode/ \
  --without-connection-token \
  --accept-server-license-terms \
  &
wait
