# Encrypted Offsite Backup (restic)

The `offsite` service pushes an encrypted, deduplicated copy of a project's
database and filestore off the machine. Encryption happens **here**, before
anything leaves the container — the storage side only ever sees ciphertext.

Since 2026-08 this runs on [restic](https://restic.net). It replaced
BorgBackup; there is deliberately only one mechanism, so nobody has to work out
which of two is active on a given machine.

## The shape of it

```
Odoo machine                                     backup server
┌───────────────────────────────┐                ┌──────────────────────────┐
│ offsite container             │                │ rest-server              │
│  restic backup                │──── HTTPS ────▶│  --append-only           │
│  (encrypts + deduplicates)    │   port 8000    │  --private-repos         │
└───────────────────────────────┘                └───────────┬──────────────┘
   sources (read-only):                                      │
     /source/barman     Barman catalog (WAL + base backup)    ▼
     /source/filestore  this database's filestore        <area>/db
     /source/dumps      optional / the fresh dump        <area>/files
```

## Two repositories per area

A run writes into **two** repositories under the same customer area:

| Repository      | Contents                                | Snapshot tags |
| --------------- | --------------------------------------- | ------------- |
| `<area>/db/`    | Barman catalog, or the database dump    | `zodoo,db`    |
| `<area>/files/` | the filestore of this database          | `zodoo,files` |

The reason is monitoring, not tidiness. With everything in one repository, an
arriving filestore hides a database dump that stopped coming: the area looks
freshly written, and the part that matters is missing. Split, each stream has its
own age, and the backup server alarms per stream — the mail then says *which*
half stopped.

Both live in the same area and therefore share access credentials and
passphrase. It stays **one secret per project**; two passphrases would be two
things to lose, neither protecting anything the other does not.

`OFFSITE_LAYOUT=flat` restores the old single-repository behaviour. It exists for
legacy installations that should not be moved, not as a preference.

Three properties matter, and they are the reason for this setup:

- **The storage side cannot read the backup.** restic encrypts on the source
  machine. Whoever holds the disk — a provider, a foreign NFS export, a stolen
  drive — sees ciphertext.
- **The source machine cannot delete the backup.** `rest-server --append-only`
  accepts writes and refuses removals. A compromised Odoo host can therefore not
  destroy the history. This is the part a plain NFS mount can never provide, and
  it is the main reason the target is our own server rather than a share.
- **One customer cannot see another.** With `--private-repos` every account is
  confined to the path matching its username; anything else answers 401.

The trade-off of append-only is that **the client can no longer clean up**.
Retention has to run on the server side, and it has to actually run there — see
[Retention](#retention).

## Targets

| `OFFSITE_REPO`                               | What it is                                                                                    |
| -------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `rest:https://10.222.0.106:8000/<area>/`     | Our backup server. The normal case, append-only, one area per customer.                       |
| `sftp:u12345@u12345.your-storagebox.de:23/…` | Hetzner Storage Box or any SSH target. Key at `$HOST_RUN_DIR/offsite/id_ed25519` (mode 0600). |
| `/mnt/somewhere/repo`                        | A mounted filesystem. Also set `OFFSITE_LOCAL_DIR` so the path exists inside the container.   |

For a path target the run refuses to start when the parent directory is
missing. That is on purpose: an unmounted disk looks exactly like an empty
repository, and restic would happily create a fresh one on the local disk — which
is only discovered when the backup is needed.

## Setting it up against our backup server

Do not wire this by hand. The machine asks for an area, a human approves it:

```bash
odoo offsite register
```

1. The first call files a request (area name derived from the project name) and
   remembers request id + pickup token in `$HOST_RUN_DIR/offsite/enroll.json`.
   No credentials exist yet.
2. An admin opens the backup server's admin page, checks the name and approves.
   Access password and repo key are created at that moment.
3. Both are shown **exactly once**. The admin files them in 1Password and
   confirms that with a checkbox. **Without that confirmation the machine does
   not get its credentials** — a repo key that exists only on the source machine
   is worthless precisely when it is needed.
4. Run `odoo offsite register` again: it collects credentials and the server
   certificate, writes them into the settings and sets `RUN_OFFSITE=1`. The
   server then forgets the repo key.

```bash
odoo reload && odoo build offsite
odoo offsite backup          # first run, creates the repository
```

On first contact there is no server certificate on the machine yet. It is
fetched, pinned to `$HOST_RUN_DIR/offsite/rest-server.crt` and its fingerprint
printed — the same trust-on-first-use as `ssh accept-new`. Any later change
aborts the connection instead of being silently accepted.

**If the machine already has a passphrase** — zCICD and the shop generate one
per project and keep it in the backend — that passphrase stays the truth and the
server creates no second key. Two keys for one repository is a trap, not
redundancy.

## What gets backed up — and the check that must not be lost

A run collects, from read-only mounts:

- `/source/barman` — the Barman catalog (WAL + base backup), only present with
  `RUN_BARMAN=1`
- the filestore of **this** database (`filestore/$DBNAME`), not the host-wide
  pool; on a machine with several instances the pool holds other customers'
  attachments
- `/source/dumps` only with `OFFSITE_INCLUDE_DUMPS=1`, or the single fresh dump
  that `odoo offsite backup` pulls when Barman is off

**The run aborts when no database state would end up in the snapshot.** The
filestore is always there, the database is not — and a snapshot of nothing but
attachments looks like a backup until someone tries to restore. This is the
failure this system had before; it must survive every future refactor.

`OFFSITE_ALLOW_WITHOUT_DB=1` switches the check off. Only use it when the
database is provably backed up elsewhere.

**And the run aborts when no filestore would end up in the snapshot** — for the
same reason, in the other direction. A database restores fine without
attachments; it is just incomplete, and in Odoo that shows up the first time
someone clicks an invoice PDF. An empty or missing filestore directory is what an
unmounted volume looks like, not what an empty instance looks like, so an empty
directory does not count as a filestore. `OFFSITE_ALLOW_WITHOUT_FILES=1` is the
deliberate way out for an instance that genuinely has no attachments yet.

Both streams are attempted even when one fails, and the run then reports which.
Otherwise a broken database upload would mask that the filestore did not go
either, and one alarm would arrive where two belong.

The recommendation is `RUN_BARMAN=1`: it costs nothing extra (it runs on a disk
that is already paid for) and adds point-in-time recovery on top.

## Write-only filestore backup

The restic path has one property that cannot be configured away: a machine that
can back up can also **read** its own backup history, because deduplication
needs the repository index and the index is encrypted (see
[Keys](#keys)). A compromised Odoo host therefore reaches not just the live
database but every older state as well.

For the filestore that is avoidable, and cheaply, because Odoo already does the
hard part: **every attachment is named after the SHA-1 of its content**
(`filestore/<db>/05/055ffc5c…`). A file is written once and never changes, and
"same content" is already "same name" — the deduplication is in the naming. So
"what is missing at the far end?" is a pure name comparison, answerable from a
**local ledger** without reading the target at all.

Set both of these and the filestore leaves the restic path:

| Setting | What it is |
| --- | --- |
| `OFFSITE_WO_URL` | The write-only receiver, e.g. `https://10.222.0.106:8444/<area>/` |
| `OFFSITE_WO_RECIPIENT` | An **age public key** (`age1…`). Generate with `age-keygen`; the private key belongs in 1Password and nowhere else |

```bash
odoo offsite filestore     # or automatically as part of `odoo offsite backup`
```

What the machine can then do, and what it cannot:

| | restic path | write-only path |
| --- | --- | --- |
| upload | yes | yes |
| read what it uploaded | **yes, all of it** | **no** — encrypted to a public key it has no private half of |
| delete | no (append-only) | no |

When a write-only target is configured it **replaces** the restic `files`
stream rather than running beside it. Two copies of the same attachments in two
places is cost without redundancy, and it makes "which one do I restore from?"
a question during an incident.

### What travels, and what does not

New files go up as **one bundle per run** (`tar` → `gzip` → `age`), not one
object per file: an instance with a million attachments would otherwise mean a
million HTTP requests. Alongside it goes a manifest:

```json
{ "run": "20260821T173222Z", "kind": "filestore",
  "bundle": "filestore-20260821T173222Z-85914f45a55c.tar.gz.age",
  "sha256": "85914f45…", "size": 665623,
  "files_added": 56, "files_total": 56, "ledger_sha256": "8f73c96f…" }
```

The manifest lists **bundles, never file names**. That is deliberate: a file
name is the hash of its content, so a name list at the target would let someone
confirm whether a particular known document is in the backup. Bundle names and
checksums are enough for the receiving side to notice a missing bundle, which is
what completeness means here.

### The ledger

`$HOST_RUN_DIR/offsite.state/filestore.ledger` — one file name per line,
appended only **after** a successful upload. A crash between upload and ledger
write costs a repeated upload, never a file that is believed safe but never
arrived.

Losing the ledger (volume wiped, machine rebuilt) means the next run uploads the
whole filestore again. That is the price of never asking the target what it has;
it costs traffic, not data.

### Restoring

Needs the age private key from 1Password — this machine cannot do it:

```bash
age -d -i filestore.age-key -o bundle.tar.gz filestore-<run>-<sum>.tar.gz.age
tar xzf bundle.tar.gz -C $ODOO_FILES/filestore/<db>/
```

Unpack every bundle, oldest first. And the filestore checks itself: because each
name is the SHA-1 of its content, `sha1sum` over the restored tree against the
file names is a complete integrity check — no manifest, no checksum list, no key
required.

### The window against the database

WAL/PITR can recover the database to any moment; the filestore is pushed once a
night. So an attachment created at 14:00 is in the backup once the night has
passed, not before. The rule that follows: **the filestore must be at least as
new as the database recovery target.** An older database with a newer filestore
is always safe (a superset); the other way round, attachments are missing. Run
the sync more often if the window matters — it is cheap, because it works on
names.

## Write-only database backup (WAL)

The same move as the filestore, for the half that matters more. With
`RUN_BARMAN=1` the database is captured as **base backups plus WAL segments**,
and both are immutable: a WAL segment is written once and never changed, a base
backup directory never changes once barman marks it `DONE`. So there is nothing
to deduplicate — and therefore no need to read the target, which is what forces
a readable key onto the machine in the restic path.

| Setting | What it is |
| --- | --- |
| `OFFSITE_WO_DB_RECIPIENT` | age **public** key for the database stream. Deliberately a different key from the filestore one |
| `OFFSITE_WAL_CRON` | how often WAL is pushed. `* * * * *` — every minute |

```bash
odoo offsite db     # base backups + WAL (after the nightly barman backup)
odoo offsite wal    # WAL only, every minute via CRONJOB_OFFSITE_WAL
```

Two modes because they have different rhythms. WAL goes up **every minute**, so
losing the machine costs a minute of transactions rather than a night. The run is
cheap: nothing new means no upload, and it is silent, because it runs 1440 times
a day.

Why a separate key from the filestore: the two have different value and are
needed separately. "Somebody may restore the filestore but not the database" is
a real request, and one shared key cannot express it.

### What this buys beyond confidentiality

- **Completeness is checkable without a key.** WAL names are a sequence and the
  manifest declares, in the clear, which segments belong to which base backup
  (`begin_wal`/`end_wal`/`timeline`). In a restic repository the file names are
  encrypted, so only a key holder could ever notice a broken chain. On the
  backup server `wo-check` verifies: every declared object present and the right
  size, every base backup's `begin_wal` present, no gap inside a timeline, and
  manifests that only ever grow — a compromised machine cannot quietly declare
  less than it did yesterday.
- **Retention becomes possible without a key.** Whole generations can be dropped
  by name. An append-only restic repository cannot be pruned at all, because
  `forget --prune` needs the repo key.

### Sizes, measured

WAL compresses extraordinarily well because a segment is a fixed 16 MiB
regardless of how much is in it:

| | raw | transferred |
| --- | --- | --- |
| quiet WAL segment | 16 MiB | ~16 KB (factor ~1000) |
| busy WAL segment | 16 MiB | ~630 KB |
| base backup (small test DB) | 9.6 MB datadir | 5.8 MB |

A base backup is a full copy every time, so **its frequency is the only real
lever on growth**. WAL volume is the irreducible part — it is the actual write
volume of the database.

### The *.partial trap

`pg_receivewal` writes the segment currently being filled as
`streaming/<name>.partial`. It is incomplete by definition, and uploading it
would store a half-written segment under a name that is supposed to mean
"complete". Only `wals/` is ever read, and `*.partial` is excluded on top of
that.

### Concurrency

The minutely WAL job gets its **own container name**, because docker rejects a
duplicate name with a hard error and a job running every minute must not fail
every minute while a nightly base backup upload is still going. Serialisation
happens inside, on a lock in the state directory, where a busy lock is a quiet
success rather than an error.

### Ledger and restoring

`$HOST_RUN_DIR/offsite.state/wal.ledger` and `base.ledger`, appended only after a
successful upload. Both are written by the container as root, so reading them
from the host needs `sudo`.

Restoring needs the age private key from 1Password:

```bash
age -d -i db.age-key -o base.tar.gz base-<id>.tar.gz.age && tar xzf base.tar.gz
for f in wal-*.gz.age; do age -d -i db.age-key "$f" | gunzip > "wals/${f#wal-}"; done
```

Then hand the base backup and the WAL to barman (or postgres directly) as a
normal PITR restore. A decrypted segment must be exactly 16 777 216 bytes — a
cheap sanity check that needs no barman.

## Commands

| Command                      | What it does                                                                           |
| ---------------------------- | -------------------------------------------------------------------------------------- |
| `odoo offsite register`      | Request a customer area, then pick up credentials after approval.                      |
| `odoo offsite filestore`     | Push the filestore to the write-only target. Needs no repository key.                  |
| `odoo offsite db`            | Push base backups + WAL to the write-only target.                                      |
| `odoo offsite wal`           | Push newly archived WAL only. Runs every minute.                                        |
| `odoo offsite backup`        | Run a backup now. Same run as the nightly cron; a quiet no-op without `RUN_OFFSITE=1`. |
| `odoo offsite init`          | Create the repository (the first backup does this anyway).                             |
| `odoo offsite list`          | List snapshots.                                                                        |
| `odoo offsite info`          | Repository stats (size, deduplication).                                                |
| `odoo offsite check`         | Verify integrity by re-reading the data. Takes time and costs traffic.                 |
| `odoo offsite prune`         | Apply retention. Refused against append-only targets, with an explanation.             |
| `odoo offsite restic <args>` | Escape hatch: any `restic` command. `OFFSITE_STREAM=db\|files` picks the repository (default `db`). |

`list`, `info`, `check` and `init` run over both repositories and label which one
they are reporting on.

The nightly run is `OFFSITE_BACKUP_CRON` (default 04:00), deliberately after the
Barman base backup at 02:00 so it picks up the fresh base instead of yesterday's.

## Retention

`OFFSITE_KEEP_DAILY` / `_WEEKLY` / `_MONTHLY` describe what should be kept.

- Against `sftp:` or a path target, the run applies them itself after each backup.
- Against our backup server (append-only) the client cannot — `odoo offsite
prune` says so instead of failing silently. Retention runs on the server, in a
  maintenance window, with a separate access that is not append-only.

This is the point that gets forgotten in append-only setups: without server-side
retention the repository grows without bound — at our volumes in months, not
years.

## Restoring

Two things are needed: the repository address and the passphrase. There is no
separate key file to lose.

```bash
export RESTIC_PASSWORD="<passphrase from 1Password>"
BASE="rest:https://<user>:<password>@10.222.0.106:8000/<area>"

# the database
export RESTIC_REPOSITORY="$BASE/db/"
restic --cacert rest-server.crt snapshots
restic --cacert rest-server.crt restore <snapshot> --target /restore

# the attachments
export RESTIC_REPOSITORY="$BASE/files/"
restic --cacert rest-server.crt restore latest --target /restore
```

Same passphrase for both. Then restore the database from the dump or the Barman
catalog, and put the filestore back into `$ODOO_FILES/filestore/<db>`.

Check the dates of the two snapshots against each other. A filestore much newer
than the database is harmless; a database much newer than the filestore means
attachments are missing for everything created in between.

A backup that has never been restored is not a backup. Plan the rehearsal; do
not wait for the emergency to be the first attempt.

## Keys

| Secret                      | Operational copy                        | Authoritative copy                                     |
| --------------------------- | --------------------------------------- | ------------------------------------------------------ |
| `OFFSITE_PASSPHRASE`        | project settings on the machine (0600)  | 1Password — **without it the backup cannot be opened** |
| `OFFSITE_REST_PASSWORD`     | project settings on the machine         | 1Password (same item)                                  |
| SSH key for `sftp:` targets | `$HOST_RUN_DIR/offsite/id_ed25519`      | access credential only, not a data key                 |
| Server certificate          | `$HOST_RUN_DIR/offsite/rest-server.crt` | public, gets distributed                               |

One passphrase **per project** — a single shared one means one leak opens every
customer. The passphrase has to sit on the source machine because the cron runs
unattended; that is a deliberate, defensible trade-off, since whoever owns the
machine already has the live database. The protection is aimed at the storage
location and at the integrity of the history.

## Troubleshooting

| Symptom                                               | Cause / fix                                                                                                                                         |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OFFSITE_REPO is empty`                               | No target configured. Run `odoo offsite register`.                                                                                                  |
| `OFFSITE_REST_USER is empty`                          | Area credentials missing — the registration never completed.                                                                                        |
| restic refuses the connection / certificate error     | `rest-server.crt` missing or the server certificate changed. Re-run `register`; if the fingerprint really changed, find out why before trusting it. |
| `Enrollment service … is unreachable`                    | The enrollment service is only reachable over the zebroo VPN. Is this machine in a VPN group with the backup server?                                |
| Backup aborts with "no database state in the backup"    | Working as intended. Set `RUN_BARMAN=1`, or use `odoo offsite backup` (pulls a dump itself).                                                        |
| Stale lock after a crash / reboot                     | The run breaks a hanging lock itself before starting. `rest-server` permits lock removal even in append-only mode.                                  |
| Offsite target is a path and the run refuses to start | Parent directory missing — the disk is probably not mounted. Do not "fix" this by creating the directory.                                           |

## Related

Internal documentation on the backup server itself (isolation, the enrollment
service, monitoring, server-side retention, the 1Password vault) lives in Odoo
Knowledge under _Backup Plan → restic-backup — zentraler Backup-Server
(append-only)_.
