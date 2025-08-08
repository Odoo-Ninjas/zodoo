#!/bin/bash

# Base directory to search
BASE_DIR="${1:-.}"  # Default to current dir if not passed as first argument

# The string to search and its replacement
SEARCH="${2}"
REPLACE="${3}"

echo "Scanning directory: $BASE_DIR"
echo "Replacing '$SEARCH' with '$REPLACE'..."

# Find all files containing the string
ag -l "$SEARCH" "$BASE_DIR" | while read -r file; do
    echo "Updating: $file"
    sed -i "s/$SEARCH/$REPLACE/g" "$file"
done

echo "✅ Replacement complete."