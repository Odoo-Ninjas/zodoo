from contextlib import contextmanager
from collections import Counter
import shutil
import tempfile

try:
    import arrow
except Exception:
    arrow = None
from collections import OrderedDict
from . import click
import ast
import json
from pathlib import Path
import os
from .tools import abort
from .tools import am_i_inside_docker_container
from .tools import on_osx, on_windows_wsl

try:
    import psycopg2
except Exception:
    pass


def get_odoo_addons_paths(
    relative=False, no_extra_addons_paths=False, additional_addons_paths=False
):
    m = MANIFEST()
    c = customs_dir()
    res = []
    addons_paths = m["addons_paths"]
    if additional_addons_paths:
        addons_paths += additional_addons_paths

    odoo_dir = m.odoo_dir

    if current_version() <= 9.0:
        MUST = ["odoo/openerp/addons", "odoo/addons"]
    else:
        MUST = [f"{odoo_dir}/odoo/addons", f"{odoo_dir}/addons"]
    for must in reversed(MUST):
        if must in addons_paths:
            continue
        addons_paths.insert(0, must)

    for x in addons_paths:
        if no_extra_addons_paths:
            if x not in MUST:
                continue
        if relative:
            res.append(x)
        else:
            res.append(c / x)

    return res


def customs_dir():
    env_customs_dir = os.getenv("CUSTOMS_DIR") or os.getenv("HOST_CUSTOMS_DIR")
    if not env_customs_dir:
        manifest_file = Path(os.getcwd()) / "MANIFEST"
        if manifest_file.exists():
            return manifest_file.parent
        else:
            here = Path(os.getcwd())
            while not (here / "MANIFEST").exists():
                here = here.parent
                if here.parent == here:
                    break
            if (here / "MANIFEST").exists():
                return here

            click.secho("no MANIFEST file found in current directory.")
    if not env_customs_dir:
        return None
    return Path(env_customs_dir)


def plaintextfile():
    path = customs_dir() / ".odoo.ast"
    return path


def _read_file(path, default=None):
    try:
        with open(path) as f:
            return (f.read() or "").strip()
    except Exception:
        return default


def MANIFEST_FILE():
    _customs_dir = customs_dir()
    if not _customs_dir:
        return None
    return _customs_dir.resolve().absolute() / "MANIFEST"


class MANIFEST_CLASS:
    def __init__(self):
        self.path = MANIFEST_FILE()

        self._apply_defaults()

    def _apply_defaults(self):
        d = self._get_data()
        d.setdefault("modules", [])
        # patches ?

        self.patch_dir = customs_dir() / "patches"

        if "version" in d:
            try:
                self["version"] = float(d["version"])
            except Exception:
                pass

    def _get_data(self):
        content = self.path.read_text() or "{}"
        try:
            res = OrderedDict(ast.literal_eval(content))
        except Exception:
            abort(f"Could not parse {content}")

        system_addons_paths = res.get("addons_paths_system", [])
        if system_addons_paths:
            res["addons_paths"] = system_addons_paths + res.get(
                "addons_paths", []
            )
        return res

    def __getitem__(self, key):
        data = self._get_data()
        return data[key]

    def get(self, key, default):
        return self._get_data().get(key, default)

    def __setitem__(self, key, value):
        data = self._get_data()
        data[key] = value
        self._update(data)

    def _update(self, d):
        if "install" in d:
            d["install"] = list(sorted(set(d["install"])))
        # remove the system addons path again
        system_addons_paths = d.get("addons_paths_system", [])
        if system_addons_paths:
            d["addons_paths"] = [
                p
                for p in d.get("addons_paths", [])
                if p not in system_addons_paths
            ]

        # safety net: never overwrite an existing non-trivial MANIFEST with
        # a near-empty one (we've seen this corrupt MANIFESTs in the wild).
        try:
            existing_content = self.path.read_text() or ""
            existing = (
                OrderedDict(ast.literal_eval(existing_content))
                if existing_content.strip()
                else {}
            )
        except Exception:
            existing = {}
        critical_keys = {"install", "addons_paths", "server-wide-modules"}
        existing_has_critical = bool(critical_keys & set(existing.keys()))
        new_has_critical = bool(critical_keys & set(d.keys()))
        if existing_has_critical and not new_has_critical:
            abort(
                f"Refusing to overwrite {self.path} with a minimal MANIFEST "
                f"(would drop keys: {sorted(set(existing.keys()) - set(d.keys()))}). "
                f"This protects against accidental MANIFEST truncation."
            )

        s = json.dumps(d, indent=4)
        fd, tmp = tempfile.mkstemp(suffix=".MANIFEST")
        try:
            os.chmod(tmp, 0o644)
            with os.fdopen(fd, "w") as fh:
                fh.write(s)
                fh.write("\n")
            shutil.move(tmp, MANIFEST_FILE())
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

        if len(set(d["addons_paths"])) != len(d["addons_paths"]):
            duplicates = [
                item
                for item, count in Counter(d["addons_paths"]).items()
                if count > 1
            ]
            abort(f"Addons Paths contains duplicate entries: {duplicates}")

    def rewrite(self):
        self._update(self._get_data())

    @property
    def odoo_dir(self):
        data = self._get_data()
        odoo_dir = data.get("odoo_dir", "odoo")
        return odoo_dir


def MANIFEST():
    return MANIFEST_CLASS()


cache_version = {}


def current_version():
    if cache_version.get("value") is None:
        cache_version["value"] = float(MANIFEST()["version"])
    return cache_version["value"]


def get_postgres_connection_params(force_inside_container=None):
    from .tools import _is_in_container

    config = get_settings()
    inside_container = (
        am_i_inside_docker_container()
        if force_inside_container is None
        else force_inside_container
    )
    if (
        not inside_container
        and not _is_in_container()
        and config.get("RUN_POSTGRES") == "1"
    ):
        host = Path(os.environ["HOST_RUN_DIR"]) / "postgres.socket"
        port = 0
        # on macos socket connection does not work
        if on_osx() or on_windows_wsl():
            host = "127.0.0.1"
            port = int(config["HOST_DB_PORT"])

    else:
        host = config["DB_HOST"]
        port = int(config.get("DB_PORT", "5432"))
    password = config["DB_PWD"]
    user = config["DB_USER"]
    return host, port, user, password


def get_settings():
    """
    Can run outside of host and inside host. Returns all values from
    composed settings file.
    """
    from .myconfigparser import MyConfigParser  # NOQA
    from .tools import _is_in_container

    if _is_in_container():
        settings_path = Path("/tmp/settings")
        content = ""
        for k, v in os.environ.items():
            v = v.replace("\n", " ")
            content += f"{k}={v}\n"
        try:
            settings_path.write_text(content)
            os.chmod(settings_path, 0o644)
        except PermissionError:
            pass  # Already written by root; env vars are identical via sudo -E
    else:
        settings_path = Path(os.environ["HOST_RUN_DIR"]) / "settings"
    myconfig = MyConfigParser(settings_path)
    return myconfig


def get_conn(db=None, host=None):
    config = get_settings()
    if db != "postgres":
        # Waiting until postgres is up: open a probe connection to the
        # default `postgres` database and close it via the autoclose
        # context manager. Previously the probe leaked one connection
        # per call (no .close() ever ran), which exhausted
        # `max_connections` after a few dozen invocations and surfaced
        # as `FATAL: sorry, too many clients already` during heavy
        # reset_db / update flows.
        with get_conn_autoclose(db="postgres"):
            pass

    host, port, user, password = get_postgres_connection_params()
    db = db or config["DBNAME"]
    connstring = f"dbname={db}"

    for combi in [
        ("password", password),
        ("host", host),
        ("port", port),
        ("user", user),
    ]:
        if combi[1]:
            connstring += f" {combi[0]}='{combi[1]}'"

    conn = psycopg2.connect(connstring)
    cr = conn.cursor()
    return conn, cr


@contextmanager
def get_conn_autoclose(*args, **kwargs):
    conn, cr = get_conn(*args, **kwargs)
    try:
        yield cr
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        cr.close()
        conn.close()


def _queue_job_installed():
    """Probe the project DB for an installed `queue_job` module.

    Returns True iff `ir_module_module` has a row with
    ``name = 'queue_job' AND state = 'installed'``.
    Fails soft (returns False) when:
      - the project DB does not exist yet (fresh build, before `db reset`),
      - `ir_module_module` does not exist yet (DB exists but `base` not
        installed),
      - postgres is unreachable for any other reason.

    The fail-soft behaviour matters because this probe runs at every odoo
    container start (server-wide-modules / supervisor role decisions); a
    hard failure here would block the container from coming up at all
    after every reboot of a not-yet-initialised project.
    """
    import psycopg2  # noqa: F401 — kept for backwards-compat call sites

    try:
        with get_conn_autoclose() as cr:
            cr.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'ir_module_module'"
            )
            if not cr.fetchone():
                return False
            cr.execute(
                "SELECT 1 FROM ir_module_module "
                "WHERE name = 'queue_job' AND state = 'installed' LIMIT 1"
            )
            return cr.fetchone() is not None
    except Exception:
        # Fail-soft: probe runs at every container start; a hard error
        # here would block the container from coming up at all on
        # not-yet-initialised projects (no DB), unreachable postgres,
        # or any odd pg state. Specific subclasses
        # (psycopg2.OperationalError, psycopg2.errors.UndefinedTable
        # via SQLSTATE 42P01) are all swallowed by this catch-all.
        return False


def translate_path_into_machine_path(path):
    path = customs_dir() / translate_path_relative_to_customs_root(path)
    return path


def translate_path_relative_to_customs_root(path):
    """
    The customs must contain a significant file named
    MANIFEST to indicate the root of the customs
    """

    cmf = MANIFEST_FILE().absolute().resolve().absolute()
    if not str(path).startswith("/"):
        return path

    try:
        path = path.resolve()
    except Exception:
        pass

    return path.relative_to(cmf.parent)


def manifest_file_names():
    result = "__manifest__.py"
    try:
        current_version()
    except Exception:
        pass
    else:
        if current_version() <= 10.0:
            result = "__openerp__.py"
        else:
            result = "__manifest__.py"
    return result
