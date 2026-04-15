import os
import shutil
import sys
import tempfile
import click
import subprocess
import re
from pathlib import Path
from .tools import _askcontinue
from .tools import remove_webassets
from .cli import cli, pass_config, Commands
from .lib_clickhelpers import AliasedGroup
from .tools import abort
from .tools import is_git_clean
from .tools import on_osx, on_windows_wsl
from .tools import update_setting
from .tools import vscode_setting
from .tools import __assure_gitignore

ALL_PORTS = [
    "PROXY_PORT",
    "DEBUG_PORT",
    "HOST_DB_PORT",
    "ODOO_PYTHON_DEBUG_PORT",
]


@cli.group(
    cls=AliasedGroup,
    help="Setup and maintenance commands (ports, web assets, upgrade, status).",
)
@pass_config
def setup(config):
    pass


@setup.command(
    help="Find and assign the next free port for PROXY_PORT, DEBUG_PORT (and HOST_DB_PORT on macOS/WSL)."
)
@pass_config
@click.pass_context
def next_port(ctx, config):
    ports = list(x for x in ALL_PORTS)
    if not (on_osx() or on_windows_wsl()):
        ports.remove("HOST_DB_PORT")
    _setup_port(ctx, config, ports)


def _setup_port(ctx, config, required_ports):
    for required_port in required_ports:
        if (
            getattr(config, required_port)
            and str(getattr(config, required_port)) != "80"
        ):
            click.secho(
                f"Port {required_port} is already configured: {getattr(config, required_port)}"
            )
            continue
        # perhaps not reloaded:
        settings = config.files["project_settings"]
        content = ""
        if settings.exists():
            content = settings.read_text() if settings.exists() else ""
            # hacky...with =80
            if (
                f"{required_port}=" in content
                and "{required_port}=80" not in content
            ):
                click.secho(f"Already configured: {content}")
                return
        port = _next_port(config)
        update_setting(config, required_port, port)
        click.secho(
            f"Configured {required_port}: {port}. Please reload and restart machines."
        )


def _next_port(config):
    PORTS = {2000}  # usually starting with 1023
    parentfolder = config.dirs["user_conf_dir"]
    for file in parentfolder.glob("settings.*"):
        lines = [
            x
            for x in file.read_text().splitlines()
            if any(
                x.startswith(SETTING_NAME + "=") for SETTING_NAME in ALL_PORTS
            )
        ]
        for line in lines:
            for port in re.findall(r"\d+", line):
                PORTS.add(int(port))
    port = max(PORTS) + 1
    return port


@setup.command(name="remove-web-assets")
@pass_config
@click.pass_context
def remove_web_assets(ctx, config):
    """
    if odoo-web interface is broken (css, js) then purging the web-assets helps;
    they are usually recreated when admin login
    """
    from .odoo_config import current_version

    _askcontinue(config)
    conn = config.get_odoo_conn().clone(dbname=config.dbname)
    remove_webassets(conn)
    if current_version() <= 10.0:
        click.echo("Please login as admin, so that assets are recreated.")


@setup.command()
@pass_config
def status(config):
    _status(config)


def _status(config):
    color = "yellow"
    EXTERNAL_DOMAIN = config.EXTERNAL_DOMAIN
    if not EXTERNAL_DOMAIN:
        click.secho(
            "No external domain configured, please set: EXTERNAL_DOMAIN",
            fg="red",
        )
    click.secho("projectname: ", nl=False)
    click.secho(config.project_name, fg=color, bold=True)
    click.secho("version: ", nl=False)
    click.secho(config.odoo_version, fg=color, bold=True)
    click.secho("db: ", nl=False)
    click.secho(
        f"{config.dbname}@{config.db_host} (user: {config.db_user})",
        fg=color,
        bold=True,
    )
    if config.PROXY_PORT:
        click.secho("url: ", nl=False)
        click.secho(
            f"{EXTERNAL_DOMAIN}:{config.PROXY_PORT}", fg=color, bold=True
        )

    for key in [
        "DEFAULT_DEV_PASSWORD",
        "ODOO_DEMO",
        "ODOO_QUEUEJOBS_CHANNELS",
        "ODOO_QUEUEJOBS_CRON_IN_ONE_CONTAINER",
        "ODOO_CRON_IN_ONE_CONTAINER",
        "RUN_ODOO_CRONJOBS",
        "RUN_ODOO_QUEUEJOBS",
    ]:
        click.secho(f"{key}:", nl=False, fg=color)
        click.secho(getattr(config, key))

    msg_file = config.files["project_msg"]
    if msg_file.exists():
        msg = msg_file.read_text().strip()
        if msg:
            click.secho("")
            click.secho(msg, fg="cyan")


@setup.command(
    name="edit-msg", help="Edit the project message shown in status."
)
@pass_config
def edit_msg(config):
    msg_file = config.files["project_msg"]
    if not msg_file.exists():
        msg_file.parent.mkdir(parents=True, exist_ok=True)
        msg_file.write_text("")
    editor = os.environ.get("EDITOR", "vi")
    subprocess.call([editor, str(msg_file)])


def _show_changelog_since(images_dir, old_version):
    """Show changelog entries for versions newer than old_version using less."""
    changelog = images_dir / "CHANGELOG.md"
    if not changelog.exists() or not old_version:
        return

    lines = changelog.read_text().splitlines()
    collected = []
    for line in lines:
        # Match version headers like "## 0.12.0 — April 2026" or "## 0.7.0"
        m = re.match(r"^## (\S+)", line)
        if m:
            version = m.group(1)
            if version == old_version:
                break
        collected.append(line)

    # Strip leading blank lines and the "# Changelog" header
    while collected and (
        not collected[0].strip() or collected[0].startswith("# ")
    ):
        collected.pop(0)

    if not collected:
        return

    text = "\n".join(collected) + "\n"
    click.secho(f"\nChangelog since v{old_version}:\n", fg="green", bold=True)
    try:
        proc = subprocess.Popen(["less", "-R"], stdin=subprocess.PIPE)
        proc.communicate(input=text.encode())
    except (FileNotFoundError, BrokenPipeError):
        click.echo(text)


@click.option("-I", "--no-install", is_flag=True)
@setup.command(help="Upgrade zodoo")
@pass_config
@click.pass_context
def upgrade(ctx, config, no_install):

    stashed = False
    if not is_git_clean(config.dirs["images"]):
        click.secho("Stashing local changes...", fg="yellow")
        subprocess.run(
            ["git", "stash", "--include-untracked"],
            cwd=config.dirs["images"],
            check=True,
        )
        stashed = True

    try:
        version_file = config.dirs["images"] / "VERSION"
        old_version = (
            version_file.read_text().strip() if version_file.exists() else ""
        )

        click.secho("Pulling zodoo from git repository...", fg="yellow")
        result = subprocess.run(
            [
                "git",
                "pull",
                "--ff-only",
                "--no-edit",
                "--progress",
                "--rebase=false",
                "--autostash",
                "--quiet",
            ],
            cwd=config.dirs["images"],
            capture_output=True,
            encoding="utf-8",
            text=True,
            env={**os.environ, "LANG": "C", "LC_ALL": "C"},
        )

        output = result.stdout.strip() + result.stderr.strip()

        # Check for typical "no changes" messages
        if "Already up to date." in output or "Already up-to-date." in output:
            click.secho("No changes pulled; skipping reinstall.", fg="cyan")
        else:
            if not no_install:
                _reinstall()
            _show_changelog_since(config.dirs["images"], old_version)

        _update_gimera_src(config)
        _fix_permissions(config, [str(config.dirs["images"])])
    finally:
        if stashed:
            click.secho("Restoring stashed changes...", fg="yellow")
            subprocess.run(
                ["git", "stash", "pop"],
                cwd=config.dirs["images"],
                check=False,
            )


def _update_gimera_src(config):
    """Update the integrated gimera source unless it is in submodule mode."""
    import yaml

    zodoo_src = config.dirs["images"] / "zodoo" / "src"
    gimera_yml = zodoo_src / "gimera.yml"
    if not gimera_yml.exists():
        return
    data = yaml.safe_load(gimera_yml.read_text())
    for repo in data.get("repos", []):
        if repo.get("path") == "gimera_src":
            if repo.get("type") == "submodule":
                click.secho(
                    "gimera_src is in submodule mode - skipping update.",
                    fg="cyan",
                )
                return
            break
    else:
        return

    click.secho("Updating gimera source...", fg="yellow")
    python = sys.executable if Path(sys.executable).exists() else (shutil.which("python3") or "python3")
    env = {**os.environ, "PYTHONPATH": str(zodoo_src / "gimera_src")}
    subprocess.run(
        [
            python,
            "-m",
            "gimera.gimera",
            "apply",
            "gimera_src",
            "--update",
            "-I",
            "-C",
        ],
        cwd=zodoo_src,
        env=env,
        check=False,
    )


def _reinstall():
    images_dir = Path(os.path.expanduser("~/.odoo/images"))
    path = str(images_dir / "zodoo" / "src")
    for name in ["zodoo", "wodoo"]:
        try:
            subprocess.check_call(["pipx", "uninstall", name], shell=False)
        except subprocess.CalledProcessError:
            pass
    cmd = ["pipx", "install", "--force", "-e", path]
    if on_osx():
        python_version = (
            (images_dir / "darwin_python_version").read_text().strip()
        )
        cmd.extend(["--python", f"python{python_version}"])
    subprocess.check_call(cmd, shell=False)


@setup.command(help="Reinstall zodoo python")
def reinstall():
    _reinstall()


@setup.command(
    name="zodoo-tests",
    help="Run the zodoo unit-test suite. Use --slow to include heavy "
    "end-to-end tests that need Docker + gimera + network.",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
@click.option(
    "--slow",
    is_flag=True,
    help="Include @slow E2E tests (requires Docker, minutes to run).",
)
@click.pass_context
def zodoo_tests(ctx, slow):
    zodoo_src = Path(os.path.expanduser("~/.odoo/images/zodoo/src"))
    if not (zodoo_src / "pytest.ini").exists():
        abort(f"pytest.ini not found in {zodoo_src}")

    cmd = [sys.executable, "-m", "pytest"]
    if slow:
        cmd += ["-m", "slow"]
    else:
        cmd += ["-m", "not slow"]
    cmd += ctx.args
    click.secho(f"Running: {' '.join(cmd)}", fg="yellow")
    rc = subprocess.run(cmd, cwd=zodoo_src).returncode
    sys.exit(rc)


@setup.command()
@click.argument("lines")
def produce_test_lines(lines):
    import lorem

    lines = int(lines)
    for i in range(lines):
        click.secho(lorem.paragraph())


@setup.command()
@pass_config
@click.option(
    "-o", "--old", is_flag=True, help="Uses old setuptools - odoo version 11"
)
@click.pass_context
def setup_pyenv(ctx, config, old):
    _setup_robo_pyenv(ctx, config)
    # _setup_odoo_pyenv(ctx, config, old)


def is_robot_env_installed(config):
    return _is_pyenv_installed("zodoo-robot")


def _is_pyenv_installed(name):
    path = Path(os.path.expanduser(f"~/.pyenv/versions/{name}"))
    if path.exists():
        return str(path / "bin" / "python")


def _setup_odoo_pyenv(ctx, config, old):
    raise Exception("outdated")
    from .odoo_config import MANIFEST

    name = config.project_name
    from .odoo_config import customs_dir

    SRC = customs_dir()
    python_version = config.ODOO_PYTHON_VERSION
    python_version_int = tuple(map(int, python_version.split(".")))
    python_version_int2 = python_version_int[:2]
    reqfile = SRC / "requirements.txt.all"
    manifest = MANIFEST()

    if python_version_int2 < (3, 11):
        old = True
        click.secho(
            f"Warning: Python {python_version} < 3.11 --> old modus is set (cython<3, setuptools<55).",
            fg="red",
        )
    if manifest["version"] <= 16.0:
        if not old:
            click.secho(
                "Warning: Odoo version <= 16.0 is not compatible with latest setuptools, using old setuptools and cython versions. Use --old to suppress this warning.",
                fg="red",
            )
    pyexec = _setup_pyenv(ctx, config, name, old, reqfile, python_version)
    vscode_setting("python.pythonPath", str(pyexec))
    vscode_setting("python.defaultInterpreterPath", str(pyexec))

    (SRC / ".python-version").write_text(name)
    __assure_gitignore(SRC / ".gitignore", ".python-version")


def _setup_robo_pyenv(ctx, config):
    name = "zodoo-robot"
    python_version = "3.12.11"
    pyexec = _setup_pyenv(
        ctx,
        config,
        name,
        False,
        config.dirs["images"] / "robot" / "requirements.txt",
        python_version,
    )
    vscode_setting("robotcode.python", str(pyexec))


def _setup_pyenv(ctx, config, name, old, reqfile, python_version):
    from .tools import require_homebrew

    require_homebrew()

    if on_osx():
        subprocess.run(
            [
                "brew",
                "install",
                "pyenv-virtualenv",
                "libpq",
                "libxml2",
                "libxslt",
                "zlib",
                "freetype",
                "jpeg",
                "libpng",
                "openjpeg",
                "libtiff",
                "webp",
                "little-cms2",
                "postgresql",
            ],
            check=True,
        )

    click.secho(f"Setting up pyenv {name} {python_version}...", fg="yellow")

    subprocess.run(["pyenv", "uninstall", "-f", name], check=True)
    subprocess.run(["pyenv", "install", "-s", python_version], check=True)
    subprocess.run(
        ["pyenv", "virtualenv", python_version, name],
        check=True,
    )
    pyexec = os.path.expanduser(f"~/.pyenv/versions/{name}/bin/python")

    with tempfile.TemporaryDirectory() as tmpdir:
        subdir = Path(tmpdir) / "wheels"
        if old:
            subprocess.run(
                [
                    pyexec,
                    "-mpip",
                    "install",
                    "-U",
                    "setuptools<55.0.0",
                    "cython<3",
                    "wheel",
                    "pip",
                ],
                check=True,
            )
        else:
            subprocess.run(
                [
                    pyexec,
                    "-mpip",
                    "install",
                    "-U",
                    "setuptools",
                    "cython",
                    "wheel",
                    "pip",
                ],
                check=True,
            )
        subprocess.run(
            [
                pyexec,
                "-mpip",
                "wheel",
                "--no-build-isolation",
                "--prefer-binary",
                "-r",
                str(reqfile),
                "-w",
                str(subdir),
            ],
            check=True,
        )
        subprocess.run(
            [
                pyexec,
                "-mpip",
                "install",
                "--no-build-isolation",
                "--no-index",
                "--find-links",
                str(subdir),
                "-r",
                str(reqfile),
            ],
            check=True,
        )

        # install binary version of psyco - better on platforms
        try:
            version = _get_package_version(pyexec, "psycopg2")
        except (FileNotFoundError, subprocess.CalledProcessError):
            version = _get_package_version(pyexec, "psycopg2-binary")
        if version >= (2, 9, 0):
            subprocess.run(
                [pyexec, "-mpip", "uninstall", "-y", "psycopg2"], check=True
            )
            subprocess.run(
                [
                    pyexec,
                    "-mpip",
                    "install",
                    f"psycopg2-binary=={'.'.join(map(str, version))}",
                ],
                check=True,
            )

    click.secho(f"Pyenv setup done at {pyexec}", fg="green")
    return pyexec


def _get_package_version(python, name):
    psyco = (
        subprocess.run(
            [python, "-mpip", "show", name],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )
    version = None
    for line in psyco:
        if line.startswith("Version:"):
            version = line.split(":", 1)[1].strip()
            version = tuple(int(x) for x in version.split("."))
            return version
    else:
        raise FileNotFoundError(f"Package {name} not found.")


def _fix_permissions(config, dirs_to_fix):
    uid = config.owner_uid
    if not uid:
        return

    for path in dirs_to_fix:
        if not os.path.exists(path):
            click.secho(f"Skipping (does not exist): {path}", fg="red")
            continue

        click.secho(f"Fixing {path} to {uid} ...", fg="yellow")
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{path}:{path}",
            "ubuntu:22.04",
            "find",
            path,
            "-not",
            "-type",
            "l",
            "-not",
            "-user",
            str(uid),
            "-exec",
            "chown",
            str(uid),
            "{}",
            "+",
        ]
        try:
            subprocess.check_call(cmd)
            click.secho(f"  OK: {path}", fg="green")
        except subprocess.CalledProcessError as ex:
            click.secho(f"  FAILED: {path}: {ex}", fg="red")


@setup.command(
    help="Fix directory permissions via a Docker container (no sudo needed)."
)
@click.argument("paths", required=False, nargs=-1)
@pass_config
def fix_permissions(config, paths):
    if paths:
        dirs_to_fix = [os.path.abspath(os.path.expanduser(p)) for p in paths]
    else:
        dirs_to_fix = []
        for key in ["images", "run", "odoo_data_dir", "user_conf_dir"]:
            p = config.dirs.get(key)
            if p:
                p = str(p)
                if os.path.exists(p):
                    dirs_to_fix.append(p)

    if not dirs_to_fix:
        raise click.ClickException("No directories found to fix.")

    _fix_permissions(config, dirs_to_fix)


Commands.register(status)
Commands.register(fix_permissions)
Commands.register(edit_msg)
