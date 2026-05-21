import os

from tools import (
    exec_odoo,
    is_odoo_cronjob,
    is_odoo_queuejob,
    prepare_run,
)
from tools import set_proxy_update_modules
from tools import set_warmup_in_progress, signal_warmup_done

# Gate external traffic at the bundled nginx proxy as the *very first*
# thing we do: prepare_run() + pregenerate can together take 30–60 s,
# during which Odoo isn't listening yet — without an early sentinel the
# proxy proxies into a dead backend and serves the static-404 fallback
# (403) to real clients. No-op when the proxy_exchange volume isn't
# mounted (standalone/AWS deployments) and for cron/queuejob roles or
# DEVMODE (no warmup loop will run; supervisor already skipped the
# initial touch — keep this consistent).
_DEVMODE = os.getenv("DEVMODE") == "1" or os.getenv("ZODOO_DEVMODE") == "1"
if not is_odoo_cronjob and not is_odoo_queuejob and not _DEVMODE:
    set_warmup_in_progress()

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
if _DEVMODE:
    TOUCH_URL = False

LEVEL = os.getenv("ODOO_LOG_LEVEL", "debug")

set_proxy_update_modules(False)

# Asset pre-generation moved to supervisor._pregenerate() (Phase 0) — it
# runs there once in an isolated odoo-shell subprocess BEFORE any role
# spawns, so no cron/queuejob worker races the asset write. The web
# role itself no longer pre-generates; the first real HTTP request
# picks up the bundles that are already committed to the DB.

# If we won't actually run the warmup loop (DEVMODE / cron / queuejob),
# signal warmup-done immediately so the supervisor's gate doesn't hang
# for ODOO_WARMUP_GATE_TIMEOUT_S waiting for a signal that never comes.
# Also clears the early proxy-gate sentinel (set above for web role).
if not TOUCH_URL:
    signal_warmup_done()

exec_odoo(
    None,
    f"--log-level={LEVEL}",
    f"--log-handler=:{LEVEL.upper()}",
    touch_url=TOUCH_URL,
)
