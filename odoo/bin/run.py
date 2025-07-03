import os
from tools import prepare_run
from tools import exec_odoo
from tools import is_odoo_cronjob
from tools import is_odoo_queuejob
import sys
print("Starting up odoo")
prepare_run()

TOUCH_URL = not is_odoo_cronjob and not is_odoo_queuejob

if os.getenv("IS_ODOO_DEBUG") == "1":
    print("Exiting - just here for debugging")
    sys.exit(0)

LEVEL = os.getenv("ODOO_LOG_LEVEL", "debug")

exec_odoo(
    None,
    f'--log-level={LEVEL}',
    f'--log-handler=:{LEVEL.upper()}',
    touch_url=TOUCH_URL,
)
