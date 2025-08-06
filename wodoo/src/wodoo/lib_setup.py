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


@cli.group(cls=AliasedGroup)
@pass_config
def setup(config):
    pass


@setup.command()
@pass_config
@click.pass_context
def next_port(ctx, config):
    PORTS = set()
    if config.PROXY_PORT and str(config.PROXY_PORT) != "80":
        click.secho(f"Port is already configured: {config.PROXY_PORT}")
        return
    # perhaps not reloaded:
    settings = config.files["project_settings"]
    content = ""
    if settings.exists():
        content = settings.read_text() if settings.exists() else ""
        if "PROXY_PORT=" in content and "PROXY_PORT=80" not in content:
            click.secho(f"Already configured: {content}")
            return

    parentfolder = config.dirs["user_conf_dir"]
    for file in parentfolder.glob("settings.*"):
        lines = [
            x
            for x in file.read_text().splitlines()
            if x.startswith("PROXY_PORT=")
        ]
        for line in lines:
            for port in re.findall(r"\d+", line):
                PORTS.add(int(port))
    port = max(PORTS) + 1
    settings.write_text(content + f"\nPROXY_PORT={port}\n")
    click.secho(
        f"Configured proxy port: {port}. Please reload and restart machines."
    )


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
    click.secho("Pulling wodoo from git repository...", fg='yellow')
    result = subprocess.run(
        [
            "git",
            "pull",
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


Commands.register(status)
