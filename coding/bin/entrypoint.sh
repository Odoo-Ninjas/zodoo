#!/bin/bash
set -e

USERNAME=coder
OPENVSCODE="/home/.openvscode-server/bin/openvscode-server"
TRIGGER_URL="${TRIGGER_URL:-http://coding_trigger:8090}"

# Create unprivileged user matching host UID
groupadd -f "$USERNAME"
useradd -g "$USERNAME" -m "$USERNAME" -u "${OWNER_UID:-1000}" -s /bin/bash 2>/dev/null || true

# Give user ownership of workspace and server dir
chown -R "$USERNAME:$USERNAME" /home/.openvscode-server
chown -R "$USERNAME:$USERNAME" /opt/src 2>/dev/null || true

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
chown -R "$USERNAME:$USERNAME" "$VSCODE_DIR"

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
