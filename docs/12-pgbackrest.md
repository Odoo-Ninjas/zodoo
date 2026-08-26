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

Two modes, chosen by whether `PGBR_REPO_HOST` is set.

### Local repository (development, testing)

Empty `PGBR_REPO_HOST`. The repository lives in the `pgbackrest_data`
volume on this machine. No certificates, no second host — and the only mode that
works without a backup server. Backups are driven from here.

### Repository host (production)

`PGBR_REPO_HOST=<backup server>`, transport TLS. The repository lives on
the backup server. **Who drives the backup** is then a second decision,
`PGBR_BACKUP_FROM`, and it decides both the firewall shape and where
retention is configured.

| | `here` (default) | `repo-host` |
| --- | --- | --- |
| runs `backup` and `expire` | this machine | the backup server |
| connections | **all outbound** | outbound WAL **plus inbound** on `PGBR_TLS_SERVER_PORT` |
| open port on this machine | none | yes |
| can this machine delete backups? | **yes** | no |
| retention configured | on the backup server | on the backup server |

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

### Retention lives on the backup server

**With any repo host, retention is configured in exactly one place: on the
backup server.** The rendered configuration on this machine deliberately
contains no `repo1-retention-*` at all, in both `BACKUP_FROM` modes.

The rule is *the machine that manages the disk manages the retention*. The
backup server is the one that watches the free space, so it is the one that
decides what goes. The alternative — the same number maintained on every Odoo
host — drifts the moment somebody changes one of them.

The mechanism is a property of pgBackRest rather than a trick: **without
`repo1-retention-*` the expire step at the end of a backup does nothing.** So
with `BACKUP_FROM=here` the Odoo machine takes the backup and expires nothing,
and the backup server runs its own scheduled

```bash
pgbackrest --stanza=<stanza> expire
```

against its own values. `expire` is a repository-only operation — it needs no
reachable cluster, which is what makes this work at all.

`PGBR_RETENTION_*` therefore applies **only to a local repository**, where
there is no other machine to do it. `odoo reload` says so in a yellow line
whenever a repo host is configured.

> **The one thing to actually check:** if the backup server has no scheduled
> `expire`, *nothing* expires — the Odoo side no longer does it and the backup
> server was never asked to. The repository then grows until the disk is full.
> This is a real trade for having one source of truth, and it is the same
> failure mode that let a dump directory reach 3.4 TB.

### Where the protection lives

With `BACKUP_FROM=here` a compromised Odoo machine can delete from the
repository on the backup server. That is inherent to pushing: the machine that
writes can unwrite.

This is acceptable when the backup server copies the repository onward to a
target the Odoo machine cannot reach — a write-only or append-only destination.
The property has not disappeared, it has moved one layer out. Two consequences
are easy to miss:

- **The downstream target's retention is a third, independent policy.**
  pgBackRest does not know about it and cannot govern it. Whatever was already
  copied onward is outside the reach of any `expire`. If that target keeps
  longer than the backup server does, those extra backups are still there but
  the pgBackRest catalogue no longer references them — restoring from that far
  back means fetching a base backup plus its WAL range by hand.
- **The exposure window is the copy interval.** Anything deleted before the
  next onward copy runs was never protected. A copy that runs right after the
  nightly backup is a much smaller window than one that runs weekly.

### Ports, firewalls, and why this is not HTTPS

The repo-host topology needs **two connections in opposite directions**, which
is the part worth knowing before writing a firewall rule:

| direction | carries | port setting | when |
| --- | --- | --- | --- |
| this machine → backup server | WAL, and with `BACKUP_FROM=here` the backups too | `PGBR_REPO_HOST_PORT` | always |
| backup server → **this machine** | the base backup — the repo host pulls | `PGBR_TLS_SERVER_PORT` | only `BACKUP_FROM=repo-host` |

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

If an inbound port is not acceptable at all, `PGBR_BACKUP_FROM=here`
makes every connection outbound. See the table above for what that costs.

> **Not turnkey yet.** There is no enrolment command. The certificates
> (`ca.crt`, `server.crt`, `server.key`, `client.crt`, `client.key`) have to be
> placed in `$HOST_RUN_DIR/pgbackrest/cert/` by hand, and the backup server side
> — a repo host running `pgbackrest server` against the NFS mount — does not
> exist yet either. Until it does, leave `PGBR_REPO_HOST` empty.

## Schedule and retention

The defaults are a **weekly full plus daily differentials**, not a nightly full.
At roughly 16 GiB per full for a 45 GiB database, a nightly full is 5.8 TiB a
year for a single instance.

| Setting | Default | |
| --- | --- | --- |
| `PGBR_FULL_CRON` | `0 2 * * 0` | Sunday — the quietest day, so the cheapest slot |
| `PGBR_DIFF_CRON` | `0 2 * * 1-6` | daily |
| `PGBR_INCR_CRON` | *(empty)* | opt-in, intra-day |
| `PGBR_RETENTION_FULL` | `14` | with `..._TYPE=time`: days of continuous PITR |
| `PGBR_RETENTION_ARCHIVE` | *(empty)* | empty = continuous WAL across the whole window |

**Diff rather than incr for the daily rhythm** is deliberate: a differential
depends only on the full, an incremental on its predecessor. A chain of six
incrementals has to be read end to end on restore, and one damaged link takes
its successors with it. With block-level incrementals a diff costs barely more.

Intra-day incrementals do not improve the recovery *point* — the WAL archive
already gives every second. They shorten the recovery *time*, because less WAL
has to be replayed, and replay is single-threaded.

### The WAL retention lever

`PGBR_RETENTION_ARCHIVE` empty keeps the WAL for every retained full
backup, i.e. a continuous window. Setting it to a number keeps continuous WAL
only for that many recent backups; older ones stay restorable, but only to their
own end point.

That is how to keep old states without paying for the gaps between them.

These apply to a **local repository only**. With a repo host they are ignored
and the repository's owner decides — see *Retention lives on the backup server*.

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

## Encryption

Two different questions, two different answers.

**In transit: always.** The connection to a repository host is TLS 1.3 with
mutual certificates - the instance proves itself with its client certificate,
the server with its own. A TCP/SNI passthrough in between does not terminate
it, so the encryption is genuinely end to end.

**At rest: only if you set a passphrase.** Without `PGBR_CIPHER_PASS` the
repository is plain zstd. The manifest is readable text and every data file
unpacks with `zstd -d`:

```
$ head -c 120 .../backup.manifest
[backup]
backup-archive-start="00000002000000000000000C"
backup-label="20260825-195522F"

$ od -c .../pg_data/base/1/1255.zst
0000000  ( 265   / 375 ...            <- zstd magic, not encryption
```

With a passphrase, the same files:

```
0000000   S   a   l   t   e   d   _   _ ...
```

Manifest, data files and WAL segments alike.

That matters whenever the storage under the backup server is not yours - as
with a rented NFS share, where "nobody can get at it" is not an argument.

### Where the passphrase lives

**On the Odoo machine, not on the backup server.** The pgBackRest guide is
explicit that encryption is *always performed client-side*: the backup server
stores ciphertext and never learns the passphrase. So a compromised backup
server - or a curious storage provider - gets nothing.

One passphrase **per area**, so one customer's key cannot open another's.
`pgbackrest-area create <name>` on the backup server issues it, shows it
**once**, and stores it nowhere, the same discipline the old restic repo keys
had. It belongs in the hosting record before the first backup runs.

> **Two things that bite.**
> Lose the passphrase and the backup is worthless - there is no recovery path.
> And it **cannot be switched on later**: pgBackRest cannot convert an existing
> repository, so the stanza has to be created fresh and the history starts
> over. Decide before real data goes in.

`odoo reload` prints a red warning when a repo host is configured without a
passphrase, because that is the case where unencrypted data leaves the machine.

## Enrolment

Getting a machine onto the backup server by hand means moving three files and a
passphrase around. The passphrase is the one value that cannot be replaced
afterwards, so chat and copy-paste are exactly the wrong tools for it.

```
odoo pgbackrest register
```

The first call files a request. An admin sees it at
`https://db.backup.zebroo.de:8445/`, checks the name and approves; only then do
the client certificate and the passphrase come into existence. They are shown
once, the admin puts the passphrase into 1Password and confirms that - and only
after that confirmation will the service hand anything to the machine. A
passphrase that lives solely on the machine being backed up is worthless in the
one situation backups exist for.

Calling `register` again then collects everything: `ca.crt`, `client.crt` and
`client.key` land in `$HOST_RUN_DIR/pgbackrest/cert/` (the key at 0600, which
pgBackRest insists on), and `PGBR_STANZA`, `PGBR_REPO_HOST`,
`PGBR_REPO_HOST_PORT`, `PGBR_CIPHER_TYPE`, `PGBR_CIPHER_PASS`,
`PGBR_BACKUP_FROM` and `RUN_PGBACKREST` go into the settings. Then:

```
odoo reload && odoo up -d && odoo pgbackrest check
```

Two properties are worth knowing:

* **Handed out exactly once.** After delivery the server deletes the passphrase
  from its own state; a second call answers `delivered` and nothing else. If
  the machine loses it before `odoo reload`, it comes from 1Password - not from
  the backup server, which only ever stores ciphertext.
* **The CA is pinned on first contact,** with its fingerprint printed, the same
  bargain ssh makes with `accept-new`. Any later change aborts the connection.

The service also files an age-encrypted envelope of the credentials on the
backup server. Encrypted against a *public* key whose private half is in
1Password, so the server can write it but never read it - which is what makes
it safe to attach to the project record in hosting.zebroo.de.

The service listens on 8445. Three ports, three different things: 8443 speaks
pgBackRest's own protocol (not HTTP), 8444 is the write-only receiver that takes
the filestores, and the enrolment service is ordinary HTTPS beside them.

## One version, everywhere

pgBackRest requires the **same version on every host that touches a
repository** — client and repository server alike. On a mismatch archiving and
backups stop:

```
[ProtocolError] expected value '2.59' for greeting key 'version' but got '2.50'
```

**The host distribution does not matter.** pgbackrest never runs on the host
here — it runs in our images, the sidecar (`ubuntu:24.04`) and the postgres
images (Debian). Ubuntu 20.04, Debian, Arch or RHEL underneath makes no
difference to what version is in play. Exactly one thing decides it:

```
PGBR_VERSION=2.59.1
```

It is a build argument for **both** images, pinned as `pgbackrest=<version>-*`
— the wildcard because the pgdg package revision is distribution-specific
(`2.59.1-1.pgdg24.04+1` vs `2.59.1-1.pgdg110+1`) while the upstream version is
what has to match. Left empty, a project installs unpinned, which is what
happens on projects without pgBackRest.

The backup server is the one host where pgbackrest **is** installed natively,
so it has to be upgraded in the same window. There the pgdg apt repository
supplies the matching build.

`odoo pgbackrest check` reports the version and complains loudly when the two
containers disagree — which is what happens when `PGBR_VERSION` changed and
only one image was rebuilt.

> **Upgrading:** change `PGBR_VERSION`, `odoo reload && odoo build postgres
> pgbackrest`, and `apt install pgbackrest=<version>-*` on the backup server —
> in one window. The repository format is stable across 2.x, so it is only the
> binaries.

## Settings are named `PGBR_*`, never `PGBACKREST_*`

pgBackRest reads its **own** options from the environment with a `PGBACKREST_`
prefix — `PGBACKREST_REPO_HOST` is the option `repo-host`, `PGBACKREST_BUNDLE`
is `bundle`. zodoo exports every setting into every container, so a setting by
such a name is handed straight to pgbackrest as one of its own options:

```
ERROR: [031]: option 'repo-host-type' requires an index
WARN: environment contains invalid option 'bundle'
```

The ones that fail are the harmless half. `compress-type`, `process-max` and
`archive-async` *are* valid options, and those silently override the
configuration file. Hence `PGBR_*`. `RUN_PGBACKREST` and the `CRONJOB_PGBACKREST_*`
entries do not collide and keep their names.

## Update guard

`PGBR_GUARD_UPDATE=1` makes every `odoo update` set a named restore point
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
