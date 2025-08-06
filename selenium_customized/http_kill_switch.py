#!/usr/bin/env python3
"""
gecko_restarter.py  –  restart geckodriver on GET /restart

Environment
────────────
WEBDRIVER_KILLSWITCH_BINDING   ip:port to bind (default 0.0.0.0:4445)

Requires:  psutil   →  pip install psutil
"""

import http.server, json, logging, os, subprocess, sys
import psutil

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
LOG = logging.getLogger(__name__)

# ─── Resolve bind address from env ─────────────────────────────────────────────
bind_env = os.getenv("WEBDRIVER_KILLSWITCH_BINDING", "0.0.0.0:4445")
try:
    BIND_IP, BIND_PORT = bind_env.split(":")
    BIND_PORT = int(BIND_PORT)
except ValueError:
    LOG.critical("WEBDRIVER_KILLSWITCH_BINDING must be ip:port (got %r)", bind_env)
    sys.exit(1)


def find_geckodriver() -> psutil.Process | None:
    me = psutil.Process().pid
    for p in psutil.process_iter(("name",)):
        if p.pid != me and p.info["name"] == "geckodriver":
            return p
    return None


def hard_restart() -> int:
    proc = find_geckodriver()
    if not proc:
        raise RuntimeError("geckodriver not found")

    cmd = proc.cmdline()
    LOG.info("Killing geckodriver pid=%s", proc.pid)
    proc.kill()              # immediate SIGKILL
    proc.wait(timeout=10)

    LOG.info("Restarting geckodriver with same args")
    new_proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)
    LOG.info("New geckodriver pid=%s", new_proc.pid)
    return new_proc.pid


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/restart":
            self.send_error(404)
            return
        try:
            pid = hard_restart()
            body = json.dumps({"message": "restarted", "pid": pid}).encode()
            self.send_response(200)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            self.send_response(500)

        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):  # suppress default logging
        pass


if __name__ == "__main__":
    LOG.info("Binding to http://%s:%s  (GET /restart)", BIND_IP, BIND_PORT)
    http.server.ThreadingHTTPServer((BIND_IP, BIND_PORT), Handler).serve_forever()