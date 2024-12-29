#!/bin/bash
tee >/tmp/archive <&0

echo "Fixing possible wrong user rights"
find /opt/src -not -user robot -exec chown robot {} \;
find /opt/robot/.odoo -not -user robot -exec chown robot {} \;
find /opt/robot/.odoo/images -not -user robot -exec chown robot {} \;
echo "Finished fixxing possible missed ownerships"

geckodriver --port 4444 &
exec gosu robot python3 robotest.py "$@"