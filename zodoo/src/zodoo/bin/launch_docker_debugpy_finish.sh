#!/bin/bash

current_dir=$(dirname "$0")
CURRENT_FILE="${CURRENT_FILE#$(pwd)/}"

if [[ "$CURRENT_FILE" == */tests/* ]]; then
    if [[ -s .unittest.log ]]; then
        code --reuse-window --goto .unittest.log:1
    fi
fi
