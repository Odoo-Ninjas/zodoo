#!/bin/bash
tee >/tmp/archive <&0

echo "Fixing possible wrong user rights"
find /opt/src -not -user robot -exec chown robot {} \;
find /opt/robot/.odoo -not -user robot -exec chown robot {} \;
find /opt/robot/.odoo/images -not -user robot -exec chown robot {} \;
echo "Finished fixxing possible missed ownerships"

export USERNAME=robot
# export DISPLAY=:99
# Xvfb $DISPLAY -screen 0 1920x1080x24 &
# Step 5: Set Up X Authority
# export USER_HOME=/opt/robot
# COOKIE=$(mcookie)
# TEMP_XAUTH="/tmp/.Xauthority-$USERNAME"
# [[ -f $TEMP_XAUTH ]] && rm "$TEMP_XAUTH"
# [[ -f $USER_HOME/.Xauthority ]] && rm $USER_HOME/.Xauthority

# xauth -f $TEMP_XAUTH add $DISPLAY . $COOKIE
# mv $TEMP_XAUTH $USER_HOME/.Xauthority
# chown $USERNAME $USER_HOME/.Xauthority

# cp $USER_HOME/.Xauthority /root/.Xauthority
# chown root:root /root/.Xauthority

geckodriver --port 4444 &  # --log trace  &
exec gosu $USERNAME python3 robotest.py "$@"