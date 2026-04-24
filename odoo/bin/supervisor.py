"""Zodoo supervisor — PID 1 of the consolidated odoo container.

Replaces the former separate containers odoo / odoo_cronjobs / odoo_queuejobs
/ odoo_update / odoo_debug. Spawns one child per enabled role (web, cronjobs,
queuejobs) and manages their lifecycle. Listens on a unix socket for control
commands sent by the host CLI via `docker exec`.

Two modes:

  supervisor.py                       # daemon (PID 1)
  supervisor.py <cmd> [<role>]        # client — talks to the socket:
                                      #   status | restart <role> |
                                      #   start <role> | stop <role> |
                                      #   shutdown
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

SOCKET_PATH = "/var/run/zodoo-supervisor.sock"
ZODOO_PYTHON = os.environ.get(
    "ZODOO_PYTHON", "/opt/zodoo_pipx/venvs/zodoo/bin/python3"
)
RUN_PY = "/odoolib/run.py"
UPDATE_PY = "/odoolib/update_on_startup.py"
GRACE_SECONDS = 30
BACKOFF_INITIAL = 1.0
BACKOFF_MAX = 30.0

# Role definitions. The run.py entrypoint reads IS_ODOO_CRONJOB /
# IS_ODOO_QUEUEJOB to pick the right odoo config file; for the web role
# neither is set and run.py falls through to config_webserver.
ROLES = {
    "web": {
        "env": {},
        "enabled_key": "RUN_ODOO_WEB",
    },
    "cronjobs": {
        "env": {"IS_ODOO_CRONJOB": "1"},
        "enabled_key": "RUN_ODOO_CRONJOBS",
    },
    "queuejobs": {
        "env": {"IS_ODOO_QUEUEJOB": "1"},
        "enabled_key": "RUN_ODOO_QUEUEJOBS",
    },
}


def _log(msg):
    sys.stdout.write(f"[supervisor] {msg}\n")
    sys.stdout.flush()


def _env_truthy(key, default="1"):
    return os.environ.get(key, default) == "1"


class Role:
    def __init__(self, name, spec):
        self.name = name
        self.spec = spec
        self.proc = None
        self.want_running = _env_truthy(spec["enabled_key"])
        self.backoff = BACKOFF_INITIAL
        self.last_spawn = 0.0
        self._log_thread = None
        self._lock = threading.Lock()

    def spawn(self):
        with self._lock:
            if self.proc is not None and self.proc.poll() is None:
                return
            env = dict(os.environ)
            env.update(self.spec["env"])
            env["ZODOO_ROLE"] = self.name
            _log(f"[{self.name}] spawn")
            self.last_spawn = time.time()
            self.proc = subprocess.Popen(
                [ZODOO_PYTHON, RUN_PY],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                bufsize=1,
                text=True,
            )
            self._log_thread = threading.Thread(
                target=self._pump_logs, daemon=True
            )
            self._log_thread.start()

    def _pump_logs(self):
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        prefix = f"[{self.name}] "
        try:
            for line in proc.stdout:
                sys.stdout.write(prefix + line)
                sys.stdout.flush()
        except Exception as ex:
            _log(f"[{self.name}] log pump error: {ex}")

    def stop(self, timeout=GRACE_SECONDS):
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                return
            _log(f"[{self.name}] stop (SIGTERM, grace {timeout}s)")
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            _log(f"[{self.name}] grace expired, SIGKILL")
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait()

    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None

    def reap_if_dead(self):
        """Return True if child has exited since last check."""
        if self.proc is None:
            return False
        rc = self.proc.poll()
        if rc is None:
            return False
        _log(f"[{self.name}] exited rc={rc}")
        self.proc = None
        return True

    def status(self):
        if self.proc is None:
            return {
                "name": self.name,
                "want_running": self.want_running,
                "alive": False,
                "pid": None,
            }
        return {
            "name": self.name,
            "want_running": self.want_running,
            "alive": self.proc.poll() is None,
            "pid": self.proc.pid,
            "returncode": self.proc.poll(),
        }


class Supervisor:
    def __init__(self):
        self.roles = {n: Role(n, s) for n, s in ROLES.items()}
        self._shutdown = threading.Event()
        self._sock = None

    # ------------------------------------------------------------------
    # Role lifecycle
    # ------------------------------------------------------------------

    def start_enabled(self):
        for role in self.roles.values():
            if role.want_running:
                role.spawn()

    def supervise_loop(self):
        """Reap children and respawn per policy (restart: on-failure)."""
        while not self._shutdown.is_set():
            for role in self.roles.values():
                if role.reap_if_dead() and role.want_running:
                    # Exponential backoff on tight crash loops.
                    since = time.time() - role.last_spawn
                    if since < role.backoff:
                        _log(
                            f"[{role.name}] crashed after "
                            f"{since:.1f}s, backoff {role.backoff:.1f}s"
                        )
                        self._shutdown.wait(role.backoff)
                        role.backoff = min(role.backoff * 2, BACKOFF_MAX)
                    else:
                        role.backoff = BACKOFF_INITIAL
                    if not self._shutdown.is_set():
                        role.spawn()
            self._shutdown.wait(1.0)

    def shutdown_all(self):
        self._shutdown.set()
        threads = []
        for role in self.roles.values():
            if role.is_alive():
                t = threading.Thread(target=role.stop)
                t.start()
                threads.append(t)
        for t in threads:
            t.join()

    # ------------------------------------------------------------------
    # Control socket
    # ------------------------------------------------------------------

    def _handle_cmd(self, line):
        parts = line.strip().split()
        if not parts:
            return {"ok": False, "error": "empty command"}
        verb = parts[0]
        arg = parts[1] if len(parts) > 1 else None

        if verb == "status":
            return {
                "ok": True,
                "roles": [r.status() for r in self.roles.values()],
            }

        if verb == "shutdown":
            threading.Thread(target=self.shutdown_all, daemon=True).start()
            return {"ok": True, "msg": "shutting down"}

        if verb in ("restart", "start", "stop"):
            if arg is None or arg not in self.roles:
                return {
                    "ok": False,
                    "error": f"unknown role: {arg}",
                }
            role = self.roles[arg]
            if verb == "stop":
                role.want_running = False
                role.stop()
                return {"ok": True, "msg": f"{arg} stopped"}
            if verb == "start":
                role.want_running = True
                role.backoff = BACKOFF_INITIAL
                role.spawn()
                return {"ok": True, "msg": f"{arg} started"}
            if verb == "restart":
                role.want_running = True
                role.backoff = BACKOFF_INITIAL
                role.stop()
                role.spawn()
                return {"ok": True, "msg": f"{arg} restarted"}

        return {"ok": False, "error": f"unknown verb: {verb}"}

    def _socket_server(self):
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o666)
        self._sock.listen(5)
        _log(f"control socket listening on {SOCKET_PATH}")
        while not self._shutdown.is_set():
            try:
                self._sock.settimeout(1.0)
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(5.0)
                data = conn.recv(4096).decode("utf-8", "replace")
                reply = self._handle_cmd(data)
                conn.sendall(json.dumps(reply).encode("utf-8") + b"\n")
            except Exception as ex:
                _log(f"socket handler error: {ex}")
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _install_signals(self):
        def handler(signum, _frame):
            _log(f"received signal {signum}, shutting down")
            self.shutdown_all()

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------

    def run(self):
        _log("starting")
        self._install_signals()

        if _env_truthy("UPDATE_ON_STARTUP", "0"):
            _log("UPDATE_ON_STARTUP=1 — running update before spawning roles")
            try:
                subprocess.run(
                    [ZODOO_PYTHON, UPDATE_PY],
                    check=True,
                    cwd="/opt/src",
                )
            except subprocess.CalledProcessError as ex:
                _log(
                    f"update failed (rc={ex.returncode}) — serving error page"
                )
                _serve_error_page()
                return

        threading.Thread(target=self._socket_server, daemon=True).start()
        self.start_enabled()
        try:
            self.supervise_loop()
        finally:
            self.shutdown_all()
            try:
                if os.path.exists(SOCKET_PATH):
                    os.unlink(SOCKET_PATH)
            except OSError:
                pass
        _log("exit")


class _ErrorPageHandler(SimpleHTTPRequestHandler):
    def list_directory(self, path):
        self.send_error(403, "Directory listing not allowed")
        return None

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
        return super().do_GET()


def _serve_error_page():
    PORT = 8069
    os.chdir("/var/www/html")
    with HTTPServer(("", PORT), _ErrorPageHandler) as httpd:
        _log(f"construction-site on port {PORT}")
        httpd.serve_forever()


# ---------------------------------------------------------------------
# Client mode
# ---------------------------------------------------------------------


def _client(argv):
    if not argv:
        argv = ["status"]
    cmd = " ".join(argv)
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError) as ex:
        print(
            f"supervisor not reachable at {SOCKET_PATH}: {ex}", file=sys.stderr
        )
        return 2
    try:
        sock.sendall(cmd.encode("utf-8"))
        resp = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp += chunk
    finally:
        sock.close()
    try:
        data = json.loads(resp.decode("utf-8").strip() or "{}")
    except json.JSONDecodeError:
        print(resp.decode("utf-8", "replace"))
        return 1
    if not data.get("ok"):
        print(f"error: {data.get('error', 'unknown')}", file=sys.stderr)
        return 1
    if argv[0] == "status":
        for r in data.get("roles", []):
            state = "running" if r["alive"] else "stopped"
            want = "wanted" if r["want_running"] else "disabled"
            print(f"{r['name']:<12} {state:<8} {want:<8} pid={r.get('pid')}")
    else:
        print(data.get("msg", "ok"))
    return 0


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("status", "restart", "start", "stop", "shutdown"):
        sys.exit(_client(argv))
    # Daemon mode
    Path(SOCKET_PATH).parent.mkdir(parents=True, exist_ok=True)
    Supervisor().run()


if __name__ == "__main__":
    main()
