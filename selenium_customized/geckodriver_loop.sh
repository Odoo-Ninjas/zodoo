#!/bin/bash
while true
do
	geckodriver \
		--host 0.0.0.0 \
		--port 4444 \
		--allow-hosts seleniumvnc localhost 127.0.0.1 \
		--log debug \
		> /var/log/geckodriver.log
	echo "Restarting crashed geckodriver..."
	sleep 1
done