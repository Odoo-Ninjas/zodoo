# Attachment filestore on multi-instance hosts

On a branch/CI host the same production dump is restored into many instances,
and an Odoo filestore easily reaches tens of gigabytes. zodoo can therefore
keep **one shared pool** of attachment files per host instead of one copy per
instance.

The whole topic has exactly one rule worth memorising:

> Share the **content** via hardlinks. Never share the **directory** via a
> symlink.

## How the pool works

With `ODOO_FILES_COMMON=1` zodoo maintains `<filestore>/_common` next to the
per-database directories:

```
~/.odoo/files/filestore/
├── _common/                 <- the pool: one inode per distinct file
├── mydb/                    <- real directory, hardlinks into _common
└── otherdb/                 <- real directory, hardlinks into _common
```

Two properties make this safe and cheap:

- **Filestore names are the SHA1 of the content.** Equal name means equal
  content, so deduplicating by name cannot mix up data, and Odoo never
  rewrites an existing file in place.
- **A hardlink is not a copy.** The content exists once; each instance holds
  its own reference. Deleting one reference only decrements the link count —
  the data survives as long as any other instance still points at it.

So the pool gives the space saving of sharing while each database keeps its
own directory.

## Why symlinks destroy data

Historically the sharing was implemented by replacing every per-database
directory with a symlink: `filestore/<db> -> filestore/_common`. It saves the
same space, and it silently eats attachments.

`ir.attachment._gc_file_store()` walks `<filestore>/checklist`, looks up every
hash it finds there in **its own** `ir_attachment` table, and unlinks every
file it cannot account for. Odoo drops a marker into `checklist` for each
attachment it writes. With a symlinked filestore that `checklist` is one
shared directory, so the markers of _all_ instances land in it — and the
nightly autovacuum of a single database deletes the freshly written
attachments of every other instance.

On a CI host this runs constantly, because instances are created and destroyed
all the time. Typical symptoms:

- missing images, and `FileNotFoundError` for filestore paths in the log
- HTTP 500 on `/web/assets/...` bundles — which makes **login impossible**,
  because the login page needs its JS
- the damage appears in instances nobody touched

`checklist` itself must therefore stay private per database. A
`filestore/checklist -> _common` symlink is part of the same defect, not a
harmless leftover.

## Commands

```bash
odoo filestore dedup          # hardlink per-database filestores into _common
odoo filestore unshare        # replace legacy <db> -> _common symlinks
odoo filestore unshare --all  # ... for every symlinked db this postgres serves
```

`dedup` walks each real per-database directory and replaces duplicate content
with a hardlink into the pool. It skips directories that are still symlinks
and tells you to run `unshare` first. The replacement goes through
`os.replace()` on a temporary link, so a concurrently running Odoo never sees
a missing file.

`unshare` is database-driven: it reads `ir_attachment.store_fname`, turns the
symlink into a real directory and materialises exactly the referenced files
back out of the pool as hardlinks. It needs no additional disk space. If the
database is unreachable or has no `ir_attachment` table, the symlink is left
alone rather than emptied.

`--all` only reaches databases served by _this_ project's postgres. Where each
instance runs its own postgres container — the normal case on a CI host — run
the command once per project; unreachable databases are reported and skipped.

## Recommended lifecycle

1. Set `ODOO_FILES_COMMON=1` on hosts that carry several instances of the same
   dump.
2. After every restore or instance creation, run `odoo filestore dedup`.
3. Never create `<db> -> _common` symlinks. Convert existing ones with
   `odoo filestore unshare`.
4. When destroying an instance, delete its filestore directory with it. The
   pool keeps the content for the remaining instances.

## Repairing a broken per-instance directory

**Hard requirement: an instance must never be without its filestore, not even
briefly.** Users are working on these instances, and a filestore that is
missing for a few seconds looks exactly like a broken system — HTTP 500 on the
asset bundles, no login. Every repair therefore has to be _additive_: create
the missing hardlink, never move, replace or rebuild a directory that an
instance is currently serving from. `dedup` obeys this by construction
(`os.replace()` on a temporary link is atomic); a plain `ln` of a missing path
obeys it trivially. `unshare` is the one command that genuinely rebuilds a
directory — run it while the instance is down, or accept that it materialises
into a fresh directory before swapping.

There is a gap between the two commands. `unshare` fixes symlinks; `dedup`
fixes duplicates. Neither fixes the state you are left with **after** a shared
GC has struck: a real per-database directory whose referenced files are gone
while the pool still has them.

Check it per instance — this is also the query worth putting on a dashboard:

```sql
select count(*) from ir_attachment
 where store_fname is not null and store_fname <> '';
```

Compare that against the files actually present under
`<filestore>/<db>/`. For a repair, take every `store_fname` from the database,
and for each one that is missing on disk but present in `_common`, create the
hardlink:

```bash
ln "<filestore>/_common/$sf" "<filestore>/<db>/$sf"
```

Files that are in neither place are lost. If the instances are copies of a
production system, the authoritative filestore is production's — mirroring it
into the pool first closes most of the gap, and because the names are content
hashes, only genuinely missing files travel:

```bash
rsync -a --ignore-existing prod:.odoo/files/filestore/<proddb>/ \
      ~/.odoo/files/filestore/_common/
```

`--ignore-existing` is essential: without it rsync replaces existing files and
thereby breaks the hardlinks into every instance directory.

### Field report

On a customer CI host (about 20 instances of one Odoo database), the
per-instance directories had lost 212k, 206k, 9.5k and 3.7k referenced files.
The pool was practically intact — mirroring production added only 865 files
(81 MB out of 76 GB), and everything else was repaired by relinking, with no
additional disk space. That is the signature of this defect: the content
survives in `_common`, the per-instance view is what gets destroyed.

## Operational consequences

- **Backups must preserve hardlinks.** Use `rsync -H` or a `tar` that detects
  them; otherwise the backup inflates to the sum of all instances. ZFS
  snapshots and `zfs send` are block-based and unaffected.
- **`du` overstates.** The sum of the per-instance directories is far larger
  than the space actually used. For capacity questions use `df` or
  `zfs list`.
- **Restores land outside the pool.** A freshly restored instance carries full
  copies until `dedup` runs, so plan for the peak or dedup right away.
