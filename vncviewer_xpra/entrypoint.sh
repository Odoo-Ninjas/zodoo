#!/bin/bash

set -e
set -x

# Default VNC server or from ENV
VNC_SERVER=${VNC_SERVER:-""}

if [[ -z "$VNC_SERVER" ]]; then
    echo "❌ Error: VNC_SERVER environment variable is not set."
    echo "Please run with: docker run -e VNC_SERVER=host:port ..."
    exit 1
fi

echo "🟢 Starting xpra VNC viewer session to $VNC_SERVER ..."

# Ensure xpra cleans up old sockets
# xpra stop $DISPLAY || true
pkill -9 -f xpra || true


mkdir -p /run/user/1001/xpra 
vncpasswd -f <<< "$VNC_PASSWORD" > /run/user/1001/vncpasswd
chmod 600 /run/user/1001/vncpasswd

# Start xpra in client (attach) mode
chmod a+x /start.sh
xpra start \
    --bind-tcp=0.0.0.0:5900 \
    --html=on \
    --resize-display=yes \
    --dpi=96 \
    --start-via-proxy=no \
    --start-child="/start.sh" \
    --exit-with-children \
    --socket-dir=/run/user/1001/xpra \
    --no-daemon \
    --mdns=no \
    --webcam=no \
    --microphone=no \
    --keyboard-raw=yes \
    --speaker=no 