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

export DISPLAY=:1

pkill -9 -f vscode || true
pkill -9 -f x11vnc || true
pkill -9 -f Xvfb || true
pkill -9 -f xhost || true

# vorsichtige Bereinigung von temporären Dateien
rm -rf /tmp/.X11-unix/X1 /tmp/.X1-lock /tmp/*vscode* || true

# xauthority initialisieren
COOKIE=$(mcookie)
TEMP_XAUTH="/tmp/.Xauthority-$USERNAME"
[[ -e "$TEMP_XAUTH" ]] && rm "$TEMP_XAUTH"
[[ -f "$USER_HOME/.Xauthority" ]] && rm "$USER_HOME/.Xauthority"

xauth -f "$TEMP_XAUTH" add "$DISPLAY" . "$COOKIE"
mv "$TEMP_XAUTH" "$USER_HOME/.Xauthority"
chown "$USERNAME:$USERNAME" "$USER_HOME/.Xauthority"
cp "$USER_HOME/.Xauthority" /root/.Xauthority
chown root:root /root/.Xauthority
rsync "$USER_HOME/.vnc/" /root/.vnc/ -ar || true

# Starte Xvfb
Xvfb "$DISPLAY" -screen 0 "${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}x${DISPLAY_COLOR}" &
XVFB_PID=$!

# Warte, bis DISPLAY bereit ist
for i in {1..10}; do
    if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
        break
    fi
    echo "Waiting for Xvfb to be ready..."
    sleep 0.5
done

# Zugriff auf DISPLAY erlauben
xhost +local:

# Starte VNC Server
/usr/bin/x11vnc -display "$DISPLAY" -auth "$USER_HOME/.Xauthority" \
    -forever \
    -rfbport 5900 \
    -noxdamage \
    -ncache 10 \
    -ncache_cr \
    -nopw \
    -shared \
    -scale "${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}" &

# Umgebungsvariablen exportieren
echo "export project_name=$project_name" > /tmp/envvars.sh
echo "export CUSTOMS_DIR=$CUSTOMS_DIR" >> /tmp/envvars.sh
echo "alias odoo=\"$USER_HOME/.local/bin/odoo --project-name=$project_name\"" >> "$USER_HOME/.bash_aliases"

# Fluxbox starten
mkdir -p "$USER_HOME/.fluxbox"
touch "$USER_HOME/.fluxbox/init"
echo "session.screen0.toolbar.visible: workspace" >> "$USER_HOME/.fluxbox/init"
#echo session.screen0.iconbar.mode: none >> "$USER_HOME/.fluxbox/init"
chown "$USERNAME:$USERNAME" "$USER_HOME/.fluxbox" -R
gosu "$USERNAME" fluxbox &

# Rechte für Odoo-Verzeichnis setzen
chown "$USERNAME:$USERNAME" /home/user1/.odoo -R || true

# Git konfigurieren
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

# VSCode starten und maximieren
gosu $USERNAME bash -c 'pgrep -x code > /dev/null || DISPLAY=:1 /usr/bin/code --reuse-window "$HOST_SRC_PATH"'
sleep 2
# Warte auf VSCode-Fenster
for i in {1..10}; do
    if wmctrl -l | grep -q "Visual Studio Code"; then
        wmctrl -a "Visual Studio Code"
        xdotool key --clearmodifiers alt+F10
        break
    fi
    sleep 1
done

sleep infinity