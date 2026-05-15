import sys
import os

CRASH_SENTINEL = "/dev/shm/cron_crashed"

if os.path.exists(CRASH_SENTINEL):
    print(
        "ERROR: Odoo cron thread crash detected - container needs restart.",
        file=sys.stderr,
    )
    sys.exit(1)

sys.exit(0)
