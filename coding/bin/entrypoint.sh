#!/bin/bash
set -e

# openvscode-server binary location in gitpod image
OPENVSCODE="/home/.openvscode-server/bin/openvscode-server"

if [[ -x "$OPENVSCODE" ]]; then
    exec "$OPENVSCODE" \
        --host 0.0.0.0 \
        --port 8080 \
        --server-base-path /code1 \
        --without-connection-token \
        /opt/src
else
    # Fallback to code-server
    exec code-server \
        --bind-addr 0.0.0.0:8080 \
        --auth none \
        --disable-telemetry \
        /opt/src
fi
