#!/bin/bash

active_file="/tmp/pgcli_history.active"
store_file="/tmp/pgcli_history/pgcli_history.active"

if [[ -f "$store_file" ]]; then
	# echo "Restoring history file $store_file to $active_file"
	cp "$store_file" "$active_file"
fi

"$@"
retcode="$?"

if [[ -f "$active_file" ]]; then
	# echo "Storing history file $active_file to $store_file"
	cp "$active_file" "$store_file"
fi

if [[ "$retcode" != "0" ]]; then
	exit "$retcode"
fi
