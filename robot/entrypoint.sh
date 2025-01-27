#!/bin/bash
tee >/tmp/archive <&0

echo "Fixing possible wrong user rights"
find /opt/src -not -user robot -exec chown robot {} \;
find /opt/robot/.odoo -not -user robot -exec chown robot {} \;
find /opt/robot/.odoo/images -not -user robot -exec chown robot {} \;
echo "Finished fixxing possible missed ownerships"

export USERNAME=robot
chmod a+rw -R "$ROBO_UPLOAD_FILES_DIR_LOCAL"
exec gosu $USERNAME python3 robotest.py "$@"