import os

from tools import (
    exec_odoo,
    is_odoo_cronjob,
    is_odoo_queuejob,
    prepare_run,
)
from tools import set_proxy_update_modules
from tools import pregenerate_assets_if_web
from tools import set_warmup_in_progress, clear_warmup_in_progress

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

# Opt-in: ODOO_WARMUP_PREGENERATE=1 pre-generates asset bundles for the
# web role before workers fork (avoids per-worker stale ormcache_context
# entries in ir.qweb._generate_asset_nodes_cache). Off by default — the
# first request just pays the cost normally. No-op for cron/queuejob.
pregenerate_assets_if_web()

# Gate external traffic at the bundled nginx proxy while the web role
# warms up (browsers see a maintenance page, API clients are held inside
# the proxy until warmup completes). Only set when we actually run the
# warmup loop (TOUCH_URL); otherwise (DEVMODE, cron/queuejob) the
# warmup-done signal would never fire and the gate would stay closed
# forever — proactively clear any stale sentinel from a previous run.
if TOUCH_URL:
    set_warmup_in_progress()
else:
    clear_warmup_in_progress()

exec_odoo(
    None,
    f"--log-level={LEVEL}",
    f"--log-handler=:{LEVEL.upper()}",
    touch_url=TOUCH_URL,
)
