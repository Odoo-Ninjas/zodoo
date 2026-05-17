import importlib.metadata
import os

from tools import (
    exec_odoo,
    is_odoo_cronjob,
    is_odoo_queuejob,
    prepare_run_role,
)
from tools import set_proxy_update_modules

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

exec_odoo(
    None,
    f"--log-level={LEVEL}",
    f"--log-handler=:{LEVEL.upper()}",
    touch_url=TOUCH_URL,
)
