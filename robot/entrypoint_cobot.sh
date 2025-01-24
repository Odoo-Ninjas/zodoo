#!/bin/bash

set -e  # Exit immediately on error
set -x  # Enable debug output

# Constants and Environment Variables
USERNAME=robot
USER_HOME=/opt/robot
TEMP_XAUTH="/tmp/.Xauthority-$USERNAME"
HOST_SRC_PATH=${CUSTOMS_DIR}

export MOZ_DISABLE_RDD_SANDBOX=1
export MOZ_REMOTE_SETTINGS_DEVTOOLS=1
export LIBGL_ALWAYS_SOFTWARE=1

# Step 2: Fix File Ownership
echo "Fixing possible wrong user rights"
for path in /opt/src /opt/robot/.odoo /opt/robot/.odoo/images; do
  find "$path" -not -user robot -exec chown robot {} +
done
echo "Finished fixing possible missed ownerships"

# Step 3: Check DEVMODE and Environment Variables
if [[ "$DEVMODE" != "1" ]]; then
  echo "DEVMODE is not set"
  exit 0
fi

if [[ -z $HOST_SRC_PATH ]]; then
  echo "Please set the environment variable HOST_SRC_PATH"
  exit 1
fi

# Step 4: Clean Temporary Files
killall vscode || true
killall xvfb || true
killall x11vnc || true

rm -rf /tmp/.*lock /tmp/*lock /tmp/.*X11* /tmp/*vscode* /tmp/.X11-unix
ls /tmp -lhtra

# Step 5: Set Up X Authority
COOKIE=$(mcookie)
[[ -f $TEMP_XAUTH ]] && rm "$TEMP_XAUTH"
[[ -f $USER_HOME/.Xauthority ]] && rm $USER_HOME/.Xauthority

xauth -f $TEMP_XAUTH add $DISPLAY . $COOKIE
mv $TEMP_XAUTH $USER_HOME/.Xauthority
chown $USERNAME $USER_HOME/.Xauthority

cp $USER_HOME/.Xauthority /root/.Xauthority
chown root:root /root/.Xauthority

# Step 6: Start Xvfb and x11vnc
gosu $USERNAME Xvfb $DISPLAY -screen 0 "${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}x${DISPLAY_COLOR}" &
gosu $USERNAME /usr/bin/x11vnc \
  -display "$DISPLAY" \
  -auth guess \
  -forever \
  -rfbport 5900 \
  -noxdamage \
  -nopw \
  -shared \
  -ncache 10 \
	-ncache_cr \
  -scale "${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}" &

xhost +local: &

# Step 7: Configure Environment Variables and Aliases
cat <<EOL > /tmp/envvars.sh
export project_name=$project_name
export CUSTOMS_DIR=$CUSTOMS_DIR
EOL

echo "alias odoo=\"$USER_HOME/.local/bin/odoo --project-name=$project_name\"" >> "$USER_HOME/.bashrc"
echo "export DISPLAY=$DISPLAY" >> "$USER_HOME/.bashrc"
echo "export IS_COBOT_CONTAINER=1" >> "$USER_HOME/.bashrc"
echo 'eval "$(_ODOO_COMPLETE=bash_source odoo)"' >> "$USER_HOME/.bashrc"

chmod a+x "$USER_HOME/.bashrc"
chown $USERNAME "$USER_HOME/.bashrc"

# Step 8: Configure Openbox Startup
DISPLAY="$DISPLAY" gosu $USERNAME openbox &

# Step 9: Visual Studio Code Permissions
mkdir -p /opt/robot/.vscode
sudo chown robot /opt/robot/.config /opt/robot/.vscode -R

# Step 10: TCP port debugpy to socket
# [[ -e "$DEBUG_SOCKET" ]] && rm "$DEBUG_SOCKET"
# socat UNIX-LISTEN:${DEBUG_SOCKET},fork TCP:localhost:5678 &

DISPLAY="$DISPLAY" gosu $USERNAME conky &

# loop forever
sleep infinity