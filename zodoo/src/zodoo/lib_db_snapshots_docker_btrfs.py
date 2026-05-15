from operator import itemgetter
import subprocess
import uuid
import arrow
import sys
import shutil
import click
from .tools import __dc
from .tools import search_env_path, __get_postgres_volume_name
from .tools import run_root_cmd
from pathlib import Path
from .tools import get_volume_fullpath, get_docker_volumes
from .tools import rsync_progress_param

SNAPSHOT_DIR = get_docker_volumes() / "subvolumes"


def _get_path(config):
    return get_volume_fullpath(__get_postgres_volume_name(config))


def _get_cmd_butter_volume():
    """Return the un-escalated btrfs subvolume base command.

    Callers wrap this via :func:`run_root_cmd` which handles the
    direct → docker → sudo escalation chain itself.
    """
    return [search_env_path("btrfs"), "subvolume"]


def __assert_btrfs(config):
    # TODO check if volumes of docker is in a subvolume
    pass


def _get_subvolume_dir(config):
    subvolume_dir = SNAPSHOT_DIR / __get_postgres_volume_name(config)
    if not subvolume_dir.exists():
        run_root_cmd(["mkdir", "-p", subvolume_dir])
    return subvolume_dir


def _get_btrfs_infos(path):
    info = {}
    out = run_root_cmd(
        [search_env_path("btrfs"), "subvol", "show", str(path)],
        capture=True,
    )
    for line in out.decode("utf-8").split("\n"):
        if "Creation time:" in line:
            line = line.split(":", 1)[1].strip()
            line = " ".join(line.split(" ")[:2])
            info["date"] = arrow.get(line).datetime
    return info


def __get_snapshots(config):
    files = list(_get_subvolume_dir(config).glob("*"))
    snapshots = list(
        {
            "path": str(x),
            "name": x.name,
            "date": _get_btrfs_infos(x)["date"],
        }
        for x in reversed(files)
    )
    return snapshots


def assert_environment(config):
    __assert_btrfs(config)


def _turn_into_subvolume(path):
    """
    Makes a subvolume out of a path. Docker restart required?
    """
    btrfs = search_env_path("btrfs")
    try:
        run_root_cmd(
            [btrfs, "subvolume", "show", path],
            capture=True,
        )
        return
    except subprocess.CalledProcessError as ex:
        err_msg = (ex.stderr or b"").decode("utf-8", errors="replace").lower()
        if not any(
            x.lower() in err_msg
            for x in ["Not a Btrfs subvolume", "not a subvolume"]
        ):
            raise Exception("Unexpected error at turning into subvolume")
    click.secho(f"Turning {path} into a subvolume.")
    filename = path.parent / f".tmp_{uuid.uuid4().hex}"
    if filename.exists():
        raise Exception(f"Path {filename} should not exist.")
    shutil.move(path, filename)
    try:
        run_root_cmd([btrfs, "subvolume", "create", path])
        click.secho(
            f"Writing back the files to original position: from {filename}/ to {path}/"
        )
        run_root_cmd(
            [
                "rsync",
                str(filename) + "/",
                str(path) + "/",
                "-ar",
                rsync_progress_param(),
            ]
        )
    finally:
        run_root_cmd(["rm", "-Rf", filename])


def make_snapshot(ctx, config, name):
    __dc(config, ["stop", "-t", "1"] + ["postgres"])
    path = _get_subvolume_dir(config)
    _turn_into_subvolume(_get_path(config))

    # check if name already exists, and if so abort
    dest_path = path / name
    if dest_path.exists():
        if config.force:
            remove(config, name)
        else:
            click.secho(f"Path {dest_path} already exists.", fg="red")
            sys.exit(-1)

    run_root_cmd(
        _get_cmd_butter_volume()
        + [
            "snapshot",
            "-r",  # readonly
            str(_get_path(config)),
            str(dest_path),
        ],
        capture=True,
    )
    __dc(config, ["up", "-d"] + ["postgres"])
    return name


def restore(ctx, config, name):
    if not name:
        return

    if "/" not in str(name):
        name = _get_subvolume_dir(config) / name

    name = Path(name)
    if not name.exists():
        click.secho(f"Path {name} does not exist.", fg="red")
        sys.exit(-1)

    __dc(config, ["stop", "-t", "1"] + ["postgres"])
    volume_path = _get_path(config)
    if volume_path.exists():
        run_root_cmd(_get_cmd_butter_volume() + ["delete", volume_path])
    run_root_cmd(
        _get_cmd_butter_volume() + ["snapshot", name, str(volume_path)]
    )

    __dc(config, ["rm", "-f"] + ["postgres"])
    __dc(config, ["up", "-d"] + ["postgres"])


def remove(config, snapshot):
    snapshots = __get_snapshots(config)
    if isinstance(snapshot, str):
        snapshots = [x for x in snapshots if x["name"] == snapshot]
        if not snapshots:
            click.secho(f"Snapshot {snapshot} not found!", fg="red")
            sys.exit(-1)
        snapshot = snapshots[0]
    if snapshot["path"] in map(itemgetter("path"), snapshots):
        run_root_cmd(
            _get_cmd_butter_volume() + ["delete", str(snapshot["path"])]
        )


def purge_inactive(config):
    for vol in SNAPSHOT_DIR.glob("*"):
        if not vol.is_dir():
            continue
        try:
            next(get_docker_volumes().glob(vol.name))
        except StopIteration:
            for snapshot in vol.glob("*"):
                click.secho(f"Deleting snapshot {snapshot}", fg="red")
                run_root_cmd(["btrfs", "subvolume", "delete", str(snapshot)])
            click.secho(f"Deleting {vol}", fg="red")
            shutil.rmtree(vol)
