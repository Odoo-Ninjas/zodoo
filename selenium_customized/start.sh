#!/bin/bash
wmctrl -m
geckodriver --host 0.0.0.0 --port 4444 --allow-hosts=* &
python3 /usr/local/bin/maximize_all_windows.py &


sleep 3
echo "Starting geckodriver test..."
python3 /opt/test_geckodriver.py &
sleep 5
pkill -9 -f firefox || true
wait