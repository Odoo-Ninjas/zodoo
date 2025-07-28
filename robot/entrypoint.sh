#!/bin/bash
tee >/tmp/archive <&0


export USERNAME=robot
chmod a+rw -R "$ROBO_UPLOAD_FILES_DIR_LOCAL"
chmod a+rw -R /opt/output
[ -e /opt/src/.robot-vars ] &&  chown $USERNAME /opt/src/.robot-vars
exec gosu $USERNAME python3 robotest.py "$@"