"""
ZFS snapshots for Docker postgres volumes.

Supports two setups:
  A) /var/lib/docker/volumes is its own ZFS dataset (e.g. pool/docker/volumes)
  B) /var/lib/docker is a ZFS dataset (e.g. tank1/docker) and volumes/ is
     just a subdirectory — individual volumes are promoted to child datasets
     with explicit mountpoints.

In case B the ZFS dataset name becomes <pool>/<postgresname> and the
mountpoint is set explicitly to /var/lib/docker/volumes/<postgresname>.
"""

import inquirer
import time
import uuid
from .tools import abort
from operator import itemgetter
import subprocess
import arrow
import sys
import shutil
import click
from .tools import __dc
from .tools import search_env_path, __get_postgres_volume_name
from pathlib import Path
from .tools import abort
from .tools import get_volume_fullpath
from .tools import rsync_progress_param

HOWTO_PREPARE = """

Works if /var/lib/docker itself sits on a ZFS dataset.
Individual postgres volumes are promoted to child ZFS datasets
automatically on first snapshot (odoo snapshot save).

No extra preparation needed beyond having /var/lib/docker on ZFS.

"""


def docker_volume_path():
    return "/var/lib/docker/volumes"


try:
    zfs = search_env_path("zfs")
except Exception:
    zfs = None


class NotZFS(Exception):
    def __init__(self, msg, poolname):
        super().__init__(msg)
        self.poolname = poolname


def unify(text):
    while "\t" in text:
        text = text.replace("\t", " ")
    while "  " in text:
        text = text.replace("  ", " ")
    return text


def _is_zfs_path(path):
    """
    path e.g. tankdocker/volumes/postgres1
    """
    try:
        subprocess.check_output(
            ["sudo", zfs, "list", str(path)],
            encoding="utf8",
            stderr=subprocess.DEVNULL,  # ignore output of 'no datasets available'
        ).strip().splitlines()[1:]
        return True
    except subprocess.CalledProcessError:
        return False


def _get_path(config):
    return get_volume_fullpath(__get_postgres_volume_name(config))


CACHE_ZFS_PATH = None


def _get_zfs_mountpoint(zfs_dataset):
    """Return the mountpoint of a ZFS dataset."""
    return subprocess.check_output(
        ["sudo", zfs, "get", "-H", "-o", "value", "mountpoint", zfs_dataset],
        encoding="utf8",
    ).strip()


def _get_zfs_pool_or_zfs_parent(path):
    try:
        findmnt = subprocess.check_output(
            ["findmnt", "--target", path, "--output", "SOURCE"],
            encoding="utf8",
        ).splitlines()
    except subprocess.CalledProcessError:
        raise NotZFS(f"No zfs pool found for {path}", path)
    if not findmnt:
        raise NotZFS(f"No zfs pool found for {path}", path)
    zfspool = findmnt[1].strip()
    return zfspool


def _get_zfs_path(config):
    """
    Takes the postgresname and translates to the ZFS dataset name.

    Handles both setups:
      - /var/lib/docker/volumes is its own ZFS dataset
        → pool/volumes/<postgresname>
      - /var/lib/docker is the ZFS dataset (volumes/ is a plain dir)
        → pool/docker/<postgresname>  (with explicit mountpoint)
    """
    global CACHE_ZFS_PATH
    if CACHE_ZFS_PATH is None:
        PATH = docker_volume_path()
        postgresname = __get_postgres_volume_name(config)
        zfspool = _get_zfs_pool_or_zfs_parent(PATH)

        fstype = subprocess.check_output(
            ["findmnt", "--target", PATH, "--output", "FSTYPE"],
            encoding="utf8",
        ).splitlines()
        if fstype[1].strip() != "zfs":
            abort(f"No zfs pool found for {PATH}")

        CACHE_ZFS_PATH = str(Path(zfspool) / postgresname)
    return CACHE_ZFS_PATH


def _get_next_snapshotpath(config):
    counter = 0
    while True:
        path = _get_zfs_path(config)
        path = str(path) + f".{counter}"
        if not __is_zfs_fs(path):
            break
        counter += 1
    return path


def _get_possible_snapshot_paths(config):
    """
    :param path: root path
    """
    postgresvolume = __get_postgres_volume_name(config)
    base_path = _get_zfs_path(config)
    if not __is_zfs_fs(Path(base_path).parent):
        abort(f"Not a zfs path: {base_path}")
    snaps = [
        x
        for x in subprocess.check_output(
            [zfs, "list", "-t", "snapshot", "-o", "name"], encoding="utf8"
        ).splitlines()[1:]
    ]

    def matches(path):
        return (
            "/" + postgresvolume + "." in path
            or "/" + postgresvolume + "@" in path
        )

    snaps = list(filter(matches, snaps))
    yield from snaps


def __get_snapshots(config):
    path = _get_path(config)
    try:
        return _get_snapshots(config)
    except NotZFS:
        abort(f"Path {path} is not a zfs.")


def _get_snapshots(config):
    def _get_snaps():
        for path in _get_possible_snapshot_paths(config):
            if "@" not in path:
                continue
            snapshotname = unify(path.split(" "))[0]
            creation = unify(
                subprocess.check_output(
                    ["sudo", zfs, "get", "-p", "creation", snapshotname],
                    encoding="utf8",
                )
                .strip()
                .splitlines()[1]
            )
            _, _, timestamp, _ = creation.split(" ")
            timestamp = arrow.get(int(timestamp)).datetime
            info = {}
            info["date"] = timestamp
            info["fullpath"] = snapshotname
            info["name"] = snapshotname.split("@")[1]
            info["path"] = snapshotname.split("/")[-1]
            yield info

    yield from sorted(_get_snaps(), key=lambda x: x["date"], reverse=True)


def __is_zfs_fs(path_zfs):
    path_zfs = str(path_zfs)
    assert " " not in path_zfs
    return _is_zfs_path(path_zfs)


def assert_environment(config):
    pass


def _turn_into_subvolume(config):
    """
    Makes a zfs volume out of a path.
    Sets an explicit mountpoint so it works even when /var/lib/docker/volumes
    is not its own ZFS dataset.
    """
    if config.NAMED_ODOO_POSTGRES_VOLUME:
        abort("Not compatible with NAMED_ODOO_POSTGRES_VOLUME by now.")
    zfs = search_env_path("zfs")
    fullpath = _get_path(config)
    fullpath_zfs = _get_zfs_path(config)
    if __is_zfs_fs(fullpath_zfs):
        # is zfs - do nothing
        return

    filename = fullpath.parent / f".tmp_{uuid.uuid4().hex}"
    if filename.exists():
        raise Exception(f"Path {filename} should not exist.")
    if not fullpath.exists():
        abort(
            f"{fullpath} does not exist. Did you start postgres? (odoo up -d)"
        )

    shutil.move(fullpath, filename)
    try:
        subprocess.check_output(
            [
                "sudo",
                zfs,
                "create",
                "-o",
                f"mountpoint={fullpath}",
                fullpath_zfs,
            ]
        )
        click.secho(
            "\n"
            "!!! WARNING - DO NOT INTERRUPT !!!\n"
            "!!! Files are being copied back - aborting will cause DATA LOSS !!!\n"
            "\n",
            fg="red",
            bold=True,
        )
        click.secho(
            f"Writing back the files to original position: from {filename}/ to {fullpath}/"
        )
        subprocess.check_call(
            [
                "sudo",
                "rsync",
                str(filename) + "/",
                str(fullpath) + "/",
                "-ar",
                rsync_progress_param(),
            ]
        )
    finally:
        subprocess.check_call(["sudo", "rm", "-Rf", filename])


def make_snapshot(ctx, config, name):
    zfs = search_env_path("zfs")
    __dc(config, ["stop", "-t", "0"] + ["postgres"])
    _turn_into_subvolume(config)
    snapshots = list(_get_snapshots(config))
    snapshot = list(filter(lambda x: x["name"] == name, snapshots))
    if snapshot:
        if not config.force:
            answer = inquirer.prompt(
                [
                    inquirer.Confirm(
                        "continue",
                        message=("Snapshot already exists - overwrite?"),
                    )
                ]
            )
            if not answer["continue"]:
                sys.exit(-1)
        subprocess.check_call(
            ["sudo", zfs, "destroy", snapshot[0]["fullpath"]]
        )

    assert " " not in name
    fullpath = _get_zfs_path(config) + "@" + name
    subprocess.check_call(["sudo", zfs, "snapshot", fullpath])
    __dc(config, ["up", "-d"] + ["postgres"])
    return name


def remount(config):
    zfs_full_path = _get_zfs_path(config)
    zfs = search_env_path("zfs")
    subprocess.check_call(
        ["sudo", zfs, "mount", zfs_full_path],
    )


def _try_umount(config):
    zfs_full_path = _get_zfs_path(config)
    umount = search_env_path("umount")
    try:
        subprocess.check_call(
            ["sudo", umount, zfs_full_path],
        )
    except subprocess.CalledProcessError:
        click.secho(
            f"Could not umount {zfs_full_path}. Perhaps not a problem.",
            fg="yellow",
        )


def restore(ctx, config, name):
    zfs = search_env_path("zfs")
    if not name:
        return

    assert "@" not in name
    assert "/" not in name

    snapshots = list(_get_snapshots(config))
    snapshot = list(filter(lambda x: x["name"] == name, snapshots))
    if not snapshot:
        abort(f"Snapshot {name} does not exist.")
    snapshot = snapshot[0]
    zfs_full_path = _get_zfs_path(config)
    snapshots_of_volume = [
        x
        for x in snapshots
        if x["fullpath"].split("@")[0].startswith(zfs_full_path)
    ]
    try:
        index = list(map(lambda x: x["name"], snapshots_of_volume)).index(name)
    except ValueError:
        index = -1

    __dc(config, ["stop", "-t", "1"] + ["postgres"])
    full_next_path = _get_next_snapshotpath(config)
    disk_path = _get_path(config)
    _try_umount(config)
    if _is_zfs_path(zfs_full_path):
        subprocess.check_call(
            ["sudo", zfs, "rename", zfs_full_path, full_next_path]
        )
        # prevent renamed dataset from claiming the same mountpoint
        subprocess.check_call(
            ["sudo", zfs, "set", "canmount=noauto", full_next_path]
        )
    snap_name = snapshot["fullpath"].split("@")[-1]
    snapshot_path = _get_zfs_path_for_snap_name(config, snap_name)
    __dc(config, ["rm", "-f"] + ["postgres"])
    cmd = [
        "sudo",
        zfs,
        "clone",
        "-o",
        f"mountpoint={disk_path}",
        snapshot_path,
        zfs_full_path,
    ]
    subprocess.check_call(cmd)
    click.secho(f"Restore command:")
    click.secho(" ".join(map(str, cmd)), fg="yellow")
    __dc(config, ["up", "-d"] + ["postgres"])


def _get_zfs_path_for_snap_name(config, snap_name):
    for path in _get_possible_snapshot_paths(config):
        if path.split("@")[-1] == snap_name:
            return path
    abort(f"Could not find snapshot with name {snap_name}")


def remove(config, snapshot):
    zfs = search_env_path("zfs")
    snapshots = __get_snapshots(config)
    if isinstance(snapshot, str):
        snapshots = [x for x in snapshots if x["name"] == snapshot]
        if not snapshots:
            click.secho(f"Snapshot {snapshot} not found!", fg="red")
            sys.exit(-1)
        snapshot = snapshots[0]
    if snapshot["fullpath"] in map(itemgetter("fullpath"), snapshots):
        _try_umount(config)
        subprocess.check_call(
            ["sudo", zfs, "destroy", "-R", snapshot["fullpath"]]
        )
        remount(config)


def remove_volume(config):
    zfs = search_env_path("zfs")
    umount = search_env_path("umount")
    for path in _get_possible_snapshot_paths(config):
        try:
            subprocess.check_call(
                ["sudo", zfs, "set", "canmount=noauto", path]
            )
        except subprocess.CalledProcessError:
            click.secho(
                "Failed to execute canmount=noauto, but perhaps not a problem. Trying to continue.",
                fg="yellow",
            )
        try:
            subprocess.check_call(["sudo", umount, path])
        except subprocess.CalledProcessError:
            pass

        fullpath = (
            translate_poolPath_to_fullPath(Path(path).parent) / Path(path).name
        )
        if fullpath.exists() or "@" in str(fullpath):
            try:
                subprocess.check_call(
                    ["sudo", zfs, "destroy", "-R", path],
                    encoding="utf8",
                    stderr=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                )
            except subprocess.CalledProcessError:
                click.secho(
                    f"Failed to destroy zfs dataset at {path}.", fg="red"
                )
                time.sleep(1)
            click.secho(f"Removed: {path}", fg="yellow")
        else:
            click.secho(f"{path} did not exist and so wasn't removed.")
    clear_all(config)


def translate_poolPath_to_fullPath(zfs_path):
    zfs_path = Path(zfs_path)
    removed = []
    while len(zfs_path.parts) >= 1:
        mountpoint = None
        try:
            mountpoint = subprocess.check_output(
                [
                    "sudo",
                    zfs,
                    "get",
                    "mountpoint",
                    "-H",
                    "-o",
                    "value",
                    zfs_path,
                ],
                encoding="utf8",
            ).strip()
        except subprocess.CalledProcessError:
            mountpoint = None
        if mountpoint != "-":
            break
        removed.insert(0, zfs_path.parts[-1])
        zfs_path = Path("/".join(zfs_path.parts[:-1]))
    mountpoint = Path(mountpoint) / "/".join(removed) if mountpoint else None

    return Path(mountpoint) if mountpoint else None


def clear_all(config):
    zfs = search_env_path("zfs")
    zfs_full_path = _get_zfs_path(config)
    _try_umount(config)
    diskpath = translate_poolPath_to_fullPath(zfs_full_path)
    if diskpath and __is_zfs_fs(diskpath):
        subprocess.check_call(["sudo", zfs, "destroy", "-r", zfs_full_path])
