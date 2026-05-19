import os

from tools import (
    exec_odoo,
    is_odoo_cronjob,
    is_odoo_queuejob,
    prepare_run,
)
from tools import set_proxy_update_modules
from tools import pregenerate_assets_if_web

try:
    import importlib.metadata as _md  # py >= 3.8
except ImportError:
    try:
        import importlib_metadata as _md  # py 3.7 backport (if installed)
    except ImportError:
        _md = None

if _md is None:
    _zodoo_version = "unknown"
else:
    try:
        _zodoo_version = _md.version("zodoo")
    except Exception:
        _zodoo_version = "unknown"
print(f"Starting up odoo (zodoo {_zodoo_version})")
# Legacy v11/v13 entrypoint: each role container runs run.py directly,
# so we must do the full prepare (config rendering + role-specific
# fixups). With the v14+ supervisor those two halves are split across
# prepare_run_shared (once, by the supervisor) and prepare_run_role
# (per spawned role).
prepare_run()

TOUCH_URL = not is_odoo_cronjob and not is_odoo_queuejob
if os.getenv("DEVMODE") == "1":
    TOUCH_URL = False

LEVEL = os.getenv("ODOO_LOG_LEVEL", "debug")

set_proxy_update_modules(False)

# Pre-generate asset bundles for the web role BEFORE odoo workers fork.
# Workers cache asset-bundle lookups in-process forever (ormcache_context,
# see ir.qweb._generate_asset_nodes_cache). If bundles are created after
# the fork, each worker still serves its own stale cached URLs and
# produces intermittent 404s. Doing the generation here means every
# worker inherits the same DB state at fork time. No-op for cron/queuejob.
pregenerate_assets_if_web()

exec_odoo(
    None,
    f"--log-level={LEVEL}",
    f"--log-handler=:{LEVEL.upper()}",
    touch_url=TOUCH_URL,
)
