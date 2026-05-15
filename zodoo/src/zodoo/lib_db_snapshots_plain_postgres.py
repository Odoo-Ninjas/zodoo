import arrow
from pathlib import Path
from datetime import datetime
from .tools import exec_file_in_path
from .cli import Commands


def __get_snapshots(config):
    path = Path(config.DUMPS_PATH)
    files = path.glob("*_snapshot_*")
    return [
        {"name": x.name, "date": arrow.get(x.stat().st_mtime).format()}
        for x in files
    ]


def assert_environment(config):
    exec_file_in_path("createdb")
    exec_file_in_path("psql")
    exec_file_in_path("dropdb")


def restore(ctx, config, snap):
    Commands.invoke(ctx, "restore_db", filename=snap)


def make_snapshot(ctx, config, name):
    now = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    snapshot_name = f"{config.dbname}_{name}_snapshot_{now}"
    Commands.invoke(ctx, "backup_db", filename=snapshot_name)
    return snapshot_name


def remove(config, snapshot):

    path = Path(config.DUMPS_PATH)
    for file in path.glob("*"):
        if file.name == snapshot:
            file.unlink()
            return
