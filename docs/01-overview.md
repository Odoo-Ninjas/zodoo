# zodoo – Overview

zodoo (formerly wodoo) is an **Odoo Docker Framework** that wraps Docker Compose and the Odoo server into a simple, settings-driven CLI tool called `odoo`.

Source: https://github.com/Odoo-Ninjas/zodoo

## What zodoo does

- Manages the full Odoo Docker stack (web, cron, queuejobs, postgres, proxy, mail, redis, vscode, ...)
- Provides a single CLI (`odoo`) for all lifecycle operations
- Generates `docker-compose.yml` dynamically from a settings file
- Handles backup/restore, module updates, registry push/pull, debugging
- Encrypted offsite backup with restic, append-only against our backup
  server (see [11-offsite-backup.md](./11-offsite-backup.md))

## Architecture

```
zodoo repo (~/.odoo/images/)
├── odoo/           ← Odoo Docker image + docker-compose templates
├── postgres/       ← PostgreSQL image
├── proxy/          ← Node.js proxy (buffering, /longpolling routing)
├── mail/           ← Fake webmail (catch-all for dev)
├── redis/          ← Redis
├── vscode/         ← VS Code Server in container
├── browser/        ← Chromium/Firefox for automated tests
├── webssh/         ← Web-based SSH terminal
├── console/        ← Admin console
├── cronjobs/       ← Cron container
├── logsio_web/     ← logs.io web interface
├── templates/      ← Project templates (copied on `odoo init`)
└── zodoo/          ← Python CLI source (the `odoo` command)
```

### Two components

| Component | What it is                              | Where                                  |
| --------- | --------------------------------------- | -------------------------------------- |
| **zodoo** | Docker images + templates               | `~/.odoo/images/` (cloned from GitHub) |
| **zodoo** | Python CLI providing the `odoo` command | installed via `pipx`                   |

### Settings resolution order

Settings are merged from multiple locations (later overrides earlier):

1. `~/.odoo/images/odoo/default.settings` — zodoo defaults
2. `/etc/odoo/settings` — system-wide
3. `~/.odoo/settings` — user-wide
4. `./.odoo/settings` — project-specific (checked into your repo)
5. Environment variables

## Containers (Services)

| Container        | Purpose                                  | Always on?         |
| ---------------- | ---------------------------------------- | ------------------ |
| `odoo`           | Main Odoo web server                     | yes                |
| `odoo_cronjobs`  | Cron job runner                          | configurable       |
| `odoo_queuejobs` | Queue job runner                         | configurable       |
| `postgres`       | PostgreSQL database                      | yes                |
| `proxy`          | Node.js reverse proxy, request buffering | configurable       |
| `mail`           | Catch-all SMTP (MailHog)                 | dev only           |
| `redis`          | Redis for sessions/cache                 | if modules need it |

Toggle containers via settings:

```
RUN_ODOO_CRONJOBS=1
RUN_PROXY=1
```

The queuejobs role is spawned automatically iff the `queue_job` module
is installed in the project database — no manual toggle is needed.

That gate is re-checked whenever the role would be (re)started: the
supervisor refuses a `start`/`restart` for a role whose gate is off, and it
does not respawn such a role after it exits. So on a project without
`queue_job`, an `odoo up` / `odoo restart odoo_queuejobs` leaves the role
stopped instead of arming a respawn loop — the child would only exit again
("Queue-Jobs shall not run"), and each attempt costs a full config render.
`odoo kill odoo_queuejobs` stops a running role; the user's stop intent also
wins over the watchdog.
