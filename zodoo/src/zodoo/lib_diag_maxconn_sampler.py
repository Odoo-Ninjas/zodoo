"""CLI proxy to the in-container diag_maxconn_sampler.py.

The actual sampler is mounted into the cronjobs container at
/usr/local/bin/diag_maxconn_sampler.py and is also driven by a CRONJOB_*
env var. This command lets you read the recorded peaks from the host:

    odoo diag-maxconn-sampler            # show peaks + latest
    odoo diag-maxconn-sampler -n 30      # show last 30 rows
    odoo diag-maxconn-sampler sample     # take an extra sample now
"""
import subprocess
import sys

import click

from .cli import cli, pass_config, Commands
from .tools import ensure_project_name


@cli.command(
    name="diag-maxconn-sampler",
    help="Show pg_stat_activity samples collected by the cronjobs container.",
)
@click.argument(
    "subcommand",
    required=False,
    default="show",
    type=click.Choice(["show", "sample"]),
)
@click.option("-n", "--last", default=10, help="Show last N rows (show only).")
@pass_config
def diag_maxconn_sampler(config, subcommand, last):
    ensure_project_name(config)
    container = f"{config.project_name}_cronjobs"
    args = [
        "docker", "exec", container,
        "python3", "/usr/local/bin/diag_maxconn_sampler.py", subcommand,
    ]
    if subcommand == "show":
        args += ["-n", str(last)]
    sys.exit(subprocess.call(args))


Commands.register(diag_maxconn_sampler)
