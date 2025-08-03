#!/bin/bash
/bin/bash /usr/local/bin/set_docker_group.sh

if [[ "$1" == "sleep" ]]; then
	while true;
		do sleep 10000
	done
	exit 0
elif [[ "$1" == "tmux" ]]; then
	tmux new-session -d -s mysession '/bin/bash'
	while true;
		do sleep 10000
	done
	exit 0
elif [[ "$1" == "bash" ]]; then
	exec /bin/bash
fi
export PATH=/root/.local/bin:$PATH
/usr/local/bin/run.py "$@"