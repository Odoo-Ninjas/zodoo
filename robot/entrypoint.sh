#!/bin/bash
/bin/bash /usr/local/bin/set_docker_group.sh || exit -1
# userdel -r $(getent passwd $OWNER_UID | cut -d: -f1) 1>/dev/null 2>&1 || true
usermod -u "${OWNER_UID}" robot
# robot's home is /opt/robot (see useradd -d in the Dockerfile); after the
# usermod above its files still belong to the old uid, so the harness could
# not write robo_params.json / its temp suites into the working dir.
ROBOT_HOME="$(getent passwd robot | cut -d: -f6)"
for dir in /home/robot "$ROBOT_HOME"; do
  [ -d "$dir" ] && find "$dir" ! -user robot -exec chown robot {} + >/dev/null 2>&1 || true
done

tee >/tmp/archive <&0

export USERNAME=robot
chmod a+rw -R "$ROBO_UPLOAD_FILES_DIR_LOCAL"
chmod a+rw -R /opt/output
[ -e /opt/src/.robot-vars ] && chown $USERNAME /opt/src/.robot-vars

usermod -aG $DOCKER_GID robot
exec gosu $USERNAME python3 robotest.py "$@"
