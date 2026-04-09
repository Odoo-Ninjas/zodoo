#!/bin/bash
set -e

USERNAME=coder
OPENVSCODE="/home/.openvscode-server/bin/openvscode-server"

# Create unprivileged user matching host UID
groupadd -f "$USERNAME"
useradd -g "$USERNAME" -m "$USERNAME" -u "${OWNER_UID:-1000}" -s /bin/bash 2>/dev/null || true

# Give user ownership of workspace and server dir
chown -R "$USERNAME:$USERNAME" /home/.openvscode-server
chown -R "$USERNAME:$USERNAME" /opt/src 2>/dev/null || true

# Create launch.json for Python remote debugging against odoo container
VSCODE_DIR="/opt/src/.vscode"
mkdir -p "$VSCODE_DIR"
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
chown -R "$USERNAME:$USERNAME" "$VSCODE_DIR"

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
        --server-base-path /code1 \
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
