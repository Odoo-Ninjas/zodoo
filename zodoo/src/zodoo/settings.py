import grp
import os
import click
import tempfile
from pathlib import Path
from contextlib import contextmanager
from .tools import whoami
from .tools import update_setting


def _get_settings_files(config):
    """
    Returns list of paths or files
    """
    customs_dir = config.WORKING_DIR

    if customs_dir:
        yield customs_dir / "settings"
    yield Path("/etc/odoo/settings")
    if config.project_name:
        yield Path(f"/etc/odoo/{config.project_name}/settings")
    yield customs_dir / ".odoo" / "settings"
    yield Path(os.environ["HOME"]) / ".odoo" / "settings"
    yield customs_dir / ".odoo" / "run" / "settings"


@contextmanager
def _get_settings(config, customs, quiet=False):
    from .myconfigparser import MyConfigParser  # NOQA

    files = _collect_settings_files(config, customs=None, quiet=quiet)
    fd, filename = tempfile.mkstemp(suffix=".")
    os.close(fd)
    _make_settings_file(filename, files)
    c = MyConfigParser(filename)
    try:
        yield c
    finally:
        Path(filename).unlink()


def get_docker_gid():
    try:
        return grp.getgrnam("docker").gr_gid
    except KeyError:
        # macOS (oder Linux ohne docker group)
        return os.getgid()


def _export_settings(config, forced_values):
    from .myconfigparser import MyConfigParser

    setting_files = _collect_settings_files(config)
    _make_settings_file(config.files["settings"], setting_files)
    # constants
    settings = MyConfigParser(config.files["settings"])
    if "OWNER_UID" not in settings.keys():
        settings["OWNER_UID"] = whoami(id=True)
    settings["DOCKER_GID"] = get_docker_gid()

    # forced values:
    for k, v in forced_values.items():
        settings[k] = v

    settings["ODOO_IMAGES"] = config.dirs["images"]

    _append_host_db_port(config, settings)

    settings.write()


def _append_host_db_port(config, settings):
    from .tools import on_osx, on_windows_wsl

    if on_osx() or on_windows_wsl():
        from .lib_setup import _next_port

        for name in ["HOST_DB_PORT", "DEBUG_PORT"]:
            if not settings.get(name):
                settings[name] = str(_next_port(config))
                update_setting(config, name, settings[name])


def _collect_settings_files(config, quiet=False):
    _files = []

    if config.dirs:
        _files.append(config.dirs["odoo_home"] / "defaults")
        # optimize
        for filename in config.dirs["images"].glob("**/default.settings"):
            _files.append(config.dirs["images"] / filename)
    if config.restrict.get("settings"):
        # System-wide settings (/etc/odoo/settings) are always merged in
        # front of the restricted file(s) so host-level overrides
        # (APT_PROXY_IP, PIP_PROXY_IP, …) still apply when a wrapper uses
        # -xs to pin a project-specific settings file.
        system_settings = config.files.get("system_settings") if config.files else None
        if system_settings and Path(system_settings).exists():
            _files.append(system_settings)
        _files += config.restrict["settings"]
    else:
        for dir in filter(lambda x: x.exists(), _get_settings_files(config)):
            if not quiet:
                click.secho(f"Searching for settings in: {dir}", fg="cyan")
            if dir.is_file():
                _files.append(dir)
            elif dir.is_dir():
                for file in dir.glob("settings*"):
                    if file.is_dir():
                        continue
                    _files.append(file)

        # _files.append(files['user_settings'])
        if config.files and "project_settings" in config.files:
            if config.files["project_settings"].exists():
                _files.append(config.files["project_settings"])
            else:
                click.secho(
                    "Hint: file for configuration can be used: {}".format(
                        config.files["project_settings"]
                    ),
                    fg="magenta",
                )

    if config.verbose:
        click.secho(
            "\n\nFound following extra settings files:\n", fg="cyan", bold=True
        )

        for file in _files:
            if not Path(file).exists():
                continue
            if not quiet:
                click.secho(
                    f">>>>>>>>>>>>>>>>>>> {file} <<<<<<<<<<<<<<<<<", fg="cyan"
                )
                click.secho(file.read_text())

    return _files


def _make_settings_file(outfile, setting_files):
    """
    Puts all settings into one settings file
    """
    from .myconfigparser import MyConfigParser

    c = MyConfigParser(outfile)
    for file in setting_files:
        if not file:
            continue
        c2 = MyConfigParser(file)
        c.apply(c2)

    # expand variables
    for key in list(c.keys()):
        value = c[key]
        if "~" in value:
            c[key] = os.path.expanduser(value)

    c.write()
