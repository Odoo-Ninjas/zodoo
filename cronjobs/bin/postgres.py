#!/usr/bin/python3
import getpass
import time
import gzip
import shutil
import platform
import psycopg2
import pipes
import tempfile
import subprocess
from threading import Thread
import humanize
import os
import click
from pathlib import Path
from datetime import datetime
import logging
from contextlib import contextmanager

FORMAT = "[%(levelname)s] %(name) -12s %(asctime)s %(message)s"
logging.basicConfig(format=FORMAT)
logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger("")  # root handler


class DBSizeOutputter(Thread):
    def __init__(self, host, dbname, port, user, password):
        Thread.__init__(self)
        self.daemon = True
        self._stop = False
        self.host = host
        self.dbname = dbname
        self.port = port
        self.user = user
        self.password = password

    def run(self):
        while not self._stop:
            try:
                with psycopg2.connect(
                    host=self.host,
                    database=self.dbname,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                ) as conn:
                    with conn.cursor() as cr:
                        cr.execute(
                            f"SELECT (pg_database_size('{self.dbname}')) FROM pg_database"
                        )
                        res = cr.fetchone()
                        if not res:
                            continue
                        res = res[0]
                        res = humanize.naturalsize(res)
                        print(80 * " ", end="\r")
                        print(res, end="\r")

            except Exception as ex:
                time.sleep(1)
            finally:
                time.sleep(1)

    def stop(self):
        self._stop = True


@click.group()
def postgres():
    pass


@postgres.command(name="exec")
@click.argument("dbname", required=True)
@click.argument("host", required=True)
@click.argument("port", required=True)
@click.argument("user", required=True)
@click.argument("password", required=True)
@click.argument("sql", required=True)
def execute(dbname, host, port, user, password, sql):
    with psycopg2.connect(
        host=host,
        database=dbname,
        port=port,
        user=user,
        password=password,
    ) as conn:
        conn.autocommit = True
        with conn.cursor() as cr:
            logger.info(f"executing sql: {sql}")
            cr.execute(sql)
            res = cr.fetchall()
            logger.info(res)
            return res


@postgres.command()
@click.argument("dbname", required=True)
@click.argument("host", required=True)
@click.argument("port", required=True)
@click.argument("user", required=True)
@click.argument("password", required=True)
@click.argument("filepath", required=True)
@click.option(
    "--dumptype", type=click.Choice(["custom", "plain", "directory"]), default="custom"
)
@click.option(
    "--pigz",
    is_flag=True,
)
@click.option("-Z", "--compression", required=False, default=5)
@click.option("--column-inserts", is_flag=True)
@click.option("-T", "--exclude", multiple=True, help="Exclude Tables comma separated")
@click.option("-j", "--worker", default=1)
def backup(
    dbname,
    host,
    port,
    user,
    password,
    filepath,
    dumptype,
    column_inserts,
    exclude,
    pigz,
    compression,
    worker,
):
    port = int(port)
    filepath = Path(filepath)
    os.environ["PGPASSWORD"] = password
    conn = psycopg2.connect(
        host=host,
        database=dbname,
        port=port,
        user=user,
        password=password,
    )
    click.echo(f"Backing up to {filepath}")
    stderr = Path(tempfile.mktemp())
    temp_filepath = None
    try:
        cr = conn.cursor()
        cr.execute("SELECT (pg_database_size(current_database())) FROM pg_database")
        size = cr.fetchone()[0] * 0.7  # ct
        bytes = str(float(size)).split(".")[0]
        temp_filepath = filepath.with_name("." + filepath.name)

        column_inserts = column_inserts and "--column-inserts" or ""
        if column_inserts and dumptype != "plain":
            raise Exception(f"Requires plain dumptype when column inserts set!")

        # FOR PERFORMANCE USE os.system
        err_dump = Path(tempfile.mkstemp()[1])
        err_pigz = Path(tempfile.mkstemp()[1])
        err_dump.unlink()
        err_pigz.unlink()

        excludes = []
        for exclude in exclude:
            excludes += ["-T", exclude]

        cmd = (
            f"pg_dump {column_inserts} "
            f"--clean "
            f"--no-owner "
            f'-h "{host}" '
            f"-p {port} "
            f'{" ".join(excludes)} '
            f'-U "{user}" '
            f"-F{dumptype[0].lower()} "
        )
        if dumptype != "plain":
            cmd += f"-Z{compression} " f"-j {worker} "
        cmd += f" {dbname} " f"2>{err_dump} " f"| pv -s {bytes} "
        if pigz:
            cmd += "| pigz --rsyncable 2>{err_pigz}"
        cmd += f"> {temp_filepath} "
        try:
            os.system(cmd)
        finally:
            for file in [err_dump, err_pigz]:
                if file.exists() and file.read_text().strip():
                    raise Exception(file.read_text().strip())

        subprocess.check_call(["mv", temp_filepath, filepath])
        subprocess.check_call(["chown", os.environ["OWNER_UID"], filepath])
    finally:
        if temp_filepath and temp_filepath.exists():
            temp_filepath.unlink()
        conn.close()
        if stderr.exists():
            stderr.unlink()


@postgres.command()
@click.argument("dbname", required=True)
@click.argument("host", required=True)
@click.argument("port", required=True)
@click.argument("user", required=True)
@click.argument("password", required=True)
@click.argument("filepath", required=True)
@click.option("-j", "--workers", default=4)
@click.option("-X", "--exclude-tables", multiple=True)
@click.option("-v", "--verbose", is_flag=True)
@click.option("--ignore-errors", is_flag=True)
def restore(
    dbname,
    host,
    port,
    user,
    password,
    filepath,
    workers,
    exclude_tables,
    verbose,
    ignore_errors,
):
    _restore(
        dbname,
        host,
        port,
        user,
        password,
        filepath,
        workers,
        exclude_tables,
        verbose,
        ignore_errors,
    )


def _restore(
    dbname,
    host,
    port,
    user,
    password,
    filepath,
    workers=4,
    exclude_tables=None,
    verbose=False,
    ignore_errors=False,
):
    click.echo(f"Restoring dump on {host}:{port} as {user}")
    if not dbname:
        raise Exception("DBName missing")

    os.environ["PGPASSWORD"] = password
    args = ["-h", host, "-p", str(port), "-U", user]
    os.system(
        f"echo 'drop database if exists {dbname};' | psql {' '.join(args)} postgres"
    )
    # os.system(f"echo \"create database {dbname} ENCODING 'unicode' LC_COLLATE 'C' TEMPLATE template0;\" | psql {' '.join(args)} postgres")
    os.system(f"echo \"create database {dbname} ;\" | psql {' '.join(args)} postgres")

    PGRESTORE, PSQL = _get_cmd(args)
    method, needs_unzip = _get_restore_action(filepath, PGRESTORE, PSQL)

    started = datetime.now()
    click.echo("Restoring DB...")
    PV_CMD = " ".join(pipes.quote(s) for s in ["pv", str(filepath)])
    if workers > 1 and needs_unzip:
        workers = 1
        click.secho(
            "no error, performance note: Cannot use workers as source is unzipped via stdin",
            fg="yellow",
        )
    if needs_unzip or method == PSQL or (workers == 1 and not exclude_tables):
        CMD = PV_CMD
        if needs_unzip:
            if CMD:
                CMD += " | "
            CMD += next(_get_file("gunzip"))
        CMD += " | "
    else:
        CMD = ""
    CMD += " ".join(pipes.quote(s) for s in method)
    CMD += " "
    if method == PGRESTORE and verbose:
        CMD += " --verbose "
    CMD += " ".join(
        pipes.quote(s)
        for s in [
            "--dbname",
            dbname,
        ]
    )
    if method == PGRESTORE and not needs_unzip:
        CMD += f" '{filepath}' "

    if method != PGRESTORE and exclude_tables:
        raise Exception(
            "Exclude Table Option only available for pg_restore. "
            "Dump does not support pg_restore"
        )

    if exclude_tables and not needs_unzip:
        CMD += _get_exclude_table_param(filepath, exclude_tables)

    if workers > 1 and "pg_restore" in CMD[0]:
        CMD += ["-j", str(workers)]

    filename = Path(tempfile.mktemp(suffix=".rc"))
    CMD += f" && echo '1' > {filename}"
    print(CMD)

    sizeoutputter = DBSizeOutputter(host, dbname, port, user, password)
    sizeoutputter.start()
    os.system(CMD)
    click.echo(f"Restore took {(datetime.now() - started).total_seconds()} seconds")
    sizeoutputter.stop()
    success = False
    if filename.exists() and filename.read_text().strip() == "1":
        success = True

    if not success and not ignore_errors:
        raise Exception("Did not fully restore.")


def _get_exclude_table_param(filepath, exclude_tables):
    todolist = subprocess.check_output(
        ["pg_restore", "-l", filepath], encoding="utf8"
    ).splitlines()

    def ok(line):
        if "TABLE DATA public" in line and any(
            " " + X + " " in line for X in exclude_tables
        ):
            line = ";" + line
        return line

    filteredlist = list(map(ok, todolist))
    file = Path(tempfile.mktemp(suffix=".exclude_tables"))
    file.write_text("\n".join(filteredlist))
    return f" -L '{file}' "


def _get_cmd(args):
    pgrestore_version = subprocess.check_output(["pg_restore", "--version"], encoding="utf8")
    click.secho(f"PG Client Tools Version: {pgrestore_version}")
    PGRESTORE = [
        "pg_restore",
        "--no-owner",
        "--no-comments",
        "--no-privileges",
        "--no-acl",
    ] + args
    PSQL = ["psql"] + args
    return PGRESTORE, PSQL


def _get_restore_action(filepath, PGRESTORE, PSQL):
    method = PGRESTORE
    needs_unzip = True

    dump_type = __get_dump_type(filepath)
    if dump_type == "plain_text":
        needs_unzip = False
        method = PSQL
    elif dump_type == "zipped_sql":
        method = PSQL
        needs_unzip = True
    elif dump_type == "zipped_pgdump":
        pass
    elif dump_type == "pgdump":
        needs_unzip = False
    else:
        raise Exception(f"not impl: {dump_type}")
    return method, needs_unzip


def __get_dump_type(filepath):
    MARKER = "PostgreSQL database dump"
    first_line = None
    zipped = False

    try:
        output = subprocess.check_output(
            ["unzip", "-q", "-l", filepath], encoding="utf8"
        )
    except Exception:
        pass
    else:
        if "dump.sql" in output:
            return "odoosh"

    try:
        with gzip.open(filepath, "r") as f:
            for line in f:
                first_line = line.decode("utf-8", errors="ignore")
                zipped = True
                break
    except Exception:  # pylint: disable=broad-except
        with open(filepath, "rb") as f:
            first_line = ""
            for i in range(2048):
                t = f.read(1)
                t = t.decode("utf-8", errors="ignore")
                first_line += t

    if first_line.startswith("dump_all\n"):
        return "dump_all"

    if first_line.startswith("WODOO_BIN\n"):
        version = first_line.split("\n")[1]
        return f"wodoo_bin {version}"

    if first_line and zipped:
        if MARKER in first_line or first_line.strip() == "--":
            return "zipped_sql"
        if first_line.startswith("PGDMP"):
            return "zipped_pgdump"
    elif first_line:
        if "PGDMP" in first_line:
            return "pgdump"
        if MARKER in first_line:
            return "plain_text"
    return "unzipped_pgdump"


def _get_file(filename):
    paths = [
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    for x in paths:
        f = Path(x) / filename
        if f.exists():
            yield str(f)


@contextmanager
def autocleanpaper(filepath=None):
    filepath = Path(filepath or tempfile._get_default_tempdir()) / next(
        tempfile._get_candidate_names()
    )

    try:
        yield filepath
    finally:
        if filepath.exists():
            if filepath.is_dir():
                shutil.rmtree(filepath)
            else:
                filepath.unlink()


@contextmanager
def extract_dumps_all(tmppath, filepath):
    with autocleanpaper() as scriptfile:
        lendumpall = len("dump_all") + 2
        scriptfile.write_text(
            (
                "#!/bin/bash\n"
                "set -e\n"
                f"rm -Rf '{tmppath}'\n"
                f"mkdir -p '{tmppath}'\n"
                f"cd '{tmppath}'\n"
                f"tail '{filepath}' -c +{lendumpall} | "
                f"tar xz\n"
            )
        )
        subprocess.check_call(["/bin/bash", scriptfile])
        yield tmppath / "db", tmppath / "files"


if __name__ == "__main__":
    postgres()
