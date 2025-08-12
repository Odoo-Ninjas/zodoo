#!/bin/bash
if [ -z "$DOCKER_GID" ]; then \
	echo "Please provide environment variable DOCKER_GID for entrypoint startup."; \
	exit 1; \
fi
if [[ ! -z "$(getent group $DOCKER_GID | cut -d: -f1)" ]] ;then
	groupmod -g 555 $(getent group $DOCKER_GID | cut -d: -f1) || true
fi

groupmod -g $DOCKER_GID docker 2>/dev/null || groupadd -g $DOCKER_GID docker
