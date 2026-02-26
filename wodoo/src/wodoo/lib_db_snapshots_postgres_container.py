import subprocess
from datetime import datetime
from .tools import exec_file_in_path
from .tools import __get_postgres_volume_name
from .tools import __dc


def _rsync_image_name(config):
    return f"{config.PROJECT_NAME}-rsync:latest"


def __get_snapshots(config):
    vols = []
    for vol in subprocess.check_output(
        ["docker", "volume", "ls", "-q"], text=True
    ).splitlines():
        if vol.startswith(config.dbname + "___") and "_snapshot_" in vol:
            date = vol.split("_snapshot_")[-1]
            vols.append(
                {
                    "name": vol,
                    "date": datetime.strptime(
                        date, "%Y-%m-%d_T%H%M%S"
                    ).isoformat(),
                }
            )
    return list(sorted(vols, reverse=True, key=lambda x: x["date"]))


def assert_environment(config):
    exec_file_in_path("docker")


def restore(ctx, config, snap):
    postgres_volume_name = __get_postgres_volume_name(config)
    snapshot_name = snap
    __dc(config, ["stop", "-t", "1"] + ["postgres"])
    volumes = list(
        filter(
            lambda f: f.startswith(config.project_name),
            map(
                lambda x: x.strip(),
                subprocess.run(
                    ["docker", "volume", "ls", "-q"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                .stdout.strip()
                .splitlines(),
            ),
        )
    )
    if not [x for x in volumes if x == snap]:
        near = [x for x in volumes if f"___{snap}_snapshot" in x]
        if near:
            snap = near[0]
        else:
            raise Exception(f"Snapshot {snap} not found")
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{snapshot_name}:/src",
            "-v",
            f"{postgres_volume_name}:/dest",
            _rsync_image_name(config),
            "-ar",
            "--info=progress2",
            "--delete-after",
            "/src/",
            "/dest/",
        ],
        check=True,
    )
    __dc(config, ["up", "-d"] + ["postgres"])


def make_snapshot(ctx, config, name):
    now = datetime.now().strftime("%Y-%m-%d_T%H%M%S")
    snapshot_name = f"{config.dbname}___{name}_snapshot_{now}"
    postgres_volume_name = __get_postgres_volume_name(config)
    __dc(config, ["stop", "-t", "1"] + ["postgres"])
    subprocess.run(["docker", "volume", "create", snapshot_name], check=True)
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{postgres_volume_name}:/src",
            "-v",
            f"{snapshot_name}:/dest",
            _rsync_image_name(config),
            "-ar",
            "--info=progress2",
            "/src/",
            "/dest/",
        ],
        check=True,
    )
    __dc(config, ["up", "-d"] + ["postgres"])
    return snapshot_name


def remove(config, snapshot):
    snapshots = __get_snapshots(config)
    if snapshot in snapshots:
        subprocess.run(["docker", "volume", "rm", snapshot], check=True)
