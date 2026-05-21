import threading
import socket
import time
import sys
import tempfile
import arrow
import shutil
import requests
import click
from sudo_odoo import sudo_odoo_cmd  # noqa: F401  (re-export)
import subprocess


import configparser
import os
from zodoo import odoo_config
from zodoo.odoo_config import customs_dir
from zodoo.odoo_config import get_conn_autoclose
from zodoo.odoo_config import current_version
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Per-role pidfile: inside the single consolidated odoo container, web /
# cronjobs / queuejobs all run as sibling children of the supervisor, so
# one shared pidfile (or a blanket `pkill -f odoo-bin`) would have each
# role tearing down the others at startup. The role name is injected by
# supervisor.py via ZODOO_ROLE.
_role = os.getenv("ZODOO_ROLE", "web")
pidfile = Path(f"/tmp/odoo.{_role}.pid")
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

    if not channels:
        raise Exception(
            "Please define ODOO_QUEUEJOBS_CHANNELS or QUEUEJOB_CHANNELS_FILE."
        )
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
        raise Exception(
            "Please define at least on root channel for odoo queue jobs."
        )

    channels = ",".join(
        f"{x[0]}:{x[1]}" for x in [("root", Sum)] + channels_no_root
    )

    # Why * 2; doesnt work with just * 1 - dont understand why right now;
    # Queuejobs did not start at all
    if not config.get("ODOO_QUEUEJOBS_WORKERS"):
        config["ODOO_QUEUEJOBS_WORKERS"] = str(
            int(Sum * 2)
        )  # good for all in one also
    return channels


def _replace_params_in_config(
    ADDONS_PATHS, content, server_wide_modules=None, upgrade_path=None
):
    for key in ["DB_HOST", "DB_USER"]:
        if not config.get(key, ""):
            raise Exception(f"Please define {key} Env Variables!")
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

    server_wide_modules = ",".join(
        _get_server_wide_modules(server_wide_modules)
    )
    content = content.replace("__SERVER_WIDE_MODULES__", server_wide_modules)

    # queuejob channels
    content = content.replace(
        "__ODOO_QUEUEJOBS_CHANNELS__", _get_queuejob_channels()
    )

    extra_config = []
    for setting in os.environ.keys():
        if setting.startswith("EXTRA_CONFIG_"):
            key = setting.replace("EXTRA_CONFIG_", "")
            value = os.environ[setting]
            extra_config.append(f"{key} = {value}")
    content = content.replace(
        "___EXTRA_ODOO_CONFIG___", "\n".join(extra_config)
    )

    # upgrade paths
    upgrade_path = upgrade_path or []
    upgrade_path = make_absolute_upgrade_paths(upgrade_path)
    content = content.replace("__UPGRADE_PATH__", ",".join(upgrade_path))

    for key, value in os.environ.items():
        key = f"__{key}__"
        content = content.replace(key, value)

    for key in config.keys():
        content = content.replace(f"__{key}__", config[key])

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
        filter(
            lambda x: not x.strip().startswith("#"), content.split("___|||___")
        )
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
            click.secho(f"executing {file}")
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
    user_id = int(os.getenv("OWNER_UID", os.getuid()))
    for file in config_dir_template.glob("*"):
        path = str(config_dir / file.name)
        shutil.copy(str(file), path)
        subprocess.call(["chmod", "a+r", path])
        # chown to the odoo user so a later re-invocation as that user
        # (via sudo_odoo_cmd) can overwrite these files.  Silently
        # ignored when we're already running as non-root (chown of a
        # file we own is a no-op; chown of a foreign file fails — that
        # path means the first invocation already did the right thing).
        try:
            shutil.chown(path, user=user_id, group=user_id)
        except (PermissionError, LookupError):
            pass
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
            additional_addons_paths += "," + os.getenv(
                "ADDITIONAL_ADDONS_PATHS"
            )

    ADDONS_PATHS = ",".join(
        list(
            map(
                str,
                odoo_config.get_odoo_addons_paths(
                    no_extra_addons_paths=no_extra_addons_paths,
                    additional_addons_paths=(
                        additional_addons_paths or ""
                    ).split(","),
                ),
            )
        )
    )

    config_dir = Path(os.getenv("ODOO_CONFIG_DIR"))

    def _get_config(filepath=None, string=None):
        content = filepath.read_text() if filepath else string
        server_wide_modules = None
        if local_config and local_config.server_wide_modules:
            server_wide_modules = (
                local_config.server_wide_modules.split(",") or None
            )
        elif os.getenv("SERVER_WIDE_MODULES"):
            server_wide_modules = os.environ["SERVER_WIDE_MODULES"].split(",")
        if local_config and local_config.upgrade_path:
            upgrade_path = local_config.upgrade_path.split(",")
        else:
            upgrade_path = list(
                filter(bool, os.getenv("UPGRADE_PATH", "").split(","))
            )
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
                if version <= 19.0:
                    config_file_content["options"]["without_demo"] = "false"
            else:
                config_file_content["options"]["without_demo"] = "all"

        with open(file, "w") as configfile:
            config_file_content.write(configfile)


def _apply_configuration(config_file, to_apply_config_file):
    for section in to_apply_config_file.sections():
        for k, v in to_apply_config_file[section].items():
            if (
                section not in config_file.sections()
                or k not in config_file[section]
            ):
                config_file[section][k] = v


def _run_libreoffice_in_background():
    cmd = os.environ["ODOOLIB"] + "/run_soffice.py"
    os.system(f"python3 {cmd} 1>/dev/null 2>/dev/null &")


def get_config_file(confname):
    return str(Path(os.environ["ODOO_CONFIG_DIR"]) / confname)


def prepare_run_shared(local_config=None):
    # Container-shared setup: chown writable dirs, render config files from
    # templates, run autosetup, start libreoffice. Idempotent. Under the
    # supervisor this runs once before role spawn — running it concurrently
    # in each role races on ODOO_CONFIG_DIR (templates get copied back over
    # already-substituted files, leaving placeholders like __DB_MAXCONN__
    # in the live config and crashing odoo at CLI parse time).
    user_id = int(os.getenv("OWNER_UID", os.getuid()))
    for path in [
        os.environ["ODOO_CONFIG_DIR"],
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
                subprocess.call(
                    [
                        "chown",
                        "-R",
                        f"{user_id}:{user_id}",
                        str(out_dir),
                    ]
                )
        del path
        del out_dir

    _replace_variables_in_config_files(local_config)

    if config["RUN_AUTOSETUP"] == "1":
        _run_autosetup()

    _run_libreoffice_in_background()


def prepare_run_role():
    # Role-specific setup that has to happen inside each role process,
    # AFTER prepare_run_shared has populated ODOO_CONFIG_DIR.
    if os.getenv("IS_ODOO_QUEUEJOB", "") == "1":
        # https://www.odoo.com/apps/modules/10.0/queue_job/
        with get_conn_autoclose() as cr:
            sql = "update queue_job set state='pending' where state in ('started', 'enqueued');"
            if table_exists(cr, "queue_job"):
                if column_exists(cr, "queue_job", "state"):
                    cr.execute(sql)


def prepare_run(local_config=None):
    # Full prep for one-off invocations (debug/shell/unit_test/update). The
    # supervisor splits this — see prepare_run_shared / prepare_run_role.
    prepare_run_shared(local_config)
    prepare_run_role()


def table_exists(cr, table):
    cr.execute(f"SELECT to_regclass('public.{table}');")
    table_exists = cr.fetchone()[0]
    return table_exists


def column_exists(cr, table, column):
    # Check if column exists
    cr.execute(f"""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = '{table}'
            AND column_name = '{column}'
        );
    """)
    column_exists = cr.fetchone()[0]
    return column_exists


def get_odoo_bin(for_shell=False):
    # Belt-and-suspenders: the supervisor already refuses to spawn a role
    # when the matching RUN_ODOO_* flag is 0. If something else still invokes
    # this code path with IS_ODOO_CRONJOB/QUEUEJOB set while the toggle is
    # off, exit cleanly so the process can't run half-enabled.
    if is_odoo_cronjob and not config.get("RUN_ODOO_CRONJOBS") == "1":
        click.secho("Cronjobs shall not run. Good-bye!")
        sys.exit(0)

    # Queuejob role is gated by `_queue_job_installed()` in the
    # supervisor (no longer a manual RUN_ODOO_QUEUEJOBS env toggle). If
    # something invokes this code path with IS_ODOO_QUEUEJOB=1 while the
    # module is no longer installed, exit cleanly.
    if is_odoo_queuejob and not odoo_config._queue_job_installed():
        click.secho(
            "Queue-Jobs shall not run — `queue_job` is not installed in "
            "the project DB. Good-bye!",
            fg="yellow",
        )
        sys.exit(0)

    EXEC = "odoo-bin"
    if is_odoo_cronjob:
        click.secho("Starting odoo cronjobs")
        CONFIG = "config_cronjob"
        if version <= 9.0:
            EXEC = "openerp-server"

    elif is_odoo_queuejob:
        click.secho("Starting odoo queuejobs")
        CONFIG = "config_queuejob"

    else:
        CONFIG = "config_webserver"
        if version <= 9.0:
            EXEC = "openerp-server"
        else:
            if config.get("ODOO_GEVENT_MODE", "") == "1":
                raise Exception("Dont use GEVENT MODE anymore")

    EXEC = "/".join([os.environ["SERVER_DIR"], EXEC])
    if not Path(EXEC).exists() and Path(EXEC).parent.exists():
        # project where they had the installed version of odoo
        EXEC = Path(EXEC).parent.parent / Path(EXEC).name
    return EXEC, CONFIG


def is_in_container():
    from zodoo.tools import _is_in_container

    return _is_in_container()


def kill_odoo():
    if pidfile.exists():
        click.secho("Killing Odoo")
        pid = pidfile.read_text().strip()
        base_cmd = (
            ["/usr/bin/sudo"]
            if os.getenv("USE_DOCKER", "") == "1" and is_in_container()
            else []
        )
        # SIGTERM first: master signals workers to exit cleanly, freeing port 8069
        subprocess.run(
            base_cmd + ["/bin/kill", "-15", pid],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        import time as _time

        for _ in range(10):
            _time.sleep(1)
            try:
                import os as _os

                _os.kill(int(pid), 0)
            except ProcessLookupError:
                break
        else:
            subprocess.run(
                base_cmd + ["/bin/kill", "-9", pid],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        try:
            pidfile.unlink()
        except FileNotFoundError:
            pass

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
        cmd = ["/opt/venv/bin/python3", "-Xfrozen_modules=off"]

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
    from contextlib import closing

    def connect():
        # Probe connection only — close immediately so we don't leak
        # one connection per retry (the loop below can fire many
        # `connect()` calls during a slow startup).
        # NOTE: `with psycopg2.connect()` only ends the transaction,
        # NOT the connection — wrap in `contextlib.closing` to actually
        # close it.
        with closing(
            psycopg2.connect(
                dbname="postgres",
                host=os.environ["DB_HOST"],
                user=os.environ["DB_USER"],
                password=os.environ["DB_PWD"],
                port=int(os.environ["DB_PORT"]),
            )
        ):
            pass

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
    enable_queuejobs=False,
    capture_output=None,
    **kwargs,
):  # NOQA
    assert not [
        x for x in args if "--pidfile" in x
    ], "Not custom pidfile allowed"

    if dokill:
        kill_odoo()

    wait_postgres()

    MANIFEST = odoo_config.MANIFEST()
    manifest = MANIFEST._get_data()
    os.environ["SERVER_DIR"] = str(
        Path(os.environ["CUSTOMS_DIR"]) / MANIFEST.odoo_dir
    )

    EXEC, _CONFIG = get_odoo_bin(for_shell=odoo_shell)
    CONFIG = get_config_file(CONFIG or _CONFIG)
    cmd = sudo_odoo_cmd(
        __python_exe(
            remote_debug=remote_debug, wait_for_remote=wait_for_remote
        )
        + [EXEC]
    )
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
        t = threading.Thread(target=_touch)
        t.start()

    filename = Path(tempfile.mktemp(suffix=".exitcode"))
    cmd += f" || echo $? > {filename}"

    def _tee(proc):
        lines = []
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            lines.append(line)
        proc.wait()
        return "".join(lines)

    params_capture = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if not capture_output:
        params_capture = {}
        output = ""

    if stdin:
        if not isinstance(stdin, str):
            stdin = (
                stdin.decode("utf-8")
                if isinstance(stdin, bytes)
                else str(stdin)
            )
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdin=subprocess.PIPE,
            **params_capture,
        )
        proc.stdin.write(
            stdin if params_capture.get("text") else stdin.encode("utf-8")
        )
        proc.stdin.close()
        if capture_output:
            output = _tee(proc)
    else:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            **params_capture,
        )
        if capture_output:
            output = _tee(proc)
    if not capture_output:
        proc.wait()
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
    return rc, output


def _run_shell_cmd(code, do_raise=False):
    cmd = [
        "--stop-after-init",
    ]
    if current_version() >= 11.0:
        cmd += ["--shell-interface=ipython"]

    rc, output = exec_odoo(
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
    """Return the list of server-wide modules for this odoo container.

    `queue_job` is added iff the module is installed in the project DB
    (probed via `ir_module_module`). The legacy env-var-based logic
    (RUN_ODOO_QUEUEJOBS, IS_ODOO_QUEUEJOB, ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER,
    ODOO_CRON_IN_WEB_CONTAINER, ENABLE_QUEUEJOBS) is gone — after the
    single-container refactor `RUN_ODOO_*` toggles only steer the
    supervisor's role spawning, and `queue_job` server-wide-loading must
    follow the actual installed-module state instead so that:
      - fresh / empty DBs don't try to import a module that isn't there,
      - DBs that DO have queue_job installed get it loaded for every
        sibling role (web / cronjobs / queuejobs), so `@job` decorators
        and `delay()` work consistently across processes.

    When queue_job ends up in the server-wide list, the queue_job channel
    config is mandatory; fail loudly if neither
    `ODOO_QUEUEJOBS_CHANNELS` nor `QUEUEJOB_CHANNELS_FILE` is set —
    silently loading the module without a channel definition means jobs
    accumulate in `pending` forever.
    """
    if not server_wide_modules:
        server_wide_modules = (
            os.getenv("SERVER_WIDE_MODULES", "") or ""
        ).split(",")
    server_wide_modules = [m for m in server_wide_modules if m and m.strip()]

    needs_queue_job = odoo_config._queue_job_installed()
    if needs_queue_job:
        if "queue_job" not in server_wide_modules:
            server_wide_modules.append("queue_job")
        if not (
            os.getenv("ODOO_QUEUEJOBS_CHANNELS")
            or os.getenv("QUEUEJOB_CHANNELS_FILE")
        ):
            click.secho(
                "queue_job is installed in the database but no channel "
                "configuration is set. Define ODOO_QUEUEJOBS_CHANNELS "
                "(e.g. 'root:1') or QUEUEJOB_CHANNELS_FILE in your "
                "settings — otherwise queued jobs will never be picked "
                "up.",
                fg="red",
                bold=True,
            )
    elif "queue_job" in server_wide_modules:
        server_wide_modules.remove("queue_job")

    return server_wide_modules


def wait_for_tcp(
    host: str, port: int, timeout: float = 60.0, interval: float = 0.5
):
    """
    Wait until TCP port on host becomes reachable.

    :param host: Domain or IP (e.g. "localhost", "odoo", "example.com")
    :param port: TCP port (e.g. 8069)
    :param timeout: Max seconds to wait
    :param interval: Seconds between retries
    :raises TimeoutError: if not reachable in time
    """
    click.secho(
        f"Waiting for TCP {host}:{port} to become reachable...", fg="blue"
    )
    deadline = time.time() + timeout
    last_error = None

    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=3):
                click.secho(f"TCP {host}:{port} is reachable.", fg="green")
                return  # Success
        except OSError as e:
            last_error = e
            time.sleep(interval)

    raise TimeoutError(
        f"Timeout waiting for TCP {host}:{port} — last error: {last_error}"
    )


ASSET_BUNDLES_DEFAULT = (
    "web.assets_common,web.assets_frontend,web.assets_backend,"
    "web.assets_common_lazy,web.assets_frontend_lazy,"
    "web.assets_common_minimal,web.assets_frontend_minimal,"
    "web.assets_backend_prod_only"
)


# Module-level start timestamp shared across pre-gen and HTTP warmup so the
# closing banner can report end-to-end elapsed time.
_WARMUP_T0 = None
_WARMUP_WIDTH = 72


def _warmup_banner(title, char="═", fg="cyan"):
    line = char * _WARMUP_WIDTH
    inner = f" {title} "
    pad = max(0, (_WARMUP_WIDTH - len(inner)) // 2)
    click.secho("")
    click.secho(line, fg=fg, bold=True)
    click.secho(" " * pad + inner, fg=fg, bold=True)
    click.secho(line, fg=fg, bold=True)


def _warmup_phase(num, total, title):
    click.secho("")
    header = click.style(f"[{num}/{total}]", fg="cyan", bold=True)
    click.secho(f"{header} {click.style(title, bold=True)}")


def _warmup_step_ok(label, elapsed=None, extra=""):
    bullet = click.style("✓", fg="green", bold=True)
    dots = "." * max(2, 48 - len(label))
    timing = f" {elapsed:6.2f}s" if elapsed is not None else " " * 8
    suffix = f"  {extra}" if extra else ""
    click.secho(f"      {bullet} {label} {dots}{timing}{suffix}")


def _warmup_step_fail(label, elapsed, error=""):
    bullet = click.style("✗", fg="red", bold=True)
    dots = "." * max(2, 48 - len(label))
    timing = f" {elapsed:6.2f}s" if elapsed is not None else " " * 8
    suffix = f"  {error}" if error else ""
    click.secho(f"      {bullet} {label} {dots}{timing}{suffix}", fg="red")


def _warmup_progress(done, total, elapsed, ok=True, note=""):
    width = 28
    filled = int(width * done / max(1, total))
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * done / max(1, total))
    bar_styled = click.style(bar, fg="green" if ok else "red")
    status = (
        click.style("ok ", fg="green") if ok else click.style("err", fg="red")
    )
    click.secho(
        f"      [{bar_styled}] {done:>2}/{total:<2} {pct:>3}%  "
        f"{elapsed:5.2f}s  {status} {note}".rstrip()
    )


def pregenerate_assets_if_web():
    """Public wrapper: only run pre-generation in the web role.

    Cron/queuejob workers don't render HTML, so they have no asset bundles
    to pre-warm. is_odoo_cronjob / is_odoo_queuejob are set by run.py via
    role-specific env vars.
    """
    if is_odoo_cronjob or is_odoo_queuejob:
        return
    _pregenerate_assets()


def _pregenerate_assets():
    """Pre-generate all known asset bundles in a single subprocess.

    Must be called BEFORE the odoo workers fork. Each worker caches its
    asset-bundle lookups in-process forever (ormcache_context on
    ir.qweb._generate_asset_nodes_cache). If we generate bundles after
    the fork, workers still serve their own stale cached URLs even though
    the new attachments are in the DB. Running pre-gen here means every
    worker inherits the same committed state at fork time and never has to
    create its own copy on first render.

    Opt-in: set ODOO_WARMUP_PREGENERATE=1 to enable. ODOO_WARMUP_BUNDLES
    overrides the bundle set as a comma-separated list.
    """
    global _WARMUP_T0
    _WARMUP_T0 = time.time()

    if os.getenv("ODOO_WARMUP_PREGENERATE", "0") != "1":
        _warmup_banner("Odoo warm-up — caches & workers")
        _warmup_phase(1, 3, "Pre-generating asset bundles")
        _warmup_step_ok("skipped (opt-in: set ODOO_WARMUP_PREGENERATE=1)")
        return
    bundles = [
        b.strip()
        for b in os.getenv("ODOO_WARMUP_BUNDLES", ASSET_BUNDLES_DEFAULT).split(
            ","
        )
        if b.strip()
    ]
    if not bundles:
        _warmup_banner("Odoo warm-up — caches & workers")
        _warmup_phase(1, 3, "Pre-generating asset bundles")
        _warmup_step_ok("no bundles configured")
        return

    _warmup_banner("Odoo warm-up — caches & workers")
    _warmup_phase(1, 3, f"Pre-generating {len(bundles)} asset bundles")
    for b in bundles:
        click.secho(f"        · {b}", dim=True)

    bundle_list_repr = repr(bundles)
    script = (
        "import time as _t\n"
        "bundles = " + bundle_list_repr + "\n"
        "for _b in bundles:\n"
        "    _start = _t.time()\n"
        "    try:\n"
        "        env['ir.qweb']._get_asset_link_urls(_b)\n"
        "        env['ir.qweb']._get_asset_nodes(_b)\n"
        "        print(f'>>WARMUP_BUNDLE_OK {_b} {_t.time()-_start:.3f}')\n"
        "    except Exception as _e:\n"
        "        print(f'>>WARMUP_BUNDLE_FAIL {_b} {_t.time()-_start:.3f} {_e}')\n"
        "env.cr.commit()\n"
        "print('>>WARMUP_BUNDLE_DONE', len(bundles))\n"
    )
    t0 = time.time()
    try:
        proc = subprocess.Popen(
            ["/odoolib/shell.py", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        timeout_s = int(os.getenv("ODOO_WARMUP_PREGEN_TIMEOUT", "300"))
        deadline = t0 + timeout_s
        tail = []  # last lines for error reporting if rc != 0
        ok_count = 0
        fail_count = 0
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                tail.append(line)
                if len(tail) > 50:
                    tail.pop(0)
                if line.startswith(">>WARMUP_BUNDLE_OK "):
                    _, name, secs = line.split(" ", 2)
                    ok_count += 1
                    _warmup_step_ok(name, float(secs))
                elif line.startswith(">>WARMUP_BUNDLE_FAIL "):
                    parts = line.split(" ", 3)
                    fail_count += 1
                    name = parts[1] if len(parts) > 1 else "?"
                    secs = float(parts[2]) if len(parts) > 2 else 0.0
                    err = parts[3] if len(parts) > 3 else ""
                    _warmup_step_fail(name, secs, err)
                elif line.startswith(">>WARMUP_BUNDLE_DONE"):
                    pass
                # else: drop shell.py / odoo loader output to keep the view clean
                if time.time() > deadline:
                    proc.kill()
                    raise TimeoutError(f"pre-gen exceeded {timeout_s}s")
            proc.wait(timeout=5)
        except TimeoutError:
            click.secho(
                f"      ⏱ Asset pre-generation timed out after {timeout_s}s",
                fg="yellow",
            )
            return
        elapsed = time.time() - t0
        if proc.returncode != 0:
            click.secho(
                f"      ⚠ pre-gen exited rc={proc.returncode} — last output:",
                fg="yellow",
            )
            for line in tail[-10:]:
                click.secho(f"        {line}", fg="yellow")
        else:
            summary = f"{ok_count} ok"
            if fail_count:
                summary += f", {fail_count} failed"
            click.secho(
                f"      ► all bundles processed in {elapsed:.2f}s ({summary})",
                fg="green",
                bold=True,
            )
    except Exception as e:
        # Never block startup over warmup
        click.secho(f"      ⚠ Asset pre-generation crashed: {e}", fg="yellow")


def _touch():
    global _WARMUP_T0
    if _WARMUP_T0 is None:
        # _touch may run without pre-gen (env opted out) — establish T0 here.
        _WARMUP_T0 = time.time()
        _warmup_banner("Odoo warm-up — caches & workers")

    INTERNAL_ODOO_PORT = os.getenv("INTERNAL_ODOO_PORT", "8069")
    ODOO_WORKERS_WEB = int(
        os.getenv("MAX_WARMUP_WORKERS", os.getenv("ODOO_WORKERS_WEB", "1"))
    )

    WARMUP_PATH = os.getenv("ODOO_WARMUP_PATH", "/web/login")
    if not WARMUP_PATH.startswith("/"):
        WARMUP_PATH = "/" + WARMUP_PATH
    url = f"http://localhost:{INTERNAL_ODOO_PORT}{WARMUP_PATH}"

    # Einstellbar:
    # Default 1 (sequential): parallel HTTP warmup against a multi-worker
    # Odoo races bundle generation across workers. See note in the warmup
    # loop below. Set MAX_PARALLEL_WARMUP>1 to re-enable parallelism.
    MAX_PARALLEL_WARMUP = int(os.getenv("MAX_PARALLEL_WARMUP", "1"))
    READY_TIMEOUT_S = float(
        os.getenv("ODOO_READY_TIMEOUT_S", "60")
    )  # wie lange auf "Odoo lebt" warten
    READY_INTERVAL_S = float(
        os.getenv("ODOO_READY_INTERVAL_S", "0.5")
    )  # Poll-Intervall
    WARMUP_REQUESTS = int(
        os.getenv("ODOO_WARMUP_REQUESTS", str(ODOO_WORKERS_WEB))
    )  # wie viele GETs insgesamt
    PER_REQUEST_RETRIES = int(os.getenv("ODOO_WARMUP_RETRIES", "3"))
    REQUEST_TIMEOUT_S = float(os.getenv("ODOO_REQUEST_TIMEOUT_S", "55"))

    def wait_until_tcp_ready():
        """Wait only for the Odoo TCP port to open — DOES NOT make an HTTP
        request. Issuing an HTTP request here would trigger asset bundle
        generation inside a worker before our single-threaded pre-generation
        had a chance to run, defeating the whole point of pre-generating."""
        t0 = time.time()
        try:
            wait_for_tcp(
                "localhost",
                int(INTERNAL_ODOO_PORT),
                timeout=READY_TIMEOUT_S,
                interval=READY_INTERVAL_S,
            )
        except Exception as e:
            _warmup_step_fail(
                f"TCP localhost:{INTERNAL_ODOO_PORT}", time.time() - t0, str(e)
            )
            raise
        _warmup_step_ok(
            f"TCP localhost:{INTERNAL_ODOO_PORT}", time.time() - t0
        )

    def wait_until_http_ready():
        """After pre-gen has committed bundles, confirm HTTP actually works."""
        deadline = time.time() + READY_TIMEOUT_S
        last_ex = None
        t0 = time.time()
        while time.time() < deadline:
            try:
                r = requests.get(url, timeout=REQUEST_TIMEOUT_S)
                r.raise_for_status()
                size_kb = len(r.content) / 1024.0
                _warmup_step_ok(
                    f"HTTP {WARMUP_PATH}",
                    time.time() - t0,
                    extra=f"{r.status_code}  {size_kb:.0f} KB",
                )
                return
            except Exception as e:
                last_ex = e
                time.sleep(READY_INTERVAL_S)
        _warmup_step_fail(
            f"HTTP {WARMUP_PATH}", time.time() - t0, str(last_ex)
        )
        raise RuntimeError(
            f"Odoo not reachable after {READY_TIMEOUT_S}s: {last_ex}"
        )

    def warmup_once(request_id: int):
        """Returns (elapsed, error) — never raises so the caller can render
        a progress line per request without try/except dance."""
        last_ex = None
        t0 = time.time()
        for _ in range(PER_REQUEST_RETRIES):
            try:
                r = requests.get(url, timeout=REQUEST_TIMEOUT_S)
                r.raise_for_status()
                return time.time() - t0, None
            except Exception as e:
                last_ex = e
                time.sleep(0.2)
        return time.time() - t0, last_ex

    # 1) Wait only for TCP — must NOT make an HTTP request here, otherwise
    #    a worker generates bundles before pre-gen.
    _warmup_phase(2, 3, f"Probing Odoo HTTP ({url})")
    wait_until_tcp_ready()

    # 2) HTTP readiness probe (bundles were pre-generated by run.py BEFORE
    #    odoo workers forked, so all workers inherit the same DB state).
    wait_until_http_ready()

    # 3) warmup in kontrollierter Parallelität
    # Sequential per default: parallel HTTP warmup against a multi-worker
    # web has each worker generate its own copy of any not-yet-cached asset
    # bundle, producing duplicate ir.attachment rows and intermittent 404s
    # when the browser hits an id that another worker has just replaced.
    # Sequential lets the first worker commit, the rest find existing rows.
    # Override with MAX_PARALLEL_WARMUP > 1 if you really want the old
    # behaviour.
    sequential = MAX_PARALLEL_WARMUP <= 1
    mode = "sequential" if sequential else f"parallel x{MAX_PARALLEL_WARMUP}"
    _warmup_phase(
        3,
        3,
        f"Warming up {WARMUP_REQUESTS} worker cache slot(s) — {mode}",
    )

    for attempt in range(3):
        if attempt > 0:
            click.secho(
                f"      ↻ retry {attempt + 1}/3 after partial failure",
                fg="yellow",
            )

        failed = []
        phase_t0 = time.time()
        done = 0

        if sequential:
            for i in range(WARMUP_REQUESTS):
                elapsed, err = warmup_once(i)
                done += 1
                if err:
                    failed.append(err)
                    _warmup_progress(
                        done,
                        WARMUP_REQUESTS,
                        elapsed,
                        ok=False,
                        note=f"req #{i + 1}  {err}",
                    )
                else:
                    _warmup_progress(
                        done,
                        WARMUP_REQUESTS,
                        elapsed,
                        ok=True,
                        note=f"req #{i + 1}",
                    )
        else:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WARMUP) as ex:
                futures = {
                    ex.submit(warmup_once, i): i
                    for i in range(WARMUP_REQUESTS)
                }
                for f in as_completed(futures):
                    i = futures[f]
                    elapsed, err = f.result()
                    done += 1
                    if err:
                        failed.append(err)
                        _warmup_progress(
                            done,
                            WARMUP_REQUESTS,
                            elapsed,
                            ok=False,
                            note=f"req #{i + 1}  {err}",
                        )
                    else:
                        _warmup_progress(
                            done,
                            WARMUP_REQUESTS,
                            elapsed,
                            ok=True,
                            note=f"req #{i + 1}",
                        )

        phase_elapsed = time.time() - phase_t0
        if not failed:
            click.secho(
                f"      ► all {WARMUP_REQUESTS} workers warm in "
                f"{phase_elapsed:.2f}s",
                fg="green",
                bold=True,
            )
            total = time.time() - _WARMUP_T0
            _warmup_banner(
                f"✓ Warm-up complete in {total:.2f}s — Odoo is hot",
                fg="green",
            )
            _signal_warmup_done()
            return

        click.secho(
            f"      ✗ attempt {attempt + 1}/3 had {len(failed)} failure(s)",
            fg="yellow",
        )
        if attempt == 2:
            for e in failed[:10]:  # nicht unendlich spam
                click.secho(f"        {e}", fg="red")
            total = time.time() - _WARMUP_T0
            _warmup_banner(
                f"⚠ Warm-up degraded after {total:.2f}s — releasing gate",
                fg="yellow",
            )
            # Even on failure mark warmup as 'done' so the supervisor stops
            # blocking cronjobs/queuejobs forever. They will see a degraded
            # web but at least background work resumes.
            _signal_warmup_done(failed=True)
            sys.exit(1)

        time.sleep(1.0)  # kurzer backoff vor nächstem attempt


WARMUP_DONE_SENTINEL = "/var/run/zodoo-warmup.done"
WARMUP_FAILED_SENTINEL = "/var/run/zodoo-warmup.failed"
# Shared with the bundled nginx proxy via the proxy_exchange volume. Mounted
# at /var/run/proxy_exchange in the odoo container (see docker-compose.yml)
# and at /var/proxy_exchange in the proxy container. The proxy polls this
# file once per second; while it exists, browsers get a maintenance page and
# API clients are held inside the proxy until it disappears.
WARMUP_IN_PROGRESS_SENTINEL = "/var/run/proxy_exchange/warmup_in_progress"


def set_warmup_in_progress():
    """Touch the proxy-gate sentinel so the bundled nginx proxy returns a
    maintenance page / holds API requests for external clients while we warm
    up.

    No-op for cron/queuejob roles.

    HARD GUARANTEE: this function NEVER raises. Standalone Odoo deployments
    (e.g. AWS) ship without the zodoo proxy and without /var/run/proxy_exchange
    mounted — in that case the touch silently fails (warning logged) and the
    rest of the warmup proceeds normally. The proxy gate is a best-effort
    optimization, never a hard dependency.
    """
    if is_odoo_cronjob or is_odoo_queuejob:
        return
    p = Path(WARMUP_IN_PROGRESS_SENTINEL)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    except Exception as e:
        click.secho(
            f"[warmup gate] could not touch {p} — external port will NOT be "
            f"gated (no zodoo proxy / standalone deployment): {e}",
            fg="yellow",
        )


def _signal_warmup_done(failed=False):
    """Write a sentinel file so the supervisor can gate cronjobs/queuejobs.

    On success: touches WARMUP_DONE_SENTINEL.
    On exhausted retries: touches WARMUP_FAILED_SENTINEL (the supervisor
    treats both as 'release the gate' so background work doesn't hang).

    Also clears the proxy-gate sentinel so external traffic is released
    (also in the failure path — degraded web is better than no web).
    """
    path = WARMUP_FAILED_SENTINEL if failed else WARMUP_DONE_SENTINEL
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(str(int(time.time())))
    except Exception as e:
        click.secho(
            f"Could not write warmup sentinel {path}: {e}", fg="yellow"
        )
    try:
        Path(WARMUP_IN_PROGRESS_SENTINEL).unlink(missing_ok=True)
    except Exception as e:
        click.secho(f"Could not clear warmup gate sentinel: {e}", fg="yellow")


def set_proxy_update_modules(enabled):
    p = Path("/var/run/proxy_exchange/odoo_update")
    if p.parent.exists():
        p.write_text("1" if enabled else "0")
        p.chmod(0o666)
