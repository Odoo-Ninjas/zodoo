#!/bin/bash

current_dir=$(dirname "$0")
SETUP_PYENV=1 /bin/bash ${current_dir}/prepare.sh || exit -1

CURRENT_FILE="${CURRENT_FILE#$(pwd)/}"

if [[ "$CURRENT_FILE" == */tests/* ]]; then
    code --reuse-window --goto ${workspaceFolder}/.unittest.log:1
fi
