import importlib.metadata
import os
import threading

from tools import exec_odoo, is_odoo_cronjob, is_odoo_queuejob, prepare_run_role
from tools import set_proxy_update_modules
from tools import pregenerate_assets_if_web

if is_odoo_cronjob:
    _CRASH_PATTERN = b"Exception in thread odoo.service.cron.cron"
    _CRASH_SENTINEL = "/dev/shm/cron_crashed"

    # Under the supervisor the container outlives a cron crash — if we did
    # not clear the sentinel on (re-)spawn, healthcheck_cronjobs.py would
    # keep reporting unhealthy forever. With separate containers docker
    # used to recycle /dev/shm for us; now we do it ourselves.
    try:
        os.unlink(_CRASH_SENTINEL)
    except FileNotFoundError:
        pass

    _r_fd, _w_fd = os.pipe()
    _orig_stdout_fd = os.dup(1)
    os.dup2(_w_fd, 1)
    os.dup2(_w_fd, 2)
    os.close(_w_fd)

    def _monitor_output():
        r = os.fdopen(_r_fd, "rb")
        while True:
            line = r.readline()
            if not line:
                break
            os.write(_orig_stdout_fd, line)
            if _CRASH_PATTERN in line:
                open(_CRASH_SENTINEL, "w").close()

    threading.Thread(target=_monitor_output, daemon=True).start()


try:
    _zodoo_version = importlib.metadata.version("zodoo")
except importlib.metadata.PackageNotFoundError:
    _zodoo_version = "unknown"
print(f"Starting up odoo (zodoo {_zodoo_version})")
prepare_run_role()

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
