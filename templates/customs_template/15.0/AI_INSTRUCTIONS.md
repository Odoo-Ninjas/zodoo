# zodoo – Odoo Docker Framework

This project uses **zodoo** (formerly zodoo) to manage the Odoo environment.
The CLI command is `odoo` (provided by the `zodoo` Python package, installed via pipx).

> **Important for AI assistants:** The `odoo` command here is the _zodoo CLI_, not the Odoo framework itself.
> Never run `./odoo-bin` or similar. Always use the `odoo <command>` CLI described below.

## Quick Start (new project)

```bash
odoo init <folder>          # Create new project (interactive version selection)
cd <folder>
odoo reload                 # Generate docker-compose from settings
odoo setup next-port        # Pick a free port
odoo -f db reset            # Initialize database
odoo up -d                  # Start all containers in background
```

Open browser at `http://localhost:<PROXY_PORT>` — default credentials: `admin` / `admin`.

## Core Workflow

Settings-based configuration — **edit settings first, then reload**:

```bash
odoo setting <KEY> <VALUE>  # Change a setting (auto-reloads by default)
odoo reload                 # Regenerate docker-compose from current settings
odoo up -d                  # (Re)start containers
```

## All Commands

### Container lifecycle

| Command                      | Description                         |
| ---------------------------- | ----------------------------------- |
| `odoo up -d`                 | Start all containers in background  |
| `odoo up`                    | Start containers in foreground      |
| `odoo down`                  | Stop and remove containers          |
| `odoo stop`                  | Stop containers (keep state)        |
| `odoo restart`               | Restart containers                  |
| `odoo build`                 | Build Docker images locally         |
| `odoo kill`                  | Force-kill containers               |
| `odoo rm`                    | Remove stopped containers           |
| `odoo recreate`              | Recreate containers without rebuild |
| `odoo ps` (via docker group) | Show running containers             |

### Configuration

| Command                         | Description                                                               |
| ------------------------------- | ------------------------------------------------------------------------- |
| `odoo reload`                   | Regenerate docker-compose from settings. Run after every settings change. |
| `odoo setting <KEY> <VALUE>`    | Set a project setting (writes to `./.odoo/settings`, triggers reload)     |
| `odoo setting -u <KEY> <VALUE>` | Set user-wide setting (`~/.odoo/settings`)                                |
| `odoo setting -s <KEY> <VALUE>` | Set system-wide setting (`/etc/odoo/settings`)                            |
| `odoo setup next-port`          | Find and assign the next free port                                        |
| `odoo setup status`             | Show current project configuration                                        |

### Database

| Command                    | Description                                                   |
| -------------------------- | ------------------------------------------------------------- |
| `odoo -f db reset`         | Drop and reinitialize the database (requires `-f` force flag) |
| `odoo db pgactivity`       | Show live database activity                                   |
| `odoo db pgcli`            | Enhanced interactive postgres CLI                             |
| `odoo db psql`             | Standard psql CLI                                             |
| `odoo db drop-db`          | Drop the current database                                     |
| `odoo db anonymize`        | Anonymize sensitive data                                      |
| `odoo db cleardb`          | Clear database content                                        |
| `odoo db show-table-sizes` | Show table sizes                                              |

### Backup & Restore

| Command                       | Description                                                 |
| ----------------------------- | ----------------------------------------------------------- |
| `odoo backup odoo-db [path]`  | Backup database (uses default filename if no path given)    |
| `odoo backup files`           | Backup filestore                                            |
| `odoo backup all`             | Backup database + filestore                                 |
| `odoo restore odoo-db [path]` | Restore database (interactive file picker if no path given) |
| `odoo restore files`          | Restore filestore                                           |
| `odoo restore list`           | List available backups                                      |

### Module management

| Command                          | Description                      |
| -------------------------------- | -------------------------------- |
| `odoo update`                    | Update all installed modules     |
| `odoo update <module>`           | Update specific module           |
| `odoo module uninstall <module>` | Uninstall a module               |
| `odoo module show-install-state` | Show which modules are installed |
| `odoo module update-i18n`        | Update translations              |

### Debugging

| Command                 | Description                                              |
| ----------------------- | -------------------------------------------------------- |
| `odoo debug odoo_debug` | Start debug container (then type `debug` + ENTER inside) |
| `odoo odoo-shell`       | Open Odoo Python shell inside container                  |

After `odoo debug odoo_debug`:

- Navigate to `https://<host>/debugpython` to activate debugging (sets cookie)
- Reset with `https://<host>/debugpython_off`

### Registry (Docker image registry)

| Command                      | Description                   |
| ---------------------------- | ----------------------------- |
| `odoo docker-registry login` | Login to Docker registry      |
| `odoo build`                 | Build images before pushing   |
| `odoo regpush`               | Push all images to registry   |
| `odoo regpull`               | Pull all images from registry |

Registry setup:

```bash
odoo setting HUB_URL registry.zebroo.de:443/myprojectname
odoo setting DOCKER_IMAGE_TAG latest
odoo docker-registry login
```

### Setup & Maintenance

| Command                        | Description                                                      |
| ------------------------------ | ---------------------------------------------------------------- |
| `odoo upgrade`                 | Upgrade zodoo to latest version                                  |
| `odoo setup remove-web-assets` | Fix broken CSS/JS (clears web assets, regenerated on next login) |

## Key Settings (in `./.odoo/settings` or `~/.odoo/settings`)

| Setting                   | Example                              | Description                                         |
| ------------------------- | ------------------------------------ | --------------------------------------------------- |
| `DEVMODE`                 | `1`                                  | Disables cronjobs/mail on restore, resets passwords |
| `ODOO_DEMO`               | `1`                                  | Load demo data                                      |
| `PROXY_PORT`              | `18069`                              | Port to access Odoo in browser                      |
| `PROJECT_NAME`            | `myproject`                          | Used in container names and volumes (keep short)    |
| `DBNAME`                  | `mydb`                               | Database name (defaults to PROJECT_NAME)            |
| `HUB_URL`                 | `registry.example.com:443/myproject` | Docker registry URL                                 |
| `REGISTRY`                | `1`                                  | Force pull-only from registry (production)          |
| `DOCKER_IMAGE_TAG`        | `latest`                             | Image tag for registry push/pull                    |
| `ODOO_PYTHON_VERSION`     | `3.12`                               | Python version for Odoo container                   |
| `POSTGRES_VERSION`        | `14`                                 | PostgreSQL version                                  |
| `ODOO_WORKERS_WEB`        | `4`                                  | Number of Odoo web workers                          |
| `RESTART_CONTAINERS`      | `1`                                  | Auto-restart containers on failure                  |
| `RUN_ODOO_CRONJOBS`       | `1`                                  | Run cronjobs container                              |
| `RUN_ODOO_QUEUEJOBS`      | `1`                                  | Run queuejobs container                             |
| `ODOO_QUEUEJOBS_CHANNELS` | `root:4,magento2:1`                  | Queuejob channel config                             |

## MANIFEST File

Located at project root. Controls which modules are installed:

```python
{
    "version": 17.0,
    "server-wide-modules": ["web"],
    "install": ["sale", "purchase", "account"],
    "uninstall": ["web_tree_many2one_clickable"],
    "devmode_uninstall": ["password_security"],
    "addons_paths": [
        "odoo/odoo/addons",
        "odoo/addons",
        "addons_tools",
    ]
}
```

## Common Troubleshooting

**Broken CSS/JS after update:**

```bash
odoo setup remove-web-assets
```

**Previous zodoo installation (cleanup):**

```bash
rm -Rf ~/.odoo/images
# then reinstall zodoo
```

**rsync errors on macOS:**

```bash
brew install rsync
```

**Set specific Python version:**

```bash
odoo setting ODOO_PYTHON_VERSION 3.12
odoo reload && odoo build
```

**Port conflict:**

```bash
odoo setup next-port
odoo reload
```
