# Command Reference

All commands are run as `odoo <command>`. Use `odoo --help` or `odoo <command> --help` for up-to-date option lists.

## Global flags

```
odoo -f <command>       # force (skips "are you sure?" prompts)
odoo -v <command>       # verbose output
odoo -p <name>          # override project name
```

---

## Container Lifecycle

### `odoo up [-d] [machines...]`

Start containers. `-d` runs in background (daemon mode).

```bash
odoo up -d              # start all containers in background
odoo up -d odoo         # start only the odoo container
```

### `odoo down [-v] [--postgres-volume]`

Stop and remove containers. Requires `-f` on production systems.

```bash
odoo down               # stop containers, keep volumes
odoo -f down -v         # also remove all volumes (destroys database!)
```

### `odoo stop [machines...]`

Stop containers without removing them.

### `odoo restart [machines...]`

Restart containers.

### `odoo build [machines...]`

Build Docker images locally. Required after Dockerfile changes.

### `odoo kill`

Force-kill all containers.

### `odoo rm`

Remove stopped containers.

### `odoo recreate [machines...]`

Recreate containers without rebuilding images.

---

## Configuration

### `odoo reload`

Regenerate `docker-compose.yml` from current settings. **Run this after every settings change** before `odoo up`.

### `odoo setting <KEY> <VALUE>`

Set a project setting. Writes to `./.odoo/settings` and triggers reload.

```bash
odoo setting DEVMODE 1
odoo setting PROXY_PORT 18069
odoo setting ODOO_PYTHON_VERSION 3.12
odoo setting HUB_URL registry.example.com:443/myproject
```

Flags:

- `-u` / `--user-wide`: write to `~/.odoo/settings`
- `-s` / `--system-wide`: write to `/etc/odoo/settings`
- `--no-reload`: skip auto-reload after setting

### `odoo setup next-port`

Find and assign the next free port for `PROXY_PORT`, `DEBUG_PORT`, and (on macOS) `HOST_DB_PORT`.

### `odoo setup status`

Show project name, Odoo version, database connection URL, and key config values.

### `odoo setup remove-web-assets`

Fix broken CSS/JS. Clears web assets from database; they are regenerated on next admin login.

### `odoo upgrade`

Upgrade zodoo to the latest version (pulls `~/.odoo/images` and reinstalls `zodoo`).

---

## Database

### `odoo -f db reset`

Drop and reinitialize the database. **Destructive** — requires `-f`.

### `odoo db pgactivity`

Show live PostgreSQL activity (like `htop` for the DB).

### `odoo db pgcli [--dbname <name>]`

Enhanced interactive PostgreSQL CLI with autocomplete.

### `odoo db psql [--sql <query>]`

Standard `psql` CLI. Can run SQL non-interactively:

```bash
odoo db psql --sql "SELECT COUNT(*) FROM res_partner;"
```

### `odoo db drop-db`

Drop the current database.

### `odoo db anonymize`

Anonymize sensitive data (emails, phone numbers, etc.) in the database.

### `odoo db show-table-sizes [--top N]`

Show the largest tables in the database.

### `odoo db dbcompare <file1> <file2>`

Compare two database dumps.

---

## Backup & Restore

### `odoo backup odoo-db [path]`

Backup the database. Uses a default filename if no path is given.

```bash
odoo backup odoo-db                      # default name
odoo backup odoo-db /backups/mydb.zip    # custom path
```

### `odoo backup files`

Backup the Odoo filestore.

### `odoo backup all [filename]`

Backup database + filestore in one archive.

### `odoo restore odoo-db [path]`

Restore the database. Shows an interactive file picker if no path is given.

```bash
odoo restore odoo-db                     # interactive picker
odoo -f restore odoo-db /backups/mydb.zip
```

### `odoo restore files`

Restore the Odoo filestore.

### `odoo restore list`

List available backup files.

---

## Module Management

### `odoo update [module...]`

Update installed modules. Without arguments, updates all modules listed in MANIFEST `install`.

```bash
odoo update               # update all
odoo update sale account  # update specific modules
```

### `odoo module uninstall <module...>`

Uninstall modules.

### `odoo module show-install-state`

Show which modules from MANIFEST are installed/uninstalled.

### `odoo module update-i18n`

Update translations for installed modules.

---

## Debugging

### `odoo debug odoo_debug [--port <port>]`

Start a debug container. Inside the container prompt, type `debug` and press ENTER.

Then:

- Navigate to `https://<host>/debugpython` → activates debug mode for your browser session (sets cookie)
- Your Python requests go to the debug container; websocket and other requests go to the normal container
- Reset with `https://<host>/debugpython_off`

See [Debug Mode Guide](./05-debug-mode.md) for full details.

### `odoo odoo-shell`

Open an interactive Odoo Python shell inside the running container.

```python
# Example usage inside shell:
env['res.partner'].search([]).mapped('name')
```

---

## Docker Registry

### `odoo docker-registry login`

Authenticate with the configured Docker registry (`HUB_URL`).

### `odoo build`

Build all images (required before `regpush`).

### `odoo regpush`

Push all images (including base images like postgres, redis) to the registry.
Images are tagged with a SHA-based name.

### `odoo regpull`

Pull all images from the registry. Requires `REGISTRY=1` and `HUB_URL` to be configured.

See [Using the Registry](./06-registry.md) for full details.

---

## Source / Project Management

### `odoo src init <path> [version]`

Initialize a new Odoo project at `<path>` (also available as `odoo init`).

### `odoo src find-duplicate-modules`

Find modules with duplicate names across addon paths.

### `odoo src apply-gimera-if-required`

Apply pending gimera updates if needed.

---

## Robot Framework

### `odoo robot:run`

Run Robot Framework tests.

### `odoo robot:make-var-file`

Generate a variables file for Robot Framework tests.

In test files, use comments to declare module requirements:

```
#odoo-require: crm,sale_stock
#odoo-uninstall: partner_autocomplete
```

---

## Snapshots (btrfs/zfs only)

Fast database snapshots using filesystem-level copy-on-write:

```bash
odoo snapshots create <name>   # create snapshot
odoo snapshots restore <name>  # restore snapshot
odoo snapshots list            # list snapshots
odoo snapshots delete <name>   # delete snapshot
```

Requires btrfs or zfs filesystem for the postgres data volume.
