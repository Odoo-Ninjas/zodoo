#!/bin/bash
set -x

if [[ "$DEVMODE" != "1" ]]; then
    echo "DEVMODE is not set"
    exit 0
fi

if [[ -z $HOST_SRC_PATH ]]; then
    echo "Please set environment variable HOST_SRC_PATH"
    exit 1
fi

GIT_USERNAME="$1"
GIT_EMAIL="$2"
REPO_URL="$3"
REPO_AUTH_TYPE="$4"
REPO_KEY="$5"
USER_HOME=$(eval echo ~$USERNAME)
SSHDIR="$USER_HOME/.ssh"
DISPLAY=:100

# Clean up any stale X11/Xpra
pkill -9 -f xpra || true
pkill -9 -f fluxbox || true
rm -rf /tmp/.X11-unix/X* /tmp/.X*-lock /run/user/*/xpra/* /tmp/*vscode* || true

# Setup xauth
COOKIE=$(mcookie)
TEMP_XAUTH="/tmp/.Xauthority-$USERNAME"
[[ -e "$TEMP_XAUTH" ]] && rm "$TEMP_XAUTH"
[[ -f "$USER_HOME/.Xauthority" ]] && rm "$USER_HOME/.Xauthority"

xauth -f "$TEMP_XAUTH" add "$DISPLAY" . "$COOKIE"
mv "$TEMP_XAUTH" "$USER_HOME/.Xauthority"
chown "$USERNAME:$USERNAME" "$USER_HOME/.Xauthority"
cp "$USER_HOME/.Xauthority" /root/.Xauthority
chown root:root /root/.Xauthority



# # Fluxbox setup (toolbar/workspaces)
# mkdir -p "$USER_HOME/.fluxbox"
# touch "$USER_HOME/.fluxbox/init"
# echo "session.screen0.toolbar.visible: workspace" >> "$USER_HOME/.fluxbox/init"
# chown "$USERNAME:$USERNAME" "$USER_HOME/.fluxbox" -R

# Permissions for Odoo
chown "$USERNAME:$USERNAME" "$USER_HOME/.odoo" -R || true

# Export vars
echo "export project_name=$project_name" > /tmp/envvars.sh
echo "export CUSTOMS_DIR=$CUSTOMS_DIR" >> /tmp/envvars.sh
echo "alias odoo=\"$USER_HOME/.local/bin/odoo --project-name=$project_name\"" >> "$USER_HOME/.bash_aliases"

# Git config
cd "$HOST_SRC_PATH"
if [[ -n "$GIT_USERNAME" && -n "$GIT_EMAIL" ]]; then
    git config --global user.email "$GIT_EMAIL"
    git config --global user.name "$GIT_USERNAME"
fi

if [[ -n "$REPO_URL" ]]; then
    git remote set-url origin "$REPO_URL"
fi

if [[ -n "$REPO_KEY" ]]; then
    mkdir -p "$SSHDIR"
    echo "$REPO_KEY" | base64 -d >> "$SSHDIR/id_rsa"
    chown "$USERNAME:$USERNAME" "$SSHDIR" -R
    chmod 500 "$SSHDIR"
    chmod 400 "$SSHDIR/id_rsa"
fi

echo "Git user is $GIT_USERNAME"

# Start VS Code inside xpra session
# gosu "$USERNAME" bash -c "DISPLAY=$DISPLAY /usr/bin/code --reuse-window \"$HOST_SRC_PATH\""
# Start xpra (X11 server with HTML5 and VNC support)
xpra start "$DISPLAY" \
    --bind-tcp=0.0.0.0:5900 \
    --html=on \
    --start-child=/usr/bin/code

# # Optional: Maximize VSCode window
# for i in {1..10}; do
#     if wmctrl -l | grep -q "Visual Studio Code"; then
#         wmctrl -a "Visual Studio Code"
#         xdotool key --clearmodifiers alt+F10
#         break
#     fi
#     sleep 1
# done

sleep infinity