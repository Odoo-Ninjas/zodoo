#!/bin/bash
set -x
/bin/bash /usr/local/bin/set_docker_group.sh || exit -1
exec "$@"