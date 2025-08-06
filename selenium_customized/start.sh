#!/bin/bash
wmctrl -m
/bin/bash /usr/local/bin/geckodriver_loop.sh &
python3 /usr/local/bin/maximize_all_windows.py &
python3 /usr/local/bin/http_kill_switch.py &


# sleep 3
# echo "Starting geckodriver test..."
# python3 /opt/test_geckodriver.py &
# sleep 5
# pkill -9 -f firefox || true
wait