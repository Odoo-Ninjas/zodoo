#!/bin/bash
set -x

current_dir=$(dirname "$0")
SETUP_PYENV=1 /bin/bash ${current_dir}/prepare.sh || exit -1
# /Users/marcwimmer/.pyenv/versions/odoo16/bin/python3 ${current_dir}/start_with_debugpy.py
echo "Debug started"

echo Open your browser on http://localhost:${PROXY_PORT}

# if [[ "$ON_OSX" == "1" ]]; then
# 	/bin/bash "$current_dir/open_once_osx.sh" ${PROJECTNAME} ${PORT} ${DEBUG_BROWSER}
# elif [[ "$ON_WINDOWS_WSL" == "1" ]]; then
# 	/bin/bash "$current_dir/open_once_wsl.sh" ${PORT}
# else
# 	echo "No OS-specific browser opener available."
# fi
