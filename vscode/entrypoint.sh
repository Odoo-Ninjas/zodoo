#!/bin/bash
set -x

echo $ROBO_ODOO_HOST > /tmp/1234

/bin/bash /usr/local/bin/set_docker_group.sh || exit -1

# --- Group fix and user shell ---
usermod -aG "$(stat -c '%G' "/var/run/docker.sock")" $USERNAME
# userdel -r $(getent passwd $OWNER_UID | cut -d: -f1) 1>/dev/null 2>&1 || true
usermod -u "${OWNER_UID}" $USERNAME
rm /home/$USERNAME/.cache/pip || true
find /home/$USERNAME -not -user $USERNAME -exec chown $USERNAME:$USERNAME {} \; || true

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

# Set permissions for Odoo folder
chown "$USERNAME:$USERNAME" "$USER_HOME/.odoo" -R || true

# Export environment variables
echo "export project_name=$project_name" > /etc/profile.d/envvars.sh
echo "export CUSTOMS_DIR=$CUSTOMS_DIR" >> /etc/profile.d/envvars.sh
chmod a+x /etc/profile.d/envvars.sh

echo "alias odoo=/usr/local/bin/odoo --project-name=\"$project_name\"" >> "$USER_HOME/.bash_aliases"
gosu $USERNAME /usr/local/bin/odoo completion -x
gosu $USERNAME gimera completion -x
/bin/bash /usr/local/bin/setup_pyenv.sh

# Configure Git
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

# Create XPRA socket directory
mkdir -p /run/user/1001/xpra
mkdir -p /run/user/1000/xpra
chown "$USERNAME:$USERNAME" /run/user/1001 -R
chown "$USERNAME:$USERNAME" /run/user/1000 -R


# remove start up annoying message
echo '#!/bin/bash' > /etc/X11/Xsession
echo 'exec "$@"' >> /etc/X11/Xsession
chmod +x /etc/X11/Xsession

# Start XPRA with VSCode as child
mkdir -p /tmp/vscode-data
chown "$USERNAME:$USERNAME" /tmp/vscode-data

# cleanup old
# xpra stop $DISPLAY || true
pkill -9 -f xpra || true
rm /tmp/.X100-lock >/dev/null 2>&1 || true
exec gosu "$USERNAME" xpra start "$DISPLAY" \
    --bind-tcp=0.0.0.0:5900 \
    --html=on \
    --resize-display=yes \
    --dpi=96 \
    --start-via-proxy=no \
    --start-child="/usr/local/bin/start.sh" \
    --exit-with-children \
    --socket-dir=/run/user/1001/xpra \
    --no-daemon \
    --mdns=no \
    --webcam=no \
    --microphone=no \
    --keyboard-raw=yes \
    --speaker=no 