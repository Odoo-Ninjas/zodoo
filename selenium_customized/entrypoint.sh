#!/bin/bash

set -e

echo "🟢 Starting xpra selenium viewer..."

# Start xpra in client (attach) mode
chmod a+x /usr/local/bin/start.sh
if [[ -z "$HOST_SRC_PATH" ]]; then
    echo "Please set environment variable HOST_SRC_PATH"
    exit 1
fi
pkill -9 -f fluxbox || true
pkill -9 -f xpra || true
pkill -9 -f xvfb || true
rm /tmp/.X100-lock || true
rm /root/.xpra -Rf || true
rm /run/user/0/xpra -Rf || true
rm /run/user/1001/xpra -Rf || true
xpra start $DISPLAY \
    --bind-tcp=0.0.0.0:5900 \
    --html=on \
    --resize-display=yes \
    --dpi=96 \
    --start-via-proxy=no \
    --start-child=/usr/local/bin/start.sh \
    --exit-with-children \
    --socket-dir=/run/user/1001/xpra \
    --no-daemon \
    --mdns=no \
    --webcam=no \
    --microphone=no \
    --keyboard-raw=yes \
    --speaker=no 