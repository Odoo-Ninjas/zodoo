#!/bin/bash
/bin/bash /usr/local/bin/set_docker_group.sh || exit -1

tee >/tmp/archive <&0


export USERNAME=robot
chmod a+rw -R "$ROBO_UPLOAD_FILES_DIR_LOCAL"
chmod a+rw -R /opt/output
[ -e /opt/src/.robot-vars ] &&  chown $USERNAME /opt/src/.robot-vars

usermod -aG $DOCKER_GID robot
exec gosu $USERNAME python3 robotest.py "$@"