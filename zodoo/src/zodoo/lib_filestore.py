"""
Shared ("common") attachment filestore.

With ``ODOO_FILES_COMMON=1`` all instances on a host share one pool of
attachment files. That is worth a lot on branch/CI hosts: the same production
dump is restored into many instances and a filestore easily reaches tens of
gigabytes.

Historically the sharing was implemented by replacing every per-database
directory ``filestore/<db>`` with a *symlink* to ``filestore/_common``. It
saves the space - but it also shares Odoo's garbage-collection bookkeeping,
and that silently destroys data:

``ir.attachment._gc_file_store()`` walks ``<filestore>/checklist``, looks the
hashes found there up in *its own* ``ir_attachment`` table and ``os.unlink()``s
every file it cannot find. Odoo puts a marker into ``checklist`` for each
attachment it writes. With a symlinked filestore that checklist is one shared
directory, so the markers of *all* instances end up in it - and the nightly
autovacuum of a single database deletes the freshly written attachments of
every other instance. Symptoms: missing images, HTTP 500 on ``/web/assets/...``
bundles (which makes login impossible, the login page needs its JS), and
``FileNotFoundError`` for filestore paths in the log.

Hardlinks give the same space saving without the shared fate:

* every database keeps its own directory, hence its own ``checklist``
* the file content exists exactly once on disk (one inode, many links)
* a GC run only drops that instance's own link; the data survives as long as
  any other instance still references it

Filestore file names are the SHA1 of the content, so deduplicating by name is
safe: equal name means equal content.
"""

import contextlib
import os
from pathlib import Path

import click

from .cli import cli, pass_config
from .lib_clickhelpers import AliasedGroup
from .tools import _execute_sql, table_exists

COMMON_DIR_NAME = "_common"

# Odoo's GC bookkeeping directory. Must stay private per database, it is the
# whole point of this module.
CHECKLIST_DIR = "checklist"


def _iter_files(directory):
    for dirpath, _, filenames in os.walk(directory):
        for filename in filenames:
            yield Path(dirpath) / filename


def _relative_is_checklist(relative_path):
    parts = relative_path.parts
    return bool(parts) and parts[0] == CHECKLIST_DIR


def _replace_by_link_to(path, target):
    """Point ``path`` at ``target``'s inode without ever unlinking ``path``.

    Links ``target`` to a temporary name next to ``path`` and renames it over
    ``path``. ``os.replace`` is atomic, so a concurrently running Odoo never
    sees a missing file.
    """
    tmp = path.parent / f".{path.name}.zodoo-dedup-tmp"
    with contextlib.suppress(FileNotFoundError):
        tmp.unlink()
    os.link(target, tmp)
    try:
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise


def dedupe_into_common(db_dir, common_dir):
    """Hardlink the files of ``db_dir`` into the pool ``common_dir``.

    Returns a stats dict. Idempotent - files that already share their inode
    with the pool are skipped by a single ``stat``, so repeated runs are cheap.
    """
    stats = {"adopted": 0, "linked": 0, "shared": 0, "failed": 0}
    common_dir.mkdir(parents=True, exist_ok=True)

    for path in _iter_files(db_dir):
        relative_path = path.relative_to(db_dir)
        if _relative_is_checklist(relative_path):
            continue
        target = common_dir / relative_path
        try:
            source_stat = path.stat()
            if source_stat.st_nlink > 1 and target.exists():
                if target.stat().st_ino == source_stat.st_ino:
                    stats["shared"] += 1
                    continue
            if target.exists():
                _replace_by_link_to(path, target)
                stats["linked"] += 1
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.link(path, target)
                stats["adopted"] += 1
        except OSError as ex:
            # Cross-device pool, link count exhausted, file vanished
            # mid-walk - never fatal, the instance keeps its own copy.
            stats["failed"] += 1
            click.secho(f"filestore dedup skipped {path}: {ex}", fg="yellow")

    return stats


def heal_from_common(db_dir, common_dir, store_fnames):
    """Link referenced files that are missing in ``db_dir`` back out of the pool.

    This is the counterpart of :func:`dedupe_into_common` and closes the gap
    the other two operations leave open: ``unshare`` repairs symlinks,
    ``dedupe_into_common`` removes duplicates, but a *real* per-database
    directory whose files a shared garbage collection already deleted is
    healed by neither.

    Strictly additive. It only ever creates a directory entry for a file that
    is missing - it never moves, replaces or rebuilds anything. An instance
    that is currently serving from ``db_dir`` is therefore not even briefly
    without its filestore, which is the whole point: on a staging host people
    are working while this runs, and a filestore that is gone for a second
    looks exactly like a broken system (HTTP 500 on the asset bundles, hence
    no login).

    Needs no additional disk space, and no restart - Odoo reads the filestore
    from disk on every access.
    """
    stats = {"linked": 0, "present": 0, "lost": 0, "failed": 0}

    for store_fname in store_fnames:
        if not store_fname:
            continue
        relative_path = Path(store_fname)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            continue
        target = db_dir / relative_path
        if target.exists():
            stats["present"] += 1
            continue
        source = common_dir / relative_path
        if not source.exists():
            # Gone from both the instance and the pool: lost before this run.
            stats["lost"] += 1
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target)
            stats["linked"] += 1
        except FileExistsError:
            # Odoo wrote it itself in the meantime - fine either way.
            stats["present"] += 1
        except OSError as ex:
            stats["failed"] += 1
            click.secho(f"filestore heal skipped {target}: {ex}", fg="yellow")

    return stats


def materialize_from_common(db_dir, common_dir, store_fnames):
    """Turn a legacy ``<db> -> _common`` symlink into a real directory.

    Builds the replacement next to it and swaps it in, so a failure leaves the
    old symlink in place. Only the files the database actually references are
    linked, which is what makes this cheap: no data is copied, only directory
    entries are created.
    """
    if not db_dir.is_symlink():
        raise ValueError(f"{db_dir} is not a symlink; nothing to unshare")

    staging = db_dir.parent / f".{db_dir.name}.zodoo-unshare"
    if staging.exists():
        raise RuntimeError(
            f"{staging} already exists - a previous run was interrupted. "
            "Remove it and retry."
        )
    staging.mkdir(parents=True)
    (staging / CHECKLIST_DIR).mkdir()

    stats = {"linked": 0, "missing": 0, "failed": 0}
    for store_fname in store_fnames:
        if not store_fname:
            continue
        relative_path = Path(store_fname)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            continue
        source = common_dir / relative_path
        if not source.exists():
            stats["missing"] += 1
            continue
        target = staging / relative_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target)
            stats["linked"] += 1
        except OSError as ex:
            stats["failed"] += 1
            click.secho(f"could not link {source}: {ex}", fg="yellow")

    # rename(2) refuses to replace a symlink by a directory, so drop the
    # symlink first. Window is a single syscall wide.
    db_dir.unlink()
    staging.rename(db_dir)
    return stats


def _filestore_dir(config):
    odoo_files = config.ODOO_FILES
    if not odoo_files:
        return None
    return Path(odoo_files) / "filestore"


class DatabaseUnreachable(Exception):
    """The database of a symlinked filestore cannot be queried right now."""


def _store_fnames(config, dbname):
    """Distinct store_fname values of ``dbname``, or None if it has no
    ir_attachment table (empty / never initialized database).

    Raises :class:`DatabaseUnreachable` when the postgres server itself
    cannot be reached - on hosts where every instance runs its own postgres
    container, the connection parameters of the current project only reach
    that project's database.
    """
    import psycopg2

    conn = config.get_odoo_conn().clone(dbname=dbname)
    try:
        if not table_exists(conn, "ir_attachment"):
            return None
        rows = _execute_sql(
            conn,
            "select distinct store_fname from ir_attachment "
            "where store_fname is not null",
            fetchall=True,
        )
    except psycopg2.OperationalError as ex:
        raise DatabaseUnreachable(str(ex).strip()) from ex
    return [row[0] for row in rows or []]


@cli.group(cls=AliasedGroup)
def filestore():
    """Attachment filestore maintenance (shared/common filestore)."""


@filestore.command(
    name="dedup",
    help="Hardlink per-database filestores into the shared _common pool.",
)
@pass_config
def dedup(config):
    files_dir = _filestore_dir(config)
    if not files_dir or not files_dir.exists():
        click.secho(f"No filestore at {files_dir}", fg="red")
        return
    common_dir = files_dir / COMMON_DIR_NAME

    for entry in sorted(files_dir.iterdir()):
        if entry.name == COMMON_DIR_NAME or not entry.is_dir():
            continue
        if entry.is_symlink():
            click.secho(
                f"{entry.name}: still a symlink to {COMMON_DIR_NAME} - "
                "run `odoo filestore unshare` first.",
                fg="yellow",
            )
            continue
        stats = dedupe_into_common(entry, common_dir)
        click.secho(
            f"{entry.name}: {stats['adopted']} adopted, "
            f"{stats['linked']} linked, {stats['shared']} already shared, "
            f"{stats['failed']} skipped",
            fg="green",
        )


@filestore.command(
    name="unshare",
    help=(
        "Replace legacy `<db> -> _common` filestore symlinks by real "
        "directories of hardlinks, so each database gets its own GC "
        "checklist again. Uses no additional disk space."
    ),
)
@click.option(
    "-a",
    "--all",
    "all_dbs",
    is_flag=True,
    help=(
        "Unshare every symlinked database, not only this project's. Only "
        "reaches databases served by this project's postgres - where each "
        "instance runs its own postgres container, run the command once per "
        "project instead; unreachable databases are reported and skipped."
    ),
)
@pass_config
def unshare(config, all_dbs):
    files_dir = _filestore_dir(config)
    if not files_dir or not files_dir.exists():
        click.secho(f"No filestore at {files_dir}", fg="red")
        return
    common_dir = files_dir / COMMON_DIR_NAME
    if not common_dir.is_dir():
        click.secho(f"No shared pool at {common_dir}; nothing to do.")
        return

    if all_dbs:
        candidates = [
            entry
            for entry in sorted(files_dir.iterdir())
            if entry.name != COMMON_DIR_NAME and entry.is_symlink()
        ]
    else:
        candidates = [files_dir / config.dbname]

    for entry in candidates:
        if not entry.is_symlink():
            click.secho(f"{entry.name}: not a symlink, skipping.")
            continue
        try:
            store_fnames = _store_fnames(config, entry.name)
        except DatabaseUnreachable as ex:
            click.secho(
                f"{entry.name}: database not reachable ({ex}) - leaving the "
                "symlink alone. Start the instance, or run the command from "
                "that project.",
                fg="yellow",
            )
            continue
        if store_fnames is None:
            click.secho(
                f"{entry.name}: no ir_attachment table (database missing or "
                "not initialized) - leaving the symlink alone.",
                fg="yellow",
            )
            continue
        stats = materialize_from_common(entry, common_dir, store_fnames)
        click.secho(
            f"{entry.name}: {stats['linked']} files linked, "
            f"{stats['missing']} referenced but absent from the pool, "
            f"{stats['failed']} failed",
            fg="green",
        )
        if stats["missing"]:
            click.secho(
                f"{entry.name}: {stats['missing']} attachments have no file "
                "left in the pool - those were already lost before this run "
                "(see the module docstring) and need a restore to come back.",
                fg="yellow",
            )


@contextlib.contextmanager
def _exclusive_lock(files_dir):
    """Serialise pool-wide runs against each other.

    ``flock`` is held by the file descriptor, so the kernel releases it when
    the process dies - no stale lock file can ever block the next run, which
    is exactly the failure mode a PID file has.
    """
    import fcntl

    lock_path = files_dir / ".zodoo-filestore.lock"
    with open(lock_path, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            click.secho(
                f"Another filestore run holds {lock_path} - skipping.",
                fg="yellow",
            )
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def pull_from_upstream(upstream, common_dir, bwlimit=None, dry_run=False):
    """Mirror missing attachment files from an upstream filestore into the pool.

    ``upstream`` is an rsync source, usually the filestore directory of the
    production system the instances are copies of, e.g.
    ``odoo_cust@10.0.0.5:.odoo/files/filestore/proddb``.

    Because filestore names are content hashes, ``--ignore-existing`` makes
    this cheap: only genuinely missing files travel, and an unchanged pool
    transfers nothing. That flag is also *mandatory* for correctness - without
    it rsync replaces existing files and thereby breaks the hardlinks into
    every instance directory.

    Read-only on the upstream side, and deliberately gentle: production is
    usually in use while this runs.
    """
    import subprocess

    common_dir.mkdir(parents=True, exist_ok=True)
    source = upstream if upstream.endswith("/") else f"{upstream}/"
    cmd = [
        "rsync",
        "-a",
        "--ignore-existing",
        "--stats",
        "--rsync-path=ionice -c3 nice -n10 rsync",
    ]
    if bwlimit:
        cmd.append(f"--bwlimit={bwlimit}")
    if dry_run:
        cmd.append("--dry-run")
    cmd += [source, f"{common_dir}/"]

    click.secho(f"filestore pull: {source} -> {common_dir}", fg="green")
    subprocess.check_call(cmd)


def _pool_and_db_dir(config):
    files_dir = _filestore_dir(config)
    if not files_dir or not files_dir.exists():
        click.secho(f"No filestore at {files_dir}", fg="red")
        return None, None, None
    common_dir = files_dir / COMMON_DIR_NAME
    return files_dir, common_dir, files_dir / config.dbname


@filestore.command(
    name="sync",
    help=(
        "One additive pass for this project: optionally pull missing files "
        "from FILESTORE_UPSTREAM into the pool, link back what the database "
        "references but the instance is missing, then dedup into the pool."
    ),
)
@click.option(
    "--heal/--no-heal", default=True, help="Link missing files back."
)
@click.option(
    "--dedup/--no-dedup", default=True, help="Hardlink into the pool."
)
@click.option(
    "--pull",
    is_flag=True,
    help=(
        "Mirror FILESTORE_UPSTREAM into the pool first. Off by default: it "
        "talks to another machine, and on a dev host that carries instances "
        "of many different production systems you rarely want that "
        "unattended."
    ),
)
@click.option("--dry-run", is_flag=True, help="Only report, change nothing.")
@pass_config
def sync(config, heal, dedup, pull, dry_run):
    files_dir, common_dir, db_dir = _pool_and_db_dir(config)
    if not files_dir:
        return

    with _exclusive_lock(files_dir) as acquired:
        if not acquired:
            return

        if pull:
            upstream = getattr(config, "FILESTORE_UPSTREAM", None)
            if not upstream:
                click.secho(
                    "--pull given but FILESTORE_UPSTREAM is not set. It is a "
                    "per-project setting on purpose: every project has its "
                    "own production system.",
                    fg="red",
                )
                return
            pull_from_upstream(
                upstream,
                common_dir,
                bwlimit=getattr(config, "FILESTORE_UPSTREAM_BWLIMIT", None),
                dry_run=dry_run,
            )

        if heal:
            if db_dir.is_symlink():
                click.secho(
                    f"{db_dir.name}: still a symlink to {COMMON_DIR_NAME} - "
                    "run `odoo filestore unshare` first.",
                    fg="yellow",
                )
            elif not db_dir.exists():
                click.secho(f"{db_dir.name}: no filestore directory yet.")
            elif not common_dir.is_dir():
                click.secho(
                    f"No shared pool at {common_dir}; nothing to heal."
                )
            else:
                try:
                    store_fnames = _store_fnames(config, config.dbname)
                except DatabaseUnreachable as ex:
                    click.secho(
                        f"{db_dir.name}: database not reachable ({ex}) - "
                        "healing needs it, start the instance and retry.",
                        fg="yellow",
                    )
                    store_fnames = []
                if store_fnames is None:
                    click.secho(
                        f"{db_dir.name}: no ir_attachment table - nothing to "
                        "heal."
                    )
                elif store_fnames:
                    stats = _heal_or_report(
                        db_dir, common_dir, store_fnames, dry_run
                    )
                    click.secho(
                        f"{db_dir.name}: {stats['linked']} linked back, "
                        f"{stats['present']} already there, "
                        f"{stats['lost']} lost, {stats['failed']} failed",
                        fg="green",
                    )
                    if stats["lost"]:
                        click.secho(
                            f"{db_dir.name}: {stats['lost']} attachments have "
                            "no file left in the pool either. Those are gone; "
                            "if the instance is a copy of a production "
                            "system, `--pull` fetches them.",
                            fg="yellow",
                        )

        if (
            dedup
            and not dry_run
            and db_dir.exists()
            and not db_dir.is_symlink()
        ):
            stats = dedupe_into_common(db_dir, common_dir)
            click.secho(
                f"{db_dir.name}: {stats['adopted']} adopted, "
                f"{stats['linked']} linked, {stats['shared']} already shared, "
                f"{stats['failed']} skipped",
                fg="green",
            )


def _heal_or_report(db_dir, common_dir, store_fnames, dry_run):
    if not dry_run:
        return heal_from_common(db_dir, common_dir, store_fnames)

    stats = {"linked": 0, "present": 0, "lost": 0, "failed": 0}
    for store_fname in store_fnames:
        if not store_fname:
            continue
        relative_path = Path(store_fname)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            continue
        if (db_dir / relative_path).exists():
            stats["present"] += 1
        elif (common_dir / relative_path).exists():
            stats["linked"] += 1
        else:
            stats["lost"] += 1
    return stats


CRON_MARKER = "# zodoo filestore dedup"


@filestore.command(
    name="install-cron",
    help=(
        "Install a nightly host-side `filestore dedup` in the user's crontab. "
        "The pool belongs to the filestore root, not to a single project, so "
        "one entry per root is enough - not one per instance."
    ),
)
@click.option("--at", "at_time", default="03:30", help="HH:MM, default 03:30.")
@click.option("--remove", is_flag=True, help="Remove the entry again.")
@pass_config
def install_cron(config, at_time, remove):
    import shutil
    import subprocess
    import sys

    files_dir = _filestore_dir(config)
    if not files_dir:
        click.secho("No filestore configured.", fg="red")
        return

    try:
        hour, minute = (int(part) for part in at_time.split(":", 1))
    except ValueError:
        click.secho(f"--at expects HH:MM, got {at_time!r}", fg="red")
        return

    odoo_bin = shutil.which("odoo") or sys.argv[0]
    marker = f"{CRON_MARKER} ({files_dir})"
    # Dedup needs no database, so it is safe to run unattended for the whole
    # root. Healing does need one and therefore stays with the instance.
    line = (
        f"{minute} {hour} * * * ionice -c3 nice -n10 "
        f"{odoo_bin} -p {config.project_name} filestore dedup "
        f">> {files_dir.parent}/filestore-dedup.log 2>&1  {marker}"
    )

    current = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    ).stdout
    kept = [
        existing for existing in current.splitlines() if marker not in existing
    ]
    if not remove:
        kept.append(line)
    new = "\n".join(kept).strip() + "\n"

    subprocess.run(["crontab", "-"], input=new, text=True, check=True)
    click.secho(
        f"crontab entry {'removed' if remove else 'installed'} for {files_dir}",
        fg="green",
    )
