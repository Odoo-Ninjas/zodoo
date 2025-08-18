#!/bin/bash
set -x

export TEMPLATE_USERNAME=usertemplate1
export USERNAME=user1

/bin/bash /usr/local/bin/set_docker_group.sh || exit -1

# --- Group fix and user shell ---
groupadd $USERNAME && \
useradd -g $USERNAME -m $USERNAME -u $OWNER_UID
usermod -aG "$(stat -c '%G' "/var/run/docker.sock")" $USERNAME
rm /home/$USERNAME/.cache/pip || true
rsync --chown $USERNAME:$USERNAME /home/$TEMPLATE_USERNAME/ /home/$USERNAME/ -ar

quick_chown() {
    [[ -e "$1.bak" ]] && rm -Rf "$1.bak"
    [[ ! -e "$1" ]] && exit 0
    mv "$1" "$1.bak"
    rsync --chown $USERNAME:$USERNAME "$1.bak/" "$1/" -ar || exit 1
    rm -Rf $1.bak
}
install_extensions() {
    mkdir -p "$EXTENSIONS_DIR" "$CODE_DATADIR"
    mkdir -p "$CODE_DATADIR/User"
    chown -R "$USERNAME:$USERNAME" "$EXTENSIONS_DIR" "$CODE_DATADIR"
    chown -R "$USERNAME:$USERNAME" /usr/share/code/resources -R
    cp /opt/settings.json.template "$CODE_DATADIR/User/settings.json"
    local name
    for name in "$@"; do
        gosu $USERNAME \
            /usr/bin/code \
                --no-sandbox \
                --disable-gpu \
                --extensions-dir="$EXTENSIONS_DIR" \
                --user-data-dir="$CODE_DATADIR" \
                --install-extension "$name" || exit 5
    done
}

if [[ "$DEVMODE" != "1" ]]; then
    echo "DEVMODE is not set"
    exit 0
fi

if [[ -z $HOST_SRC_PATH ]]; then
    echo "Please set environment variable HOST_SRC_PATH"
    exit 1
fi

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

rsync --chown $USERNAME:$USERNAME /home/$TEMPLATE_USERNAME/.pyenv/ /home/$USERNAME/.pyenv/ -ar
find /home/$USERNAME -type l -lname '/home/$TEMPLATE_USERNAME/*' | while read link; do
    target=$(readlink "$link")
    new_target="${target/\/home\/$TEMPLATE_USERNAME/\/home\/$USERNAME}"
    echo "Relinking $link → $new_target"
    ln -snf "$new_target" "$link"
done
/bin/bash /usr/local/bin/replace_in_files.sh /home/$USERNAME $TEMPLATE_USERNAME $USERNAME

# Configure Git
cd "$HOST_SRC_PATH"



# Create XPRA socket directory
mkdir -p /run/user/1001/xpra
mkdir -p /run/user/1000/xpra
chown "$USERNAME:$USERNAME" /run/user/1001 -R
chown "$USERNAME:$USERNAME" /run/user/1000 -R


# remove start up annoying message
echo '#!/bin/bash' > /etc/X11/Xsession
echo 'exec "$@"' >> /etc/X11/Xsession
chmod +x /etc/X11/Xsession

# cleanup old
# xpra stop $DISPLAY || true
pkill -9 -f xpra || true
rm /tmp/.X100-lock >/dev/null 2>&1 || true
chmod a+x /usr/local/bin/start.sh


if [[ -e $VSCODE_PERMA_EXTENSIONS_FOLDER/.notempty ]]; then
    rsync --chown $USERNAME:$USERNAME $VSCODE_PERMA_EXTENSIONS_FOLDER/ "$EXTENSIONS_DIR/" -ar || exit 1
fi
VSCODE_PERMA_EXTENSIONS_FOLDER

install_extensions \
    d-biehl.robotcode \
    MarcWimmerITE.odoobrowserITE \
    ms-python.python
rsync "$EXTENSIONS_DIR/" "$VSCODE_PERMA_EXTENSIONS_FOLDER/" -ar
touch "$VSCODE_PERMA_EXTENSIONS_FOLDER/.notempty"

#/usr/bin/code --install-extension vscodevim.vim && \
#RUN /usr/bin/code --disable-extension vscodevim.vim
# install_extensions vscodevim.vim

quick_chown "$EXTENSIONS_DIR"
quick_chown "$CODE_DATADIR"

/bin/bash /usr/local/bin/set_assets_path_vscode_web.sh || true

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
    --swap-keys=no \
    --speaker=no
