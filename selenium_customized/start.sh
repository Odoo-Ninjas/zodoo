#!/bin/bash
wmctrl -m
pkill -9 -f fluxbox || true
fluxbox &
geckodriver --host 0.0.0.0 --port 4444 --allow-hosts=* &
python3 /usr/local/bin/maximize_all_windows.py &


# sleep 3
# echo "Starting geckodriver test..."
# python3 /opt/test_geckodriver.py
wait