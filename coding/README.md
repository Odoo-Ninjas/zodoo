# Coding Container

Web-based VS Code (OpenVSCode Server) for Odoo development, accessible at `/code/`.

## Enable

Set `RUN_CODING=1` in your project settings, then:

```bash
odoo reload
odoo build coding coding_trigger --no-zodoo-pull
odoo restart coding coding_trigger
```

## Access

`/code/` is guarded by the same password gate as `/system` (see
`proxy/lua/dashauth.lua`): one password, no user name, a signed cookie
afterwards. The password is `CODING_PASSWORD`; it is generated on the first
`odoo reload` of a real instance and left empty in DEVMODE, where the gate
stays open. Read it with `odoo setting CODING_PASSWORD`.

This matters because the editor has a terminal on the machine. An instance
that can be reached from the internet must not serve it to everyone who knows
the host name.

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
| `/restart` | POST   | Put odoo back to normal (also ends a debug session) |
| `/debug`   | POST   | Start odoo in debug mode    |
| `/up`      | POST   | `docker compose up -d odoo` |
| `/logs`    | POST   | Last 100 lines of odoo logs |
| `/health`  | GET    | Health check                |
| `/actions` | GET    | List available actions      |

## Debugging

1. In `/code/`, open the Run & Debug panel
2. Select "Attach Odoo (debugpy)"
3. Press F5 -- this triggers `/debug` on the sidecar, which restarts odoo with debugpy on
   port 5678. Note that this **stops the running odoo** for a moment and leaves it waiting
   for the debugger: on a production instance the site is down until you detach and restart.
4. Set breakpoints in your code
5. When you are done, run the task `restart:odoo` (or POST `/restart`). This recreates the
   odoo container from the plain compose file and is what ends the debug session -- a plain
   `docker compose restart` would leave odoo waiting for a debugger forever.

## Security

- The coding container has **zero Docker access**
- The trigger sidecar only executes predefined commands (restart, debug, up, logs)
- No volume mounting, image building, or container creation possible from the browser
- OpenVSCode Server runs as unprivileged user, not root
