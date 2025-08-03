#!/bin/bash
if [ -z "$DOCKER_GID" ]; then \
	echo "Please provide a valid DOCKER_GID as build argument"; \
	exit 1; \
fi
groupmod -g 555 $(getent group $DOCKER_GID | cut -d: -f1) || true
groupmod -g $DOCKER_GID docker || groupadd -g $DOCKER_GID docker