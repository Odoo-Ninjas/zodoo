#!/bin/bash

set -e

REPO_URL="https://github.com/Odoo-Ninjas/zodoo"
TARGET_DIR="$HOME/.odoo/images"
SRC_DIR="$TARGET_DIR/zodoo/src"

pipx uninstall zodoo || true  # remove any old version
pipx uninstall wodoo || true  # remove legacy name

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

# Force re-materialise the working tree from HEAD. Old git versions
# (e.g. git 2.25 on Ubuntu 20.04) have been observed to clone with a
# partial working tree (zodoo/src missing) — a hard reset to the index
# fixes that and is a no-op on a healthy clone.
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git reset --hard "origin/${CURRENT_BRANCH}"

# Check for pipx
echo "🔍 Checking for pipx..."
if ! command -v pipx >/dev/null 2>&1; then
    echo "❌ pipx is not installed."
    echo "Please install it using one of the following:"
    echo "  Debian/Ubuntu: sudo apt install pipx"
    echo "  Or via pip: python3 -m pip install --user pipx && python3 -m pipx ensurepath"
    exit 1
fi

# pipx 0.x (Ubuntu 20.04) and 1.0.x–1.3.x (Ubuntu 22.04) have broken
# editable installs: 0.x wipes setup.py with the venv path, and 1.0–1.3
# misclassify absolute paths as URL requirements under packaging >=22,
# silently dropping --editable. pipx 1.4+ uses urllib.urlsplit and works.
# Force-upgrade and make sure subsequent `pipx` calls hit the upgraded
# copy in ~/.local/bin (apt's pipx in /usr/bin would otherwise shadow it).
PIPX_VER="$(pipx --version 2>/dev/null)"
PIPX_MAJOR="$(echo "$PIPX_VER" | cut -d. -f1)"
PIPX_MINOR="$(echo "$PIPX_VER" | cut -d. -f2)"
if [ "${PIPX_MAJOR:-0}" -lt 1 ] || \
   { [ "${PIPX_MAJOR:-0}" -eq 1 ] && [ "${PIPX_MINOR:-0}" -lt 4 ]; }; then
    echo "⚙️  Old pipx detected ($PIPX_VER) — upgrading to current."
    python3 -m pip install --user --upgrade pipx
    export PATH="$HOME/.local/bin:$PATH"
    hash -r
    echo "    now using $(command -v pipx) ($(pipx --version))"
fi

# zodoo is pinned to one python minor version (see the python_version file).
# On current systems python3 is already 3.13/3.14, and part of our dependency
# set has no wheels there, so pipx must never silently pick the system python.
WANTED_PYTHON="$(cat "$TARGET_DIR/python_version" 2>/dev/null || cat "$TARGET_DIR/darwin_python_version")"
WANTED_PYTHON="$(echo "$WANTED_PYTHON" | tr -d '[:space:]' | cut -d. -f1,2)"
WANTED_MINOR="${WANTED_PYTHON#*.}"

find_python() {
    local ver="$1" cand
    for cand in "python${ver}" \
                "/opt/homebrew/bin/python${ver}" \
                "/usr/local/bin/python${ver}" \
                "/usr/bin/python${ver}"; do
        if command -v "$cand" >/dev/null 2>&1; then
            command -v "$cand"
            return 0
        fi
    done
    return 1
}

# pipx renamed the flag: --fetch-missing-python (1.5+) became
# --fetch-python=missing (deprecated warning since 1.15). Support both.
PIPX_INSTALL_HELP="$(pipx install --help 2>&1 || true)"
FETCH_PYTHON_ARG=""
if echo "$PIPX_INSTALL_HELP" | grep -q -- "--fetch-python"; then
    FETCH_PYTHON_ARG="--fetch-python=missing"
elif echo "$PIPX_INSTALL_HELP" | grep -q -- "--fetch-missing-python"; then
    FETCH_PYTHON_ARG="--fetch-missing-python"
fi

SYSTEM_MINOR="$(python3 -c 'import sys; print(sys.version_info[1])' 2>/dev/null || echo 0)"

PYTHONARG=()
if PINNED_PYTHON="$(find_python "$WANTED_PYTHON")"; then
    echo "🐍 Using python $WANTED_PYTHON ($PINNED_PYTHON)."
    PYTHONARG=(--python "$PINNED_PYTHON")
elif [ "$SYSTEM_MINOR" -ge 10 ] && [ "$SYSTEM_MINOR" -le "$WANTED_MINOR" ]; then
    # Older but still supported system python (e.g. 3.10 on Ubuntu 22.04).
    echo "⚠️  python${WANTED_PYTHON} not found — using $(python3 --version)."
elif [ -n "$FETCH_PYTHON_ARG" ]; then
    # No matching python on the machine and the system one is too new. This is
    # the normal case on Ubuntu 26.04, which has no python3.12 package at all:
    # let pipx download a standalone python (lands in ~/.local/pipx/py).
    echo "⚠️  python${WANTED_PYTHON} not found and the system python (3.${SYSTEM_MINOR}) is too new"
    echo "    — letting pipx download python ${WANTED_PYTHON}."
    PYTHONARG=(--python "$WANTED_PYTHON" "$FETCH_PYTHON_ARG")
else
    echo "❌ zodoo needs python ${WANTED_PYTHON}, but only python 3.${SYSTEM_MINOR} was found,"
    echo "   and this pipx ($(pipx --version)) cannot download one."
    echo "Please install python ${WANTED_PYTHON} and re-run this script:"
    echo "  macOS:         brew install python@${WANTED_PYTHON}"
    echo "  Debian/Ubuntu: sudo apt install python${WANTED_PYTHON}-venv"
    echo "                 (or add ppa:deadsnakes/ppa first)"
    echo "Alternatively upgrade pipx: python3 -m pip install --user --upgrade pipx"
    exit 1
fi

# Install the editable package using pipx
echo "📦 Installing $SRC_DIR via pipx..."
# ubuntu 20.04 has no -f flag
pipx install -e "$SRC_DIR" --force ${PYTHONARG[@]} || \
pipx install -e "$SRC_DIR" ${PYTHONARG[@]}

# gimera manages the vendored/pinned submodules of our odoo projects and is
# needed for everyday work ("gimera apply"). "odoo setup reinstall" has always
# injected it, the installer did not - so a fresh machine had no gimera.
echo "📦 Injecting gimera..."
pipx inject --force zodoo gimera

# Setting up completion
odoo completion -x

echo "✅ Done."
