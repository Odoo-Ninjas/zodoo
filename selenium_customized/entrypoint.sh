#!/bin/bash

set -e

echo "🟢 Starting xpra selenium viewer..."

# Start xpra in client (attach) mode
chmod a+x /start.sh
pkill -9 -f fluxbox || true
pkill -9 -f xpra || true
rm /tmp/.X100-lock || true
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