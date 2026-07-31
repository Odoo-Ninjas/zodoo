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


def _store_fnames(config, dbname):
    conn = config.get_odoo_conn().clone(dbname=dbname)
    if not table_exists(conn, "ir_attachment"):
        return None
    rows = _execute_sql(
        conn,
        "select distinct store_fname from ir_attachment "
        "where store_fname is not null",
        fetchall=True,
    )
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
    help="Unshare every symlinked database, not only this project's.",
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
        store_fnames = _store_fnames(config, entry.name)
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
