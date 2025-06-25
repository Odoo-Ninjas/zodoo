import tempfile
import arrow
import shutil
import requests
import time
import threading
import sys
import click
from consts import ODOO_USER
import subprocess
import configparser
import os
from wodoo import odoo_config
from wodoo.odoo_config import customs_dir
from wodoo.odoo_config import get_conn_autoclose
from wodoo.odoo_config import current_version
from pathlib import Path

pidfile = Path("/tmp/odoo.pid")
config = odoo_config.get_settings()
version = odoo_config.current_version()

is_odoo_cronjob = os.getenv("IS_ODOO_CRONJOB", "0") == "1"
is_odoo_queuejob = os.getenv("IS_ODOO_QUEUEJOB", "0") == "1"


def _get_queuejob_channels():
    if os.getenv("QUEUEJOB_CHANNELS_FILE"):
        settingsfile = (
            Path("/opt/run") / Path(os.environ["QUEUEJOB_CHANNELS_FILE"]).name
        )
        if settingsfile.exists():
            channels = ",".join(settingsfile.read_text().strip().splitlines())
        else:
            channels = os.getenv("ODOO_QUEUEJOBS_CHANNELS")
    else:
        channels = os.getenv("ODOO_QUEUEJOBS_CHANNELS")

        # replace any env variable
    channels = [
        (x, int(y))
        for x, y in list(
            map(
                lambda x: x.strip().split(":"),
                [X for X in channels.split(",")],
            )
        )
    ]
    channels_no_root = [x for x in channels if x[0] != "root"]
    if channels_no_root:
        Sum = sum(x[1] for x in channels_no_root)
    elif channels:
        Sum = sum(x[1] for x in channels)
    else:
        raise Exception("Please define at least on root channel for odoo queue jobs.")

    channels = ",".join(f"{x[0]}:{x[1]}" for x in [("root", Sum)] + channels_no_root)

    # Why * 2; doesnt work with just * 1 - dont understand why right now;
    # Queuejobs did not start at all
    if not config.get("ODOO_QUEUEJOBS_WORKERS"):
        config["ODOO_QUEUEJOBS_WORKERS"] = str(int(Sum * 2))  # good for all in one also
    return channels


def _replace_params_in_config(
    ADDONS_PATHS, content, server_wide_modules=None, upgrade_path=None
):
    if not config.get("DB_HOST", "") or not config.get("DB_USER", ""):
        raise Exception("Please define all DB Env Variables!")
    content = content.replace("__ADDONS_PATH__", ADDONS_PATHS)
    content = content.replace(
        "__ENABLE_DB_MANAGER__",
        "True" if config["ODOO_ENABLE_DB_MANAGER"] == "1" else "False",
    )
    for key in ["WEB", "QUEUEJOBS", "CRON", "UPDATE", "MIGRATION"]:
        for ttype in ["HARD", "SOFT"]:
            content = content.replace(
                f"__LIMIT_MEMORY_{ttype}_{key}__",
                config.get(f"LIMIT_MEMORY_{ttype}_{key}", "32000000000"),
            )
    content = content.replace(
        "__LIMIT_MEMORY_HARD__", config.get("LIMIT_MEMORY_HARD", "32000000000")
    )
    content = content.replace(
        "__LIMIT_MEMORY_SOFT__", config.get("LIMIT_MEMORY_SOFT", "31000000000")
    )

    server_wide_modules = ",".join(_get_server_wide_modules(server_wide_modules))
    content = content.replace("__SERVER_WIDE_MODULES__", server_wide_modules)

    # queuejob channels
    content = content.replace("__ODOO_QUEUEJOBS_CHANNELS__", _get_queuejob_channels())

    # upgrade paths
    upgrade_path = upgrade_path or []
    upgrade_path = make_absolute_upgrade_paths(upgrade_path)
    content = content.replace("__UPGRADE_PATH__", ",".join(upgrade_path))

    for key, value in os.environ.items():
        key = f"__{key}__"
        content = content.replace(key, value)

    for key in config.keys():
        content = content.replace("__{}__".format(key), config[key])

    # exchange existing configurations
    return content

def make_absolute_upgrade_paths(upgrade_path):
    res = []
    c = customs_dir()
    for path in upgrade_path:
        if path.startswith("/"):
            res.append(path)
        else:
            res.append(str(c / path))
    return res


def _apply_additional_odoo_config(content, addition):
    """
    [options]
    ...


    [queue_job]
    ...

    [option1]
    ...
    """
    content = list(
        filter(lambda x: not x.strip().startswith("#"), content.split("___|||___"))
    )
    assert content[0] == "[options]"
    for i, line in enumerate(content[1:], 1):
        if line.strip().startswith("["):
            break

    part1, part2 = "\n".join(content[: i + 1]), "\n".join(content[i + 1 :])
    content = part1 + "\n" + addition + "\n" + part2
    return content


def _run_autosetup():
    path = customs_dir() / "autosetup"
    if path.exists():
        for file in path.glob("*.sh"):
            print("executing {}".format(file))
            os.chdir(path.parent)
            subprocess.check_call(
                [
                    file,
                    os.environ["ODOO_AUTOSETUP_PARAM"],
                ]
            )


def _replace_variables_in_config_files(local_config):
    config_dir = Path(os.environ["ODOO_CONFIG_DIR"])
    config_dir_template = Path(os.environ["ODOO_CONFIG_TEMPLATE_DIR"])
    config_dir.mkdir(exist_ok=True, parents=True)
    for file in config_dir_template.glob("*"):
        path = str(config_dir / file.name)
        shutil.copy(str(file), path)
        subprocess.call(["chmod", "a+r", path])
        del path

    no_extra_addons_paths = False
    if local_config and local_config.no_extra_addons_paths:
        no_extra_addons_paths = True
    additional_addons_paths = False
    if local_config and local_config.additional_addons_paths:
        additional_addons_paths = local_config.additional_addons_paths

    if os.getenv("ADDITIONAL_ADDONS_PATHS"):
        if not additional_addons_paths:
            additional_addons_paths = os.getenv("ADDITIONAL_ADDONS_PATHS")
        else:
            additional_addons_paths += "," + os.getenv("ADDITIONAL_ADDONS_PATHS")

    ADDONS_PATHS = ",".join(
        list(
            map(
                str,
                odoo_config.get_odoo_addons_paths(
                    no_extra_addons_paths=no_extra_addons_paths,
                    additional_addons_paths=(additional_addons_paths or "").split(","),
                ),
            )
        )
    )

    config_dir = Path(os.getenv("ODOO_CONFIG_DIR"))

    def _get_config(filepath=None, string=None):
        content = filepath.read_text() if filepath else string
        server_wide_modules = None
        if local_config and local_config.server_wide_modules:
            server_wide_modules = local_config.server_wide_modules.split(",") or None
        elif os.getenv("SERVER_WIDE_MODULES"):
            server_wide_modules = os.environ["SERVER_WIDE_MODULES"].split(",")

        if local_config and local_config.upgrade_path:
            upgrade_path = local_config.upgrade_path.split(",")
        else:
            upgrade_path = list(filter(bool, os.getenv("UPGRADE_PATH", "").split(",")))
        upgrade_path = list(map(lambda x: x.strip(), upgrade_path))

        content = _replace_params_in_config(
            ADDONS_PATHS,
            content,
            server_wide_modules=server_wide_modules,
            upgrade_path=upgrade_path,
        )
        cfg = configparser.ConfigParser()
        cfg.read_string(content)
        return cfg

    common_config = _get_config(config_dir / "common")
    for file in config_dir.glob("config_*"):
        config_file_content = _get_config(file)
        _apply_configuration(config_file_content, common_config)

        # apply configuration coming from environment variable ADDITIONAL_ODOO_CONFIG
        # as there may be options
        if os.getenv("ADDITIONAL_ODOO_CONFIG"):
            _apply_configuration(
                config_file_content,
                _get_config(string=os.environ["ADDITIONAL_ODOO_CONFIG"]),
            )

        if config["ODOO_ADMIN_PASSWORD"]:
            config_file_content["options"]["admin_passwd"] = config[
                "ODOO_ADMIN_PASSWORD"
            ]

        if config.get("ODOO_DEBUG_LOGLEVEL"):
            loglevel = config["ODOO_DEBUG_LOGLEVEL"]
            LOGLEVEL = loglevel.upper()
            config_file_content["options"][
                "log_handler"
            ] = f":{LOGLEVEL},openerp:{LOGLEVEL},werkzeug:{LOGLEVEL},odoo.addons.queue_job:{LOGLEVEL}"
            config_file_content["options"]["log_level"] = loglevel

        if "without_demo" not in config_file_content["options"]:
            if os.getenv("ODOO_DEMO", "") == "1":
                if version <= 17.0:
                    config_file_content["options"]["without_demo"] = "false"
            else:
                config_file_content["options"]["without_demo"] = "all"

        with open(file, "w") as configfile:
            config_file_content.write(configfile)


def _apply_configuration(config_file, to_apply_config_file):
    for section in to_apply_config_file.sections():
        for k, v in to_apply_config_file[section].items():
            if section not in config_file.sections() or k not in config_file[section]:
                config_file[section][k] = v


def _run_libreoffice_in_background():
    cmd = os.environ["ODOOLIB"] + "/run_soffice.py"
    os.system(f"python3 {cmd} 1>/dev/null 2>/dev/null &")


def get_config_file(confname):
    return str(Path(os.environ["ODOO_CONFIG_DIR"]) / confname)


def prepare_run(local_config=None):
    _replace_variables_in_config_files(local_config)

    if config["RUN_AUTOSETUP"] == "1":
        _run_autosetup()

    _run_libreoffice_in_background()

    # make sure out dir is owned by odoo user to be writable
    user_id = int(os.getenv("OWNER_UID", os.getuid()))
    for path in [
        os.environ["OUT_DIR"],
        os.environ["RUN_DIR"],
        os.environ["ODOO_DATA_DIR"],
        os.getenv("INTERCOM_DIR", ""),
        Path(os.environ["RUN_DIR"]) / "debug",
        Path(os.environ["ODOO_DATA_DIR"]) / "addons",
        Path(os.environ["ODOO_DATA_DIR"]) / "filestore",
        Path(os.environ["ODOO_DATA_DIR"]) / "sessions",
    ]:
        if not path:
            continue
        out_dir = Path(path)
        if not out_dir.exists() and not out_dir.is_symlink():
            out_dir.mkdir(parents=True, exist_ok=True)
        if out_dir.exists():
            if out_dir.stat().st_uid == 0:
                shutil.chown(str(out_dir), user=user_id, group=user_id)
        del path
        del out_dir

    if os.getenv("IS_ODOO_QUEUEJOB", "") == "1":
        # https://www.odoo.com/apps/modules/10.0/queue_job/
        sql = "update queue_job set state='pending' where state in ('started', 'enqueued');"
        with get_conn_autoclose() as cr:
            cr.execute(sql)


def get_odoo_bin(for_shell=False):
    if is_odoo_cronjob and not config.get("RUN_ODOO_CRONJOBS") == "1":
        print("Cronjobs shall not run. Good-bye!")
        sys.exit(0)

    if is_odoo_queuejob and not config.get("RUN_ODOO_QUEUEJOBS") == "1":
        print("Queue-Jobs shall not run. Good-bye!")
        sys.exit(0)

    EXEC = "odoo-bin"
    if is_odoo_cronjob:
        print("Starting odoo cronjobs")
        CONFIG = "config_cronjob"
        if version <= 9.0:
            EXEC = "openerp-server"

    elif is_odoo_queuejob:
        print("Starting odoo queuejobs")
        CONFIG = "config_queuejob"

    else:
        CONFIG = "config_webserver"
        if version <= 9.0:
            if for_shell:
                EXEC = "openerp-server"
            else:
                EXEC = "openerp-server"
        else:
            try:
                if config.get("ODOO_GEVENT_MODE", "") == "1":
                    raise Exception("Dont use GEVENT MODE anymore")
            except KeyError:
                pass
            if os.getenv("ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER", "") == "1":
                CONFIG = "config_allinone"

            if os.getenv("ODOO_CRON_IN_ONE_CONTAINER", "") == "1":
                CONFIG = "config_web_and_cron"

    EXEC = "/".join([os.environ["SERVER_DIR"], EXEC])
    if not Path(EXEC).exists() and Path(EXEC).parent.exists():
        # project where they had the installed version of odoo
        EXEC = Path(EXEC).parent.parent / Path(EXEC).name
    return EXEC, CONFIG


def kill_odoo():
    if pidfile.exists():
        print("Killing Odoo")
        pid = pidfile.read_text()
        cmd = ["/bin/kill", "-9", pid]
        if (
            os.getenv("USE_DOCKER", "") == "1"
            and os.getenv("DOCKER_MACHINE", "") == "1"
        ):
            cmd = [
                "/usr/bin/sudo",
            ] + cmd
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        try:
            pidfile.unlink()
        except FileNotFoundError:
            pass
    else:
        if version <= 9.0:
            subprocess.run(
                [
                    "/usr/bin/sudo",
                    "/usr/bin/pkill",
                    "-9",
                    "-f",
                    "openerp-server",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    "/usr/bin/sudo",
                    "/usr/bin/pkill",
                    "-9",
                    "-f",
                    "openerp-gevent",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        else:
            subprocess.run(
                [
                    "/usr/bin/sudo",
                    "/usr/bin/pkill",
                    "-9",
                    "-f",
                    "odoo-bin",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    sane_tty()


def sane_tty():
    # was not needed in debian
    if Path("/usr/bin/stty").exists():
        subprocess.run(["/usr/bin/stty", "sane"])


def __python_exe(remote_debug=False, wait_for_remote=False):
    if version <= 10.0:
        cmd = ["/usr/bin/python"]
    else:
        # return "/usr/bin/python3"
        cmd = ["/opt/venv/bin/python3"]

    if remote_debug or wait_for_remote:
        cmd += [
            "-mdebugpy",
            "--listen",
            "0.0.0.0:5678",
        ]

    if wait_for_remote:
        cmd += [
            "--wait-for-client",
        ]
    return cmd


def wait_postgres(timeout=10):
    import psycopg2

    def connect():
        psycopg2.connect(
            dbname="postgres",
            host=os.environ["DB_HOST"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PWD"],
            port=int(os.environ["DB_PORT"]),
        )

    deadline = arrow.get().shift(seconds=timeout)
    count = 0
    sleep = 0.5
    while arrow.get() < deadline:
        count += 1
        try:
            connect()
        except Exception as ex:
            click.secho("Waiting for postgres to arrive", fg="blue")
            time.sleep(sleep)
            if count > 3:
                click.secho(ex, fg="red")
            sleep *= 1.4
        else:
            break


def exec_odoo(
    CONFIG,
    *args,
    odoo_shell=False,
    touch_url=False,
    on_done=None,
    stdin=None,
    dokill=True,
    remote_debug=False,
    wait_for_remote=False,
    **kwargs,
):  # NOQA
    assert not [x for x in args if "--pidfile" in x], "Not custom pidfile allowed"

    if dokill:
        kill_odoo()

    wait_postgres()

    MANIFEST = odoo_config.MANIFEST()
    manifest = MANIFEST._get_data()
    os.environ['SERVER_DIR'] = str(Path(os.environ['CUSTOMS_DIR']) /  MANIFEST.odoo_dir)

    EXEC, _CONFIG = get_odoo_bin(for_shell=odoo_shell)
    CONFIG = get_config_file(CONFIG or _CONFIG)
    cmd = []
    if os.getenv("ODOO_SUDO_CMD") == "1":
        cmd = [
            "/usr/bin/sudo",
            "-E",
            "-H",
            "-u",
            ODOO_USER,
        ]
    cmd += __python_exe(remote_debug=remote_debug, wait_for_remote=wait_for_remote) + [
        EXEC,
    ]
    if odoo_shell:
        cmd += ["shell"]
    try:
        DBNAME = config["DBNAME"]
    except KeyError:
        DBNAME = os.environ["DBNAME"]
    cmd += ["-c", CONFIG, "-d", DBNAME]

    # if os.getenv("DEVMODE") == "1":
    #     print(Path(CONFIG).read_text())
    if os.getenv("PROXY_PORT", ""):
        PROXY_PORT = os.environ["PROXY_PORT"]
        click.secho(f"PROXY Port: {PROXY_PORT}", fg="green", bold=True)
    if not odoo_shell:
        cmd += [
            f"--pidfile={pidfile}",
        ]
    cmd += args

    cmd = " ".join(map(lambda x: f'"{x}"', cmd))

    if touch_url:
        _touch()

    filename = Path(tempfile.mktemp(suffix=".exitcode"))
    cmd += f" || echo $? > {filename}"

    if stdin:
        if isinstance(stdin, str):
            stdin = stdin.encode("utf-8")
        subprocess.run(cmd, input=stdin, shell=True)
    else:
        subprocess.run(cmd, shell=True)
    if pidfile.exists():
        pidfile.unlink()
    if on_done:
        on_done()

    rc = 0
    if filename.exists():
        try:
            rc = int(filename.read_text().strip())
        except ValueError:
            rc = -1  # undefined return code
        finally:
            filename.unlink()
    return rc


def _run_shell_cmd(code, do_raise=False):
    cmd = [
        "--stop-after-init",
    ]
    if current_version() >= 11.0:
        cmd += ["--shell-interface=ipython"]

    rc = exec_odoo(
        "config_shell",
        *cmd,
        odoo_shell=True,
        stdin=code,
        dokill=False,
    )
    if do_raise and rc:
        click.secho(("Failed at: \n" f"{code}",), fg="red")
        sys.exit(-1)
    return rc


def _get_server_wide_modules(server_wide_modules=None):
    if not server_wide_modules:
        server_wide_modules = (os.getenv("SERVER_WIDE_MODULES", "") or "").split(",")

    if (
        os.getenv("IS_ODOO_QUEUEJOB", "") == "1"
        or os.getenv("ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER", "") == "1"
    ):
        if "queue_job" not in server_wide_modules:
            server_wide_modules.append("queue_job")

    if (
        os.getenv("IS_ODOO_QUEUEJOB", "") != "1"
        and os.getenv("ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER", "") != "1"
    ):
        if "queue_job" in server_wide_modules:
            server_wide_modules.remove("queue_job")

    if (
        os.getenv("ODOO_CRON_IN_WEB_CONTAINER", "") == "1"
        and os.getenv("ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER", "") != "1"
    ):
        if "queue_job" in server_wide_modules:
            server_wide_modules.remove("queue_job")
    return server_wide_modules


def _touch():
    def toucher():
        while True:
            try:
                r = requests.get(
                    "http://localhost:{}".format(os.environ["INTERNAL_ODOO_PORT"])
                )
                r.raise_for_status()
                print("HTTP Get to odoo succeeded.")
                break
            finally:
                time.sleep(2)

    t = threading.Thread(target=toucher)
    t.daemon = True
    print("Touching odoo url to start it")
    t.start()
