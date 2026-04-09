import os
import threading
from tools import prepare_run
from tools import exec_odoo
from tools import set_proxy_update_modules
from tools import is_odoo_cronjob
from tools import is_odoo_queuejob
from http.server import HTTPServer, SimpleHTTPRequestHandler

import subprocess
import sys

if is_odoo_cronjob:
    _CRASH_PATTERN = b"Exception in thread odoo.service.cron.cron"
    _CRASH_SENTINEL = "/dev/shm/cron_crashed"

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

print("Starting up odoo")
prepare_run()

TOUCH_URL = not is_odoo_cronjob and not is_odoo_queuejob
if os.getenv("DEVMODE") == "1":
    TOUCH_URL = False

if os.getenv("IS_ODOO_DEBUG") == "1":
    print("Exiting - just here for debugging")
    sys.exit(0)

LEVEL = os.getenv("ODOO_LOG_LEVEL", "debug")
ZODOO_PYTHON = os.getenv("ZODOO_PYTHON")


class OnlyIndexHandler(SimpleHTTPRequestHandler):
    def list_directory(self, path):
        # Disable directory listing
        self.send_error(403, "Directory listing not allowed")
        return None

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
        return super().do_GET()


if os.getenv("UPDATE_ON_STARTUP") == "1":
    try:
        subprocess.run(
            [ZODOO_PYTHON, "/odoolib/update_on_startup.py"],
            check=True,
            cwd="/opt/src",
        )
    except subprocess.CalledProcessError as e:
        PORT = 8069
        os.chdir("/var/www/html")  # folder containing index.html
        with HTTPServer(("", PORT), OnlyIndexHandler) as httpd:
            print(f"Serving construction-site port {PORT}")
            httpd.serve_forever()

set_proxy_update_modules(False)

exec_odoo(
    None,
    f"--log-level={LEVEL}",
    f"--log-handler=:{LEVEL.upper()}",
    touch_url=TOUCH_URL,
)
