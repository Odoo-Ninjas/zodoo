#!/opt/zodoo_pipx/venvs/zodoo/bin/python3
"""Runs Odoo's own `odoo-bin neutralize` against the project database.

Odoo executes the data/neutralize.sql of every installed module (base: crons,
mail servers, webhooks, ...; payment, iap, mail, calendars, ...) and sets
database.is_neutralized. Available since Odoo 16.0.
"""

import sys
from tools import exec_odoo
from tools import prepare_run

prepare_run()

rc, _ = exec_odoo(
    "config_shell",
    command="neutralize",
    dokill=False,
)
sys.exit(rc)
