"""Keep zodoo settings out of Odoo's own option lookup.

From 19.0 on Odoo reads every option that can live in the config file
also from an environment variable ``ODOO_<OPTION>``, and the environment
beats the config file (``odoo/tools/config.py``: ``ChainMap(runtime,
cli, env, file, default)``). zodoo hands all its settings to the
container environment, and some of them are named like Odoo options
(``ODOO_MAX_CRON_THREADS``, ``ODOO_LOG_LEVEL``, ``ODOO_DATA_DIR``,
``ODOO_DBFILTER``). Odoo would then ignore what zodoo wrote per role into
the config file - e.g. ``max_cron_threads = 0`` for the web server - and
start cron threads in every process.

zodoo already renders those values into the config files, so the config
file is authoritative: for every option set in the config file the
matching ``ODOO_<OPTION>`` variable is removed from the environment of
the odoo-bin process. Lives in its own module so it can be unit-tested
without importing tools.py.
"""

import configparser

# first Odoo version that reads ODOO_<OPTION> from the environment
FIRST_VERSION_WITH_ENV_OPTIONS = 19.0


def config_file_env_names(config_path):
    """``ODOO_<OPTION>`` names of all options set in the config file."""
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(config_path)
    if not cfg.has_section("options"):
        return set()
    return {"ODOO_" + key.upper() for key in cfg.options("options")}


def odoo_process_env(environ, config_path, version):
    """Environment for odoo-bin and the names that were taken out of it."""
    env = dict(environ)
    if float(version) < FIRST_VERSION_WITH_ENV_OPTIONS:
        return env, []
    removed = sorted(config_file_env_names(config_path) & set(env))
    for name in removed:
        del env[name]
    return env, removed
