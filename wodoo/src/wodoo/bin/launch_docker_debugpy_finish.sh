#!/bin/bash

current_dir=$(dirname "$0")
CURRENT_FILE="${CURRENT_FILE#$(pwd)/}"

if [[ "$CURRENT_FILE" == */tests/* ]]; then
    code --reuse-window --goto .unittest.log:1
fi
