# Coding Container

Web-based VS Code (OpenVSCode Server) for Odoo development, accessible at `/code1/`.

## Enable

Set `RUN_CODING=1` in your project settings, then:

```bash
odoo reload
odoo build coding coding_trigger --no-zodoo-pull
odoo restart coding coding_trigger
```

## Architecture

```
Browser --> /code1/ --> [coding] openvscode-server (unprivileged user)
                            |
                            | curl http://coding_trigger:8090/restart
                            v
                        [coding_trigger] Python HTTP sidecar
                            |
                            | docker compose -p <project> restart odoo
                            v
                        /var/run/docker.sock
```

### coding

- OpenVSCode Server running as unprivileged `coder` user (UID matches `OWNER_UID`)
- Source code mounted at `/opt/src`
- **No Docker access** -- all container operations go through the trigger sidecar
- Pre-installed extensions: Zebroo (latest from GitHub), Python (ms-python)
- Auto-generated `.vscode/launch.json` and `tasks.json` for debugging

### coding_trigger

- Minimal Python HTTP server with Docker CLI
- Only container with Docker socket access
- Exposes predefined actions only:

| Endpoint   | Method | Action                      |
| ---------- | ------ | --------------------------- |
| `/restart` | POST   | Restart the odoo container  |
| `/debug`   | POST   | Start odoo in debug mode    |
| `/up`      | POST   | `docker compose up -d odoo` |
| `/logs`    | POST   | Last 100 lines of odoo logs |
| `/health`  | GET    | Health check                |
| `/actions` | GET    | List available actions      |

## Debugging

1. In `/code1/`, open the Run & Debug panel
2. Select "Attach Odoo (debugpy)"
3. Press F5 -- this triggers `/debug` on the sidecar, which starts odoo with debugpy on port 5678
4. Set breakpoints in your code

## Security

- The coding container has **zero Docker access**
- The trigger sidecar only executes predefined commands (restart, debug, up, logs)
- No volume mounting, image building, or container creation possible from the browser
- OpenVSCode Server runs as unprivileged user, not root
