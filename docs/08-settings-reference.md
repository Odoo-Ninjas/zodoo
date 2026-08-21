# Settings Reference

Settings are stored in plain `KEY=VALUE` text files. They are merged in this order (later overrides earlier):

1. `~/.odoo/images/odoo/default.settings` (zodoo defaults, don't edit)
2. `/etc/odoo/settings` (system-wide)
3. `~/.odoo/settings` (user-wide)
4. `./.odoo/settings` (project-specific, committed to your repo)

Set settings via CLI:

```bash
odoo setting <KEY> <VALUE>          # project-level (./.odoo/settings)
odoo setting -u <KEY> <VALUE>       # user-level (~/.odoo/settings)
odoo setting -s <KEY> <VALUE>       # system-level (/etc/odoo/settings)
```

Or edit the files directly. Run `odoo reload` after manual edits.

---

## Project Settings

| Setting           | Default            | Description                                                                                                   |
| ----------------- | ------------------ | ------------------------------------------------------------------------------------------------------------- |
| `PROJECT_NAME`    | —                  | Container name prefix and postgres volume name. **Keep short** (max ~20 chars).                               |
| `DBNAME`          | PROJECT_NAME       | PostgreSQL database name.                                                                                     |
| `PROXY_PORT`      | —                  | HTTP port to access Odoo in browser. Set with `odoo setup next-port`.                                         |
| `DEBUG_PORT`      | —                  | Port for Python debugger. Set with `odoo setup next-port`.                                                    |
| `EXTERNAL_DOMAIN` | `http://localhost` | Public URL of the system. Comma-separated list of URLs is allowed; `odoo status` prints each on its own line. |

## Developer Settings

| Setting                  | Default | Description                                                                             |
| ------------------------ | ------- | --------------------------------------------------------------------------------------- |
| `DEVMODE`                | `0`     | `1` = on restore: disable cronjobs/mail, reset all passwords to `DEFAULT_DEV_PASSWORD`. |
| `DEFAULT_DEV_PASSWORD`   | `admin` | Password set for all users when `DEVMODE=1` and a DB is restored.                       |
| `ODOO_DEMO`              | `0`     | `1` = load demo data on `db reset`.                                                     |
| `ODOO_ENABLE_DB_MANAGER` | `0`     | `1` = enable Odoo's built-in database manager at `/web/database/manager`.               |

## Odoo Server

| Setting                  | Default | Description                                                      |
| ------------------------ | ------- | ---------------------------------------------------------------- |
| `ODOO_LOG_LEVEL`         | `debug` | Odoo log level: `debug`, `info`, `warning`, `error`, `critical`. |
| `ODOO_DEBUG_LOGLEVEL`    | `info`  | Log level inside the debug container.                            |
| `ODOO_WORKERS_WEB`       | `6`     | Number of Odoo web worker processes.                             |
| `ODOO_PYTHON_VERSION`    | —       | Python version for the Odoo container (e.g. `3.12`).             |
| `ODOO_INSTALL_LIBPOSTAL` | `0`     | `1` = install libpostal for address parsing.                     |

## Containers

| Setting               | Default | Description                                                    |
| --------------------- | ------- | -------------------------------------------------------------- |
| `RUN_ODOO`            | `1`     | Run the Odoo container (web + supervised sibling roles).       |
| `RUN_ODOO_CRONJOBS`   | `1`     | Spawn the cronjobs sibling role inside the odoo container.     |
| `RUN_PROXY`           | `1`     | Run the Node.js reverse proxy.                                 |
| `RUN_PROXY_PUBLISHED` | `0`     | `1` = expose proxy port to host (required for browser access). |
| `RESTART_CONTAINERS`  | `0`     | `1` = set `restart: unless-stopped` on all containers.         |

## PostgreSQL

| Setting                      | Default   | Description                                               |
| ---------------------------- | --------- | --------------------------------------------------------- |
| `POSTGRES_VERSION`           | `14`      | PostgreSQL version: `11`, `12`, `13`, `14`, `15`.         |
| `HOST_DB_PORT`               | —         | Expose postgres on this host port (macOS/WSL only).       |
| `NAMED_ODOO_POSTGRES_VOLUME` | —         | Use a named external volume (not deleted with `down -v`). |
| `DB_SSLMODE`                 | `disable` | PostgreSQL SSL mode.                                      |

## Queue Jobs

| Setting                                    | Default  | Description                                       |
| ------------------------------------------ | -------- | ------------------------------------------------- |
| `ODOO_QUEUEJOBS_CHANNELS`                  | `root:1` | Queue channel configuration: `root:4,magento2:1`. |
| `QUEUEJOBS_MAX_AGE_BEFORE_RESTART_MINUTES` | `120`    | Restart queuejob worker if idle for this long.    |

## Standard Odoo Image

| Setting                    | Default | Description                                                                         |
| -------------------------- | ------- | ----------------------------------------------------------------------------------- |
| `ODOO_STANDARD_IMAGE`      | `0`     | `1` = run the official `odoo:<version>` image from Docker Hub instead of our build. |
| `ODOO_STANDARD_IMAGE_NAME` | —       | Override the image reference (default `odoo:${ODOO_VERSION_INT}`).                  |

Everything around Odoo keeps working: proxy, postgres, barman and the whole
monitoring stack are independent of the Odoo image. What lives _inside_ our
image is gone, so these commands are unavailable or behave differently:

- `odoo shell` / `odoo debug odoo_debug` / unit tests / `odoo lang` — refused
  with a clear message (they need `/odoolib`).
- `odoo update` and `odoo db reset` run through the official Odoo CLI
  (`odoo -i <mods> -u <mods> --stop-after-init`) in a one-off container.
- `odoo backup files` does not see the filestore: it lives in the named
  volume `odoo-standard-data`, not under `${ODOO_FILES}`. The database is
  fully covered by barman.

## Registry

| Setting            | Default | Description                                                                       |
| ------------------ | ------- | --------------------------------------------------------------------------------- |
| `HUB_URL`          | —       | Docker registry: `host:port/path` or `user:password@host:port/path`.              |
| `REGISTRY`         | `0`     | `1` = rewrite all image URLs to HUB_URL, disable local builds. Use on production. |
| `DOCKER_IMAGE_TAG` | —       | Tag for registry images (e.g. `latest`, `v1.2.3`).                                |

## Memory Limits

| Setting                       | Default | Description                               |
| ----------------------------- | ------- | ----------------------------------------- |
| `LIMIT_MEMORY_HARD_WEB`       | `18 GB` | Hard memory limit for web worker (bytes). |
| `LIMIT_MEMORY_SOFT_WEB`       | `16 GB` | Soft memory limit for web worker.         |
| `LIMIT_MEMORY_HARD_QUEUEJOBS` | `18 GB` | Hard memory limit for queuejob worker.    |
| `LIMIT_MEMORY_HARD_CRON`      | `18 GB` | Hard memory limit for cron worker.        |
| `LIMIT_MEMORY_HARD_UPDATE`    | `88 GB` | Memory limit during module updates.       |

## APT Proxy (build acceleration)

| Setting          | Description                                                                 |
| ---------------- | --------------------------------------------------------------------------- |
| `APT_PROXY_IP`   | IP of apt-cacher-ng proxy, speeds up Docker builds by caching apt packages. |
| `RUN_APT_CACHER` | `1` = run the built-in apt-cacher container.                                |

## Warmup (startup performance)

| Setting                | Default          | Description                                   |
| ---------------------- | ---------------- | --------------------------------------------- |
| `MAX_WARMUP_WORKERS`   | ODOO_WORKERS_WEB | Override warmup worker count.                 |
| `MAX_PARALLEL_WARMUP`  | `4`              | Max concurrent warmup HTTP requests.          |
| `ODOO_READY_TIMEOUT_S` | `60`             | Seconds to wait for Odoo to become reachable. |
| `ODOO_WARMUP_REQUESTS` | worker count     | Total warmup requests to send.                |

## Extra Odoo config

Append arbitrary Odoo server config via settings:

```bash
# Add to [options] section of odoo.conf:
EXTRA_CONFIG_my_key=value

# Or edit ~/.odoo/settings/odoo.config (or odoo.config.<PROJECT_NAME>):
```

```ini
[options]
setting1=value1

[queue_job]
channels=root:4
```

## Encrypted Offsite Backup (restic)

Full guide: [11-offsite-backup.md](./11-offsite-backup.md). Against our own
backup server, do not set these by hand — `odoo offsite register` fills them in.

| Setting                    | Default                     | Description                                                                                                                                                                                                                                              |
| -------------------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `RUN_OFFSITE`              | `0`                         | Enables the offsite service. On DEVMODE machines it stays off unless `OFFSITE_FORCE_IN_DEVMODE=1`.                                                                                                                                                       |
| `OFFSITE_REPO`             | _(empty)_                   | Target: `rest:https://host:8000/<area>/` (our backup server), `sftp:user@host:port/path`, or a path on a mounted filesystem. Empty means "not configured" — the backup command then explains itself instead of doing nothing.                            |
| `OFFSITE_REST_USER`        | _(empty)_                   | Area account on the backup server (`rest:` targets). Governs who may **write**, not who may read.                                                                                                                                                        |
| `OFFSITE_REST_PASSWORD`    | _(empty)_                   | Password for that account.                                                                                                                                                                                                                               |
| `OFFSITE_PASSPHRASE`       | _(empty)_                   | Repository key. **Without it the backups are lost** — it must exist outside this machine (1Password / the hosting backend).                                                                                                                              |
| `OFFSITE_ENROLL_URL`       | `https://10.222.0.106:8443` | Enrollment service that `odoo offsite register` talks to.                                                                                                                                                                                                |
| `OFFSITE_LOCAL_DIR`        | _(empty)_                   | Host directory mounted into the container — only for path targets, so `OFFSITE_REPO` reads the same on both sides.                                                                                                                                       |
| `OFFSITE_BACKUP_CRON`      | `0 4 * * *`                 | Nightly run, deliberately after the Barman base backup (02:00).                                                                                                                                                                                          |
| `OFFSITE_KEEP_DAILY`       | `7`                         | Retention. Against append-only targets these describe what should apply **server-side**; the client cannot prune there.                                                                                                                                  |
| `OFFSITE_KEEP_WEEKLY`      | `4`                         |                                                                                                                                                                                                                                                          |
| `OFFSITE_KEEP_MONTHLY`     | `6`                         |                                                                                                                                                                                                                                                          |
| `OFFSITE_COMPRESSION`      | `auto`                      | `auto`, `off` (already-compressed sources) or `max` (line costs more than CPU).                                                                                                                                                                          |
| `OFFSITE_INCLUDE_DUMPS`    | `0`                         | Also back up all of `$DUMPS_PATH`. Off by default: with Barman the database is already covered, and the dumps folder often holds many old states.                                                                                                        |
| `OFFSITE_ALLOW_WITHOUT_DB` | `0`                         | Emergency exit for the completeness check. The run aborts when no database state would be in the snapshot — a snapshot of attachments alone looks like a backup until someone restores. Only set this when the database is provably backed up elsewhere. |
| `OFFSITE_ALLOW_WITHOUT_FILES` | `0`                      | The same check in the other direction: the run aborts when the filestore is missing or empty — which is exactly what an unmounted volume looks like. The database would be saved, the attachments not, and it would only show up on restore. |
| `OFFSITE_LAYOUT`           | `split`                     | `split` writes two repositories per area, `<area>/db` and `<area>/files`, so each part has its own visible age on the backup server. `flat` is the old single-repository behaviour and exists for legacy installations only. |
| `OFFSITE_WO_URL`           | _(empty)_                   | Write-only receiver for the filestore. Set together with `OFFSITE_WO_RECIPIENT` it replaces the restic `files` stream: the machine can then neither read nor delete what it uploaded. |
| `OFFSITE_WO_RECIPIENT`     | _(empty)_                   | age **public** key for the write-only path. The private key belongs in 1Password — without it the filestore cannot be restored, with it on the machine the point is lost. |
| `OFFSITE_WO_DB_RECIPIENT`  | _(empty)_                   | age **public** key for the write-only database stream (base backups + WAL). Set together with `OFFSITE_WO_URL` it replaces the restic `db` stream. A different key from the filestore one on purpose. |
| `OFFSITE_WAL_CRON`         | `* * * * *`                 | How often WAL segments are pushed. Every minute, so a machine loss costs a minute of transactions rather than a night. Quiet no-op when there is nothing new. |
| `OFFSITE_UPLOAD_LIMIT`     | `0`                         | Upload brake in KiB/s, `0` = unlimited.                                                                                                                                                                                                                  |
| `OFFSITE_FORCE_IN_DEVMODE` | `0`                         | Run offsite backups on a DEVMODE machine anyway (testing).                                                                                                                                                                                               |

## Update strategy

| Setting           | Value     | Description                                                     |
| ----------------- | --------- | --------------------------------------------------------------- |
| `UPDATE_STRATEGY` | _(empty)_ | Update all modules listed in MANIFEST `install`.                |
| `UPDATE_STRATEGY` | `odoo.sh` | Only update modules changed since last deployment (by version). |
