#!/bin/bash
set -e

USERNAME=coder
OWNER_UID="${OWNER_UID:-1000}"
OPENVSCODE="/home/.openvscode-server/bin/openvscode-server"
TRIGGER_URL="${TRIGGER_URL:-http://coding_trigger:8090}"

# We need to run as a user whose UID is the host owner's, so that files
# written in the workspace belong to them. The base image
# (gitpod/openvscode-server) already ships `openvscode-server` with UID 1000
# - and 1000 is the usual OWNER_UID, being the first user on the host. In
# that case `useradd -u` refuses the duplicate UID, so insisting on our own
# name leaves no `coder` at all: every following `chown coder:coder` then
# fails with "invalid user" and the container dies under `set -e`.
# So take over whoever already holds the UID, and only create `coder` when
# the UID is free.
existing_user="$(getent passwd "$OWNER_UID" | cut -d: -f1)"
if [ -n "$existing_user" ]; then
    USERNAME="$existing_user"
else
    groupadd -f "$USERNAME"
    useradd -g "$USERNAME" -m "$USERNAME" -u "$OWNER_UID" -s /bin/bash
fi
USERGROUP="$(id -gn "$USERNAME")"

# Give user ownership of workspace and server dir
chown -R "$USERNAME:$USERGROUP" /home/.openvscode-server
chown -R "$USERNAME:$USERGROUP" /opt/src 2>/dev/null || true

# Create .vscode config for debugging via trigger sidecar
VSCODE_DIR="/opt/src/.vscode"
mkdir -p "$VSCODE_DIR"

cat > "$VSCODE_DIR/tasks.json" <<TASKS
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "launch:odoo:debugpy",
      "type": "shell",
      "command": "curl -sf -X POST ${TRIGGER_URL}/debug",
      "options": { "cwd": "\${workspaceFolder}" },
      "presentation": { "reveal": "never", "panel": "shared", "close": true },
      "problemMatcher": []
    },
    {
      "label": "restart:odoo",
      "type": "shell",
      "command": "curl -sf -X POST ${TRIGGER_URL}/restart",
      "options": { "cwd": "\${workspaceFolder}" },
      "presentation": { "reveal": "never", "panel": "shared", "close": true },
      "problemMatcher": []
    },
    {
      "label": "logs:odoo",
      "type": "shell",
      "command": "curl -sf -X POST ${TRIGGER_URL}/logs | jq -r .stdout",
      "options": { "cwd": "\${workspaceFolder}" },
      "presentation": { "reveal": "always", "panel": "shared", "close": true },
      "problemMatcher": []
    },
    {
      "label": "robot:run",
      "type": "shell",
      "command": "curl -sf -X POST -H 'Content-Type: application/json' -d '{\"test_file\": \"\${relativeFile}\"}' ${TRIGGER_URL}/robot | jq .",
      "options": { "cwd": "\${workspaceFolder}" },
      "presentation": { "reveal": "always", "panel": "shared" },
      "problemMatcher": []
    }
  ]
}
TASKS

cat > "$VSCODE_DIR/launch.json" <<'LAUNCH'
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Attach Odoo (debugpy)",
      "type": "debugpy",
      "request": "attach",
      "connect": {
        "host": "odoo",
        "port": 5678
      },
      "preLaunchTask": "launch:odoo:debugpy",
      "pathMappings": [
        {
          "localRoot": "${workspaceFolder}",
          "remoteRoot": "/opt/src"
        }
      ],
      "justMyCode": false
    }
  ]
}
LAUNCH
# Ensure settings.json exists and has robotcode.python configured
if [[ ! -f "$VSCODE_DIR/settings.json" ]]; then
    cat > "$VSCODE_DIR/settings.json" <<'SETTINGS'
{
  "vim.enable": false,
  "robotcode.python": "/opt/robotenv/bin/python"
}
SETTINGS
else
    # Add robotcode.python if not already present
    if ! grep -q "robotcode.python" "$VSCODE_DIR/settings.json"; then
        sed -i 's/^{$/{\n  "robotcode.python": "\/opt\/robotenv\/bin\/python",/' "$VSCODE_DIR/settings.json"
    fi
fi
chown -R "$USERNAME:$USERGROUP" "$VSCODE_DIR"

# Start vim toggle server in background as unprivileged user
NODE="/home/.openvscode-server/node"
gosu "$USERNAME" "$NODE" /usr/local/bin/vim-toggle.js &

# Install VSIX extensions as user
if [[ -x "$OPENVSCODE" ]]; then
    for vsix in /opt/vsix/*.vsix; do
        [[ -f "$vsix" ]] || continue
        echo "Installing extension: $vsix"
        gosu "$USERNAME" "$OPENVSCODE" --install-extension "$vsix" || true
    done

    exec gosu "$USERNAME" "$OPENVSCODE" \
        --host 0.0.0.0 \
        --port 8080 \
        --server-base-path /code \
        --without-connection-token \
        --default-folder /opt/src
else
    # Fallback to code-server
    for vsix in /opt/vsix/*.vsix; do
        [[ -f "$vsix" ]] || continue
        echo "Installing extension: $vsix"
        gosu "$USERNAME" code-server --install-extension "$vsix" || true
    done

    exec gosu "$USERNAME" code-server \
        --bind-addr 0.0.0.0:8080 \
        --auth none \
        --disable-telemetry \
        /opt/src
fi
