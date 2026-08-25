# Database backup and point-in-time recovery (pgBackRest)

`RUN_PGBACKREST=1` gives the instance continuous WAL archiving plus scheduled
base backups, and with them recovery to **any second** inside the retention
window rather than to last night's dump.

This replaces the earlier barman integration. The two solve the same problem and
differ in one structural way that explains everything else on this page:

| | barman (removed) | pgBackRest |
| --- | --- | --- |
| WAL capture | **streamed** (`pg_receivewal` against a replication slot) | **archived** (`archive_command`) |
| Runs inside the postgres container | nothing | the `archive_command`, so the binary lives there |
| Incremental granularity | whole files (rsync hardlinks) | **8 KiB pages** (block incremental) |
| Expiry | `retention_policy`, applied by barman's cron | part of every backup run |

The page-level incrementals are the reason for the switch: postgres already
knows which pages changed, so nothing has to be rediscovered by hashing a byte
stream.

## What runs where

```
┌──────────────────────┐        ┌──────────────────────────┐
│ postgres container   │        │ pgbackrest sidecar       │
│  archive_command ────┼───┐    │  reads PGDATA            │
│  pgbackrest (client) │   │    │  pg_backup_start/stop    │
└──────────┬───────────┘   │    └───────────┬──────────────┘
           │ shared volumes │                │
           ├── PGDATA ──────┴────────────────┤
           └── /var/run/postgresql (socket) ─┘
```

Two shared mounts, and neither is a convenience:

- **PGDATA**, because pgbackrest reads the data directory directly.
- **the socket directory**, because pgbackrest has *no option* to reach postgres
  over TCP. `pg1-host` means "run the pgbackrest process on that remote
  machine", not "connect libpq there" — since it must read PGDATA anyway, it
  always considers itself co-located with the cluster. Inside a compose stack
  that co-location has to be manufactured, and these two volumes are how.

The `archive_command` is executed by the postgres server process itself, which
is why `pgbackrest` is installed in the postgres images too. Without
`RUN_PGBACKREST=1` nothing of it is configured and postgres keeps its stock
setup.

## Repository topology

Two modes, chosen by whether `PGBACKREST_REPO_HOST` is set.

### Local repository (development, testing)

Empty `PGBACKREST_REPO_HOST`. The repository lives in the `pgbackrest_data`
volume on this machine. No certificates, no second host — and the only mode that
works without a backup server. Backups are driven from here.

### Repository host (production)

`PGBACKREST_REPO_HOST=<backup server>`, transport TLS. The repository lives on
the backup server. **Who drives the backup** is then a second decision,
`PGBACKREST_BACKUP_FROM`, and it decides both the firewall shape and where
retention is configured.

| | `here` (default) | `repo-host` |
| --- | --- | --- |
| runs `backup` and `expire` | this machine | the backup server |
| connections | **all outbound** | outbound WAL **plus inbound** on `PGBACKREST_TLS_SERVER_PORT` |
| open port on this machine | none | yes |
| can this machine delete backups? | **yes** | no |
| retention configured | **here** | on the backup server |

**`repo-host` is the stronger shape.** This machine holds no repository
passphrase, has no delete rights, and can only push WAL — stronger than an
append-only target, because it never touches the repository storage at all.

**`here` is the shape that survives a restrictive network**, and it is the
default because a misconfigured `repo-host` fails silently until backup time.
The delete rights it hands this machine are only acceptable if something
downstream keeps a copy the machine cannot reach — see *Where the protection
lives* below.

Either way the certificate in `$HOST_RUN_DIR/pgbackrest/cert/` is an
**identity**, not a key: it proves who may write, and opens nothing.
`tls-server-auth` binds one client certificate to one stanza, so a certificate
signed by the same CA cannot back up somebody else's instance.

### Where the protection lives

With `BACKUP_FROM=here` a compromised Odoo machine can run `expire`, or simply
delete, against the repository on the backup server. That is inherent: expiring
a backup *is* a delete, and the machine that expires needs the right.

This is acceptable when the backup server copies the repository onward to a
target the Odoo machine cannot reach — a write-only or append-only destination.
The property has not disappeared, it has moved one layer out. Two things follow
from that, and both are easy to miss:

- **The downstream copy's retention is the real guarantee**, not
  `PGBACKREST_RETENTION_FULL`. pgBackRest expires on the backup server; whatever
  was already copied onward is outside its reach and is governed by that
  target's own rules. If the downstream target keeps 90 days and pgbackrest
  keeps 14, the answer to "how far back can we go" is 90 — but only by
  restoring from the downstream copy by hand, since the local repository no
  longer references those backups.
- **The exposure window is the copy interval.** Anything deleted before the
  next onward copy runs was never protected. A copy that runs right after the
  nightly backup is a much smaller window than one that runs weekly.

### Ports, firewalls, and why this is not HTTPS

The repo-host topology needs **two connections in opposite directions**, which
is the part worth knowing before writing a firewall rule:

| direction | carries | port setting | when |
| --- | --- | --- | --- |
| this machine → backup server | WAL, and with `BACKUP_FROM=here` the backups too | `PGBACKREST_REPO_HOST_PORT` | always |
| backup server → **this machine** | the base backup — the repo host pulls | `PGBACKREST_TLS_SERVER_PORT` | only `BACKUP_FROM=repo-host` |

The inbound one surprises people. It is not an accident: the repo host runs
`pgbackrest backup` precisely so that this machine never touches the
repository. `BACKUP_FROM=here` removes that direction entirely.

Both ports are freely settable, so **443 on either side is fine** and is the
usual answer to a firewall that only lets 443 out. What it does *not* do is turn
this into HTTPS:

> pgBackRest speaks **its own protocol inside TLS**, not HTTP inside TLS, and it
> authenticates with **mutual TLS** — `tls-server-auth` maps a client
> certificate's CN to a stanza.

So:

- **Port-based firewall** — use 443, done.
- **L7 reverse proxy that terminates TLS** (nginx `http`, Traefik HTTP router,
  Cloudflare) — **does not work.** There are no HTTP requests to route, and
  terminating the TLS discards the client certificate the authorisation is
  built on.
- **TCP or SNI passthrough** (nginx `stream`, HAProxy `mode tcp`, Traefik TCP
  router with `passthrough`) — works, because the bytes are handed through
  untouched. This is the way to put it on 443 alongside real web traffic.

If an inbound port is not acceptable at all, `PGBACKREST_BACKUP_FROM=here`
makes every connection outbound. See the table above for what that costs.

> **Not turnkey yet.** There is no enrolment command. The certificates
> (`ca.crt`, `server.crt`, `server.key`, `client.crt`, `client.key`) have to be
> placed in `$HOST_RUN_DIR/pgbackrest/cert/` by hand, and the backup server side
> — a repo host running `pgbackrest server` against the NFS mount — does not
> exist yet either. Until it does, leave `PGBACKREST_REPO_HOST` empty.

## Schedule and retention

The defaults are a **weekly full plus daily differentials**, not a nightly full.
At roughly 16 GiB per full for a 45 GiB database, a nightly full is 5.8 TiB a
year for a single instance.

| Setting | Default | |
| --- | --- | --- |
| `PGBACKREST_FULL_CRON` | `0 2 * * 0` | Sunday — the quietest day, so the cheapest slot |
| `PGBACKREST_DIFF_CRON` | `0 2 * * 1-6` | daily |
| `PGBACKREST_INCR_CRON` | *(empty)* | opt-in, intra-day |
| `PGBACKREST_RETENTION_FULL` | `14` | with `..._TYPE=time`: days of continuous PITR |
| `PGBACKREST_RETENTION_ARCHIVE` | *(empty)* | empty = continuous WAL across the whole window |

**Diff rather than incr for the daily rhythm** is deliberate: a differential
depends only on the full, an incremental on its predecessor. A chain of six
incrementals has to be read end to end on restore, and one damaged link takes
its successors with it. With block-level incrementals a diff costs barely more.

Intra-day incrementals do not improve the recovery *point* — the WAL archive
already gives every second. They shorten the recovery *time*, because less WAL
has to be replayed, and replay is single-threaded.

### The WAL retention lever

`PGBACKREST_RETENTION_ARCHIVE` empty keeps the WAL for every retained full
backup, i.e. a continuous window. Setting it to a number keeps continuous WAL
only for that many recent backups; older ones stay restorable, but only to their
own end point.

That is how to keep old states without paying for the gaps between them.

`PGBACKREST_BACKUP_FROM` decides *where* these values belong: they are read by
whichever machine runs `expire`. With `repo-host` they are ignored here and go
into the backup server's configuration instead — the rendered configuration
leaves them out rather than pretending otherwise.

### Expiry is not a separate job

`expire` runs as the last step of every backup. This is on purpose: a cleanup
that has to be scheduled separately is a cleanup that eventually is not — see
`JOB_DADDY_CLEANUP` in `cronjobs/default.settings`, which is defined but has no
`CRONJOB_` counterpart and therefore never runs.

For the same reason the configuration always emits `repo1-retention-full`, even
when the setting is empty. pgBackRest without it expires **nothing**, says so
once in a log line, and then keeps every backup forever.

## Commands

```bash
odoo pgbackrest backup --type full    # or diff / incr
odoo pgbackrest info                  # backups, sizes, WAL range
odoo pgbackrest check                 # does the whole archiving path work?
odoo pgbackrest restore               # interactive target picker
odoo pgbackrest restore --target-time "2026-05-31 14:25:00"
odoo pgbackrest restore --target-name pre_update_20260531120000
odoo pgbackrest expire                # normally unnecessary
```

`odoo pgbackrest check` is the one worth running after any change. It verifies
that the repository is reachable, that the `archive_command` works, and that a
freshly switched segment really arrives — it is the command that says whether
the backups are worth anything.

### Restoring

`restore` stops the stack, rewrites the data directory, and starts postgres so
it can replay WAL and promote.

Two differences from the old barman path worth knowing before the first time:

- **`--delta` is the default.** Only files whose checksum differs are fetched,
  which usually turns a restore from "copy the whole database" into "copy what
  changed". `--no-delta` forces a full restore, which is the right choice when
  the existing data directory is suspected corrupt.
- **There is no automatic rollback copy.** barman staged the recovery elsewhere
  and kept the old data directory; pgbackrest restores in place, which is what
  makes `--delta` fast. `--keep-previous` preserves the old directory, at the
  cost of a second full copy of the database on disk.

After a restore the timeline changes, so take a fresh full backup.

## Update guard

`PGBACKREST_GUARD_UPDATE=1` makes every `odoo update` set a named restore point
first, and offers to rewind to it if the update fails. The marker's WAL segment
is switched and verified as archived before the update starts — an unarchived
marker cannot be recovered to.

## Migrating from barman

The barman catalogue is **not** migrated. pgbackrest starts a fresh stanza with
its own history.

```bash
odoo setting RUN_BARMAN=0
odoo setting RUN_PGBACKREST=1
odoo reload && odoo up -d
odoo pgbackrest backup --type full
odoo pgbackrest check
```

Keep the barman volume until that first backup is verified. A project that still
carries `RUN_BARMAN=1` gets a loud message at `odoo reload`: the service no
longer exists, so nothing would fail and nothing would log — it would surface on
the day somebody needs a restore.

## Offsite

The offsite path reads this repository read-only and pushes it to a write-only
receiver, encrypted to a public key. See
[11-offsite-backup.md](./11-offsite-backup.md).
