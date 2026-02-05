#!/bin/bash

current_dir=$(dirname "$0")

touch /tmp/aaa

if [[ "$RUN_POSTGRES" == "1" ]]; then
    odoo up -d postgres
fi

if [[ "$ON_OSX" == "1" ]]; then
	/bin/bash "$current_dir/open_once_osx.sh" ${PROJECTNAME}  ${PORT}
elif [[ "$ON_WINDOWS_WSL" == "1" ]]; then
	/bin/bash "$current_dir/open_once_wsl.sh" ${PORT}
else
	echo "No OS-specific browser opener available."
fi