#!/bin/bash

if [[ -f /usr/lib/firefox.tar.gz ]]; then
	cd /usr/lib
	tar -xfz firefox.tar.gz &
	rm firefox.tar.gz
fi
if [[ -f /opt/venv.tar.gz ]]; then
    cd /opt
    tar -xfz venv.tar.gz &
	rm venv.tar.gz
fi

if [[ -f /usr/local/lib/python.tar.gz ]]
	cd /usr/local/lib
	tar -xfz python.tar.gz &
	rm python.tar.gz
fi
wait
/bin/bash /usr/local/bin/set_docker_group.sh || exit -1
# userdel -r $(getent passwd $OWNER_UID | cut -d: -f1) 1>/dev/null 2>&1 || true
usermod -u "${OWNER_UID}" robot
chown robot:robot -R /home/robot

tee >/tmp/archive <&0

export USERNAME=robot
chmod a+rw -R "$ROBO_UPLOAD_FILES_DIR_LOCAL"
chmod a+rw -R /opt/output
[ -e /opt/src/.robot-vars ] && chown $USERNAME /opt/src/.robot-vars

usermod -aG $DOCKER_GID robot
exec gosu $USERNAME python3 robotest.py "$@"