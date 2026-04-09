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

| Setting           | Default            | Description                                                                     |
| ----------------- | ------------------ | ------------------------------------------------------------------------------- |
| `PROJECT_NAME`    | —                  | Container name prefix and postgres volume name. **Keep short** (max ~20 chars). |
| `DBNAME`          | PROJECT_NAME       | PostgreSQL database name.                                                       |
| `PROXY_PORT`      | —                  | HTTP port to access Odoo in browser. Set with `odoo setup next-port`.           |
| `DEBUG_PORT`      | —                  | Port for Python debugger. Set with `odoo setup next-port`.                      |
| `EXTERNAL_DOMAIN` | `http://localhost` | Public URL of the system.                                                       |

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

| Setting                                | Default | Description                                                    |
| -------------------------------------- | ------- | -------------------------------------------------------------- |
| `RUN_ODOO`                             | `1`     | Run the Odoo web container.                                    |
| `RUN_ODOO_CRONJOBS`                    | `1`     | Run a separate cronjob container.                              |
| `RUN_ODOO_QUEUEJOBS`                   | `1`     | Run a separate queuejob container.                             |
| `ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER` | `0`     | `1` = run queuejobs + cronjobs inside the main web container.  |
| `RUN_PROXY`                            | `1`     | Run the Node.js reverse proxy.                                 |
| `RUN_PROXY_PUBLISHED`                  | `0`     | `1` = expose proxy port to host (required for browser access). |
| `RESTART_CONTAINERS`                   | `0`     | `1` = set `restart: unless-stopped` on all containers.         |

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

## Update strategy

| Setting           | Value     | Description                                                     |
| ----------------- | --------- | --------------------------------------------------------------- |
| `UPDATE_STRATEGY` | _(empty)_ | Update all modules listed in MANIFEST `install`.                |
| `UPDATE_STRATEGY` | `odoo.sh` | Only update modules changed since last deployment (by version). |
