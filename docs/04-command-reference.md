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

### `odoo dev [-b/--build] [-k/--kill]`

Start containers in dev mode: combines build + up + watch, so code changes
are picked up live. `-b` forces a rebuild first, `-k` kills existing
containers before starting.

---

## Configuration

### `odoo reload`

Regenerate `docker-compose.yml` from current settings. **Run this after every settings change** before `odoo up`.

Also writes `.vscode/launch.json` and `.vscode/tasks.json` for the project and
installs/updates the Zebroo VS Code extension (if the `code` CLI is
available) — no separate setup command is needed for VS Code integration.

### `odoo setting <KEY> <VALUE>`

Set a project setting. Writes to `./.odoo/settings` and triggers reload.

```bash
odoo setting DEVMODE=1
odoo setting PROXY_PORT=18069
odoo setting ODOO_PYTHON_VERSION=3.12
odoo setting HUB_URL=registry.example.com:443/myproject
```

Flags:

- `-u` / `--user-wide`: write to `~/.odoo/settings`
- `-s` / `--system-wide`: write to `/etc/odoo/settings`
- `--no-reload`: skip auto-reload after setting

### `odoo setup next-port`

Find and assign the next free port for `PROXY_PORT`, `DEBUG_PORT`, and (on macOS) `HOST_DB_PORT`.

### `odoo status`

Show project name, Odoo version, database connection URL, and key config
values. (Also reachable as `odoo setup status`; `odoo status` is the direct,
unambiguous form.)

### `odoo setup remove-web-assets`

Fix broken CSS/JS. Clears web assets from database; they are regenerated on next admin login.

### `odoo setup setup-pyenv`

Set up a local `pyenv`-managed Python environment for the robot/test tooling,
so tests show up correctly in VS Code.

### `odoo config [-f/--full]`

Print the effective configuration for the current project. `--full` shows
the full environment instead of the shortened default.

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

### `odoo restore-web-icons`

Repairs broken `ir.attachment` links after a database restore, by deleting
and recreating the affected web-icon attachments. (Also reachable as
`odoo talk restore-web-icons`.)

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

## Shared Filestore

On hosts carrying several instances of the same dump, `ODOO_FILES_COMMON=1`
keeps one pool of attachment files in `<filestore>/_common`. Content is shared
via **hardlinks**; sharing the directory via a symlink instead destroys
attachments, because Odoo's garbage collection bookkeeping (`checklist`) must
stay private per database. See [17-filestore.md](./17-filestore.md) for the
concept, the failure mode and how to repair a damaged instance.

### `odoo filestore sync [--pull] [--no-heal] [--no-dedup] [--wait] [--dry-run]`

The everyday command, for the current project: optionally mirror missing files
from `FILESTORE_UPSTREAM` into the pool (`--pull`), then link back what the
database references but the instance is missing, then dedup into the pool.

Strictly additive and idempotent — it never moves, replaces or rebuilds a
directory an instance is serving from, so nobody sees a missing filestore. An
`flock` keeps two runs from overlapping; the lock is held by the file
descriptor, so a killed run cannot leave a blocking lock behind. Interactively
the lock does not wait - it says so and stops. `--wait` queues instead, which
is what the instance cronjob (`CRONJOB_FILESTORE_HEAL`) uses: all instances of
a host share one pool, so skipping would mean most of them never run.

`--pull` is off by default on purpose: it talks to another machine, and on a
dev host carrying instances of many different production systems you rarely
want that unattended. `FILESTORE_UPSTREAM` is therefore a per-project setting
(`FILESTORE_UPSTREAM_BWLIMIT` throttles the transfer).

### `odoo filestore install-cron [--at HH:MM] [--remove]`

Install a nightly `filestore dedup` in the user's crontab, `ionice`d. The pool
belongs to the filestore root rather than to a project, so one entry per root
is enough. Healing is _not_ part of it — that needs each instance's database
and therefore belongs to the instance or to the CI system after a restore.

### `odoo filestore dedup`

Hardlink per-database filestores into the shared `_common` pool. Skips
directories that are still symlinks and asks you to run `unshare` first.

### `odoo filestore unshare [-a/--all]`

Replace legacy `<db> -> _common` symlinks by real directories of hardlinks, so
each database gets its own GC checklist again. Uses no additional disk space.
Database-driven: only files referenced by `ir_attachment` are materialised; an
unreachable database is left untouched rather than emptied.

`--all` covers every symlinked database served by _this_ project's postgres.
Where each instance runs its own postgres container, run it once per project.

---

## Encrypted Offsite Backup

Pushes the pgBackRest repository and this database's filestore to a remote repository
using [restic](https://restic.net). The usual target is our own backup server
(`restic-backup`), which runs `rest-server` in **append-only** mode: this
machine may write but cannot delete anything, so a compromised Odoo host cannot
destroy the history. A Hetzner Storage Box (`sftp:`) or a mounted filesystem
work too.

Encryption happens **on this machine** before anything leaves it: the storage
provider only ever sees ciphertext and cannot read or silently alter the backup.

For our backup server, do not wire this up by hand — run `odoo offsite
register` (see below). Otherwise set `RUN_OFFSITE=1` plus `OFFSITE_REPO` and
`OFFSITE_PASSPHRASE`, then `odoo reload && odoo build offsite`. See
`offsite/default.settings` for the retention, compression and bandwidth knobs.

> **Keep the passphrase somewhere other than this machine.** Without it the
> backup cannot be opened — and it is needed precisely when the machine is
> gone.

A run **aborts loudly** when no database state would end up in the snapshot —
neither via pgBackRest nor via a dump. A snapshot of attachments alone looks like a
backup until someone needs to restore. `OFFSITE_ALLOW_WITHOUT_DB=1` switches
that check off, and should only be used when the database is provably backed up
elsewhere.

### `odoo offsite register`

Request a customer area on the backup server. The first call files the request;
an admin approves it in the server's admin page, and the same call then picks up
credentials plus the server certificate and writes them into the settings. The
repo key is shown to the admin **once** — it goes into 1Password there, and the
backup server does not keep it.

### `odoo offsite backup`

Run a backup now. The same command runs nightly via `OFFSITE_BACKUP_CRON`
(default 04:00, after the pgBackRest backup) and is a quiet no-op on projects
without `RUN_OFFSITE=1`.

It runs **whichever streams are configured** — filestore, database, or both.
With `RUN_OFFSITE=1` but no target at all it fails loudly instead of returning
success; so does a filestore-only target when the database is covered by
neither pgBackRest nor `OFFSITE_WO_DB_RECIPIENT`.

### `odoo offsite list` / `odoo offsite info`

List the archives in the repository / show repository stats (size,
deduplication).

### `odoo offsite check`

Verify integrity by re-reading the data. Takes time and costs traffic.

### `odoo offsite prune`

Apply the retention rules now (`OFFSITE_KEEP_DAILY` / `_WEEKLY` / `_MONTHLY`).
Against an append-only target this is refused with an explanation: retention has
to run on the backup server, and it must actually run there — otherwise the
repository grows without bound.

### `odoo offsite restic <args...>`

Escape hatch: run an arbitrary `restic` command against the repository, e.g.
`odoo offsite restic snapshots --compact`.

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

### `odoo shell`

Open an interactive Odoo Python shell inside the running container.

> Written as `odoo-shell` here until 06.09.2026. That is the name the
> command carries in zodoo's internal registry
> (`Commands.register(shell, "odoo-shell")`), not the one the CLI answers
> to — typing `odoo odoo-shell` gets you a usage error.

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

See [Robot Tests](./16-robot-tests.md) for the full workflow.

### `odoo robot setup`

Wire Robot Framework into the project: adds `odoo-robot_utils` to `gimera.yml`,
`robot_utils` to the MANIFEST `install` list and `addons_robot` to
`addons_paths`, creates the `~/.robotenv` virtualenv, and runs `gimera apply`.
Idempotent.

### `odoo robot new <name>`

Create `tests/<name>.robot` from the template. `-I` / `--no-install-pip` skips
the `setup` step.

### `odoo robot run [file]`

Run Robot Framework tests. Requires devmode. Notable options: `--all`,
`--user`, `--tags`, `--parallel`, `--repeat`, `--test-tv` (watch the browser at
`/test.tv/`) and `--debug`.

### `odoo robot list`

List the available robot tests.

### `odoo robot run-all`

Run every robot matching the `robotests` file patterns.

### `odoo robot make-variable-file`

Generate the `.robot-vars` variables file.

### `odoo robot cleanup`

Clean up after test runs.

### `odoo robot start-cobot`

Start cobot, reachable at `http://<host>/cobot`.

In test files, use comments to declare module requirements:

```
#odoo-require: crm,sale_stock
#odoo-uninstall: partner_autocomplete
```

---

## Performance

### `odoo benchmark fields <model>`

Benchmark every field of a model to find slow computed fields under real
database conditions.

### `odoo benchmark curl`

Same idea, scoped to the fields a specific slow request actually asked for —
paste a `web_search_read` cURL command copied from Chrome DevTools.

See [Benchmarking](./14-benchmarking.md) for full option lists and a worked
example.

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

On zfs the dataset is created with `xattr=sa acltype=posixacl`. The linux
default `xattr=on` stores every extended attribute as a hidden directory with
one file per attribute, which costs additional IOs on every access. If you
prepare the dataset yourself, set those two properties as well - they only
apply to newly written attributes, existing files keep the old layout.
