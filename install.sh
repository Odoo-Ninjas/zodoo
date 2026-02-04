#!/bin/bash

set -e

REPO_URL="https://github.com/Odoo-Ninjas/zodoo"
TARGET_DIR="$HOME/.odoo/images"
SRC_DIR="$TARGET_DIR/wodoo/src"
OS="$(uname -s)"

pipx uninstall wodoo || true  # remove any old version

echo "🔍 Checking for git..."
if ! command -v git >/dev/null 2>&1; then
    echo "❌ git is not installed. Please install Git and re-run this script."
    exit 1
fi


# Clone repo if not present
if [ ! -d "$TARGET_DIR/.git" ]; then
    echo "📥 Cloning $REPO_URL into $TARGET_DIR..."
    mkdir -p "$(dirname "$TARGET_DIR")"
    git clone "$REPO_URL" "$TARGET_DIR"
else
    echo "✅ Git repo already exists at $TARGET_DIR!"
fi

# Checkout the desired branch
cd "$TARGET_DIR"
git remote set-url origin "$REPO_URL"
git fetch
if [ "$(git rev-parse --abbrev-ref HEAD)" = "2025-05b" ]; then
  echo "Switching from 2025-05b to main..."
  git checkout main
fi

# Check for pipx
echo "🔍 Checking for pipx..."
if ! command -v pipx >/dev/null 2>&1; then
    echo "❌ pipx is not installed."
    echo "Please install it using one of the following:"
    echo "  Debian/Ubuntu: sudo apt install pipx"
    echo "  Or via pip: python3 -m pip install --user pipx && python3 -m pipx ensurepath"
    exit 1
fi

# Install the editable package using pipx
echo "📦 Installing $SRC_DIR via pipx..."
# ubuntu 20.04 has no -f flag
PYTHONARG=()
if [[ "$OS" == "Darwin" ]]; then
    PYTHONARG=(--python python3.12)
fi
pipx install -e "$SRC_DIR" -f ${PYTHONARG[@]} || \
pipx install -e "$SRC_DIR" ${PYTHONARG[@]}

# Setting up completion
odoo completion -x

echo "✅ Done."
