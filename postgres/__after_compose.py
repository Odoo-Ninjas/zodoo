import re
import base64
import click
import yaml
import inspect
import os
from pathlib import Path
import shutil

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)


def after_compose(config, settings, yml, globals):
    # set postgres version
    V = settings["POSTGRES_VERSION"]
    if "postgres" in yml["services"] and yml["services"]["postgres"].get("build"):
        yml["services"]["postgres"]["build"]["dockerfile"] = f"Dockerfile.{V}"

    # if a named postgres volume is used, make it as external with name
    if settings["NAMED_ODOO_POSTGRES_VOLUME"]:
        yml["volumes"]["odoo_postgres_volume"] = {
            "external": True,
            "name": settings["NAMED_ODOO_POSTGRES_VOLUME"],
        }

    candidates = {
        '/config1': "~/.odoo/postgres.conf",
        '/config2': f"~/.odoo/{settings['PROJECT_NAME']}/postgres.conf",
    }
    for target, source_path in candidates.items():
        candi_path = Path(source_path).expanduser()
        if candi_path.is_file():
            yml['services']['postgres']['volumes'].append({
                'type': 'bind', 
                'source': str(candi_path),
                'target': str(target)})
            click.secho(f"Using postgres config from {candi_path}", fg='yellow')
        else:
            click.secho(f"Suggestion: you can put postgres configuration file here: {candi_path}", fg='blue')
