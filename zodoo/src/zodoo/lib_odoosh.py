import click
from .cli import cli, pass_config
from .lib_clickhelpers import AliasedGroup


@cli.group(cls=AliasedGroup)
@pass_config
def odoosh(config):
    pass


@odoosh.command(name="export")
@click.argument("ssh", required=True)
@pass_config
def fetch(config, ssh):
    pass
