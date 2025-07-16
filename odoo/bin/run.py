import os
from tools import prepare_run
from tools import exec_odoo
from tools import is_odoo_cronjob
from tools import is_odoo_queuejob
from http.server import HTTPServer, SimpleHTTPRequestHandler

import subprocess
import sys
print("Starting up odoo")
prepare_run()

TOUCH_URL = not is_odoo_cronjob and not is_odoo_queuejob

if os.getenv("IS_ODOO_DEBUG") == "1":
    print("Exiting - just here for debugging")
    sys.exit(0)

LEVEL = os.getenv("ODOO_LOG_LEVEL", "debug")
WODOO_PYTHON = os.getenv("WODOO_PYTHON")

class OnlyIndexHandler(SimpleHTTPRequestHandler):
    def list_directory(self, path):
        # Disable directory listing
        self.send_error(403, "Directory listing not allowed")
        return None

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self.path = '/index.html'
        return super().do_GET()

if os.getenv("UPDATE_ON_STARTUP") == "1":
    try:
        subprocess.run([
            WODOO_PYTHON, "/odoolib/update_on_startup.py"], check=True, cwd="/opt/src")
    except subprocess.CalledProcessError as e:
        PORT = 8069
        os.chdir("/var/www/html")  # folder containing index.html
        with HTTPServer(("", PORT), OnlyIndexHandler) as httpd:
            print(f"Serving construction-site port {PORT}")
            httpd.serve_forever()
    else:
        exec_odoo(
            None,
            f'--log-level={LEVEL}',
            f'--log-handler=:{LEVEL.upper()}',
            touch_url=TOUCH_URL,
        )
