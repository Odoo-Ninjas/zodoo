import os
import click
import sys
import subprocess
import re
from .tools import _askcontinue
from .tools import remove_webassets
from .cli import cli, pass_config, Commands
from .lib_clickhelpers import AliasedGroup
from .tools import __try_to_set_owner
from .tools import whoami
from .tools import abort
from .tools import is_git_clean
from .tools import on_osx, on_windows_wsl
from .tools import __rmtree
from .tools import update_setting
from .tools import vscode_setting

ALL_PORTS = ["PROXY_PORT", "DEBUG_PORT", "HOST_DB_PORT"]

@cli.group(cls=AliasedGroup)
@pass_config
def setup(config):
    pass


@setup.command()
@pass_config
@click.pass_context
def next_port(ctx, config):
    ports = ["PROXY_PORT", "DEBUG_PORT" ]
    if on_osx() or on_windows_wsl():
        ports += ["HOST_DB_PORT"]
    _setup_port(ctx, config, ports)

def _setup_port(ctx, config, required_ports):
    for required_port in required_ports:
        if getattr(config, required_port) and str(getattr(config, required_port)) != "80":
            click.secho(f"Port is already configured: {getattr(config, required_port)}")
            continue
        # perhaps not reloaded:
        settings = config.files["project_settings"]
        content = ""
        if settings.exists():
            content = settings.read_text() if settings.exists() else ""
            # hacky...with =80
            if f"{required_port}=" in content and "{required_port}=80" not in content:
                click.secho(f"Already configured: {content}")
                return
        port = _next_port(config)
        update_setting(config, required_port, port)
        click.secho(
            f"Configured {required_port}: {port}. Please reload and restart machines."
        )

def _next_port(config):
    PORTS = set((2000,))  # usually starting with 1023
    parentfolder = config.dirs["user_conf_dir"]
    for file in parentfolder.glob("settings.*"):
        lines = [
            x
            for x in file.read_text().splitlines()
            if any(x.startswith(SETTING_NAME + "=") for SETTING_NAME in ALL_PORTS)
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


@click.option('-I', '--no-install', is_flag=True)
@setup.command(help="Upgrade wodoo")
@pass_config
@click.pass_context
def upgrade(ctx, config, no_install):

    if not is_git_clean(config.dirs["images"]):
        abort(f"Directory {config.dirs['images']} is not clean, please commit or stash your changes before upgrading.")

    click.secho("Pulling wodoo from git repository...", fg='yellow')
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        text=True,
        env={**os.environ, "LANG": "C", "LC_ALL": "C"},
    )

    output = result.stdout.strip() + result.stderr.strip()

    # Check for typical "no changes" messages
    if "Already up to date." in output or "Already up-to-date." in output:
        click.secho("No changes pulled; skipping reinstall.", fg='cyan')
    else:
        if not no_install:
            _reinstall()
    __try_to_set_owner(whoami(), config.dirs['images'], abort_if_failed=False)

def _reinstall():
    path = os.path.expanduser("~/.odoo/images/wodoo/src")
    try:
        subprocess.check_call(["pipx", "uninstall", "wodoo"], shell=False)
    except subprocess.CalledProcessError:
        pass
    subprocess.check_call(["pipx", "install", "--force", "-e", path], shell=False)

@setup.command(help="Reinstall wodoo python")
def reinstall():
    _reinstall()


@setup.command()
@click.argument("lines")
def produce_test_lines(lines):
    import lorem

    lines = int(lines)
    for i in range(lines):
        click.secho(lorem.paragraph())


@setup.command()
@pass_config
@click.pass_context
def setup_pyenv(ctx, config):
    from .tools import require_homebrew
    require_homebrew()
    click.secho("Setting up pyenv...", fg="yellow")
    from .odoo_config import customs_dir
    SRC = customs_dir()
    d = config.dirs['pyenv']
    if d.exists():
        __rmtree(config, d)
    from .tools import get_best_python
    python = get_best_python(config.ODOO_PYTHON_VERSION_SHORT)

    d.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([python, "-mvenv", str(d)], check=True)

    subprocess.run(["brew", "install", "libpq"], check=True)
    subprocess.run([d / 'bin/python3', '-m', 'pip', 'install', '-r', SRC / 'requirements.txt.all'], check=True)
    subprocess.run([d / 'bin/python3', '-m', 'pip', 'uninstall', '-y', 'psycopg2'], check=True)
    subprocess.run([d / 'bin/python3', '-m', 'pip', 'install','psycopg2-binary'], check=True)
    click.secho("Pyenv setup done.", fg="green")

    vscode_setting("python.defaultInterpreterPath", str(d / 'bin' / 'python3'))
    vscode_setting("robot.pythonPath", str(d / 'bin' / 'python3'))


Commands.register(status)
