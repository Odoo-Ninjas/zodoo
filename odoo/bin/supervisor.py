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
# Runs prepare_run_shared (config-file rendering) once before roles spawn,
# in an isolated subprocess so the heavy tools.py import doesn't get pulled
# into PID 1.
PREPARE_SHARED_CMD = (
    "import sys; sys.path.insert(0, '/odoolib'); "
    "from tools import prepare_run_shared; prepare_run_shared()"
)
# Runs pregenerate_assets_if_web (asset-bundle pre-generation via an
# isolated odoo-shell subprocess) once BEFORE any role spawns. Doing
# this in the supervisor — not in the web role's run.py — guarantees a
# single web-shell process owns the asset write window with no cron /
# queuejob workers running yet. Opt-in via ODOO_WARMUP_PREGENERATE=1.
PREGENERATE_CMD = (
    "import sys; sys.path.insert(0, '/odoolib'); "
    "from tools import pregenerate_assets_if_web; pregenerate_assets_if_web()"
)
GRACE_SECONDS = 30
BACKOFF_INITIAL = 1.0
BACKOFF_MAX = 30.0

# Watchdog: stdout patterns from a worker role that indicate it has stopped
# making progress (cron thread crashed, DB connection lost and the loop is
# stuck retrying a poisoned pool, …). When matched on a watched role we
# respawn only that role — the web role is intentionally left untouched so
# a cron hiccup never takes the UI down. A user-initiated stop
# (`odoo kill odoo_cronjobs` → want_running=False) wins over the watchdog.
_WATCHDOG_PATTERNS = (
    "Exception in thread odoo.service.cron.cron",
    "server closed the connection unexpectedly",
    "could not connect to server",
    "connection already closed",
    "terminating connection due to administrator command",
    "SSL connection has been closed unexpectedly",
    "psycopg2.InterfaceError",
)
_WATCHDOG_ROLES = {"cronjobs", "queuejobs"}

# Role definitions. The run.py entrypoint reads IS_ODOO_CRONJOB /
# IS_ODOO_QUEUEJOB to pick the right odoo config file; for the web role
# neither is set and run.py falls through to config_webserver.
#
# `enabled_key` is the env-var that toggles the role. `enabled_probe`
# (optional) is an alternative gating function — when present, the role
# is enabled iff `enabled_probe()` returns True (used for queuejobs:
# the role spawns iff the `queue_job` module is actually installed in
# the project DB, replacing the legacy `RUN_ODOO_QUEUEJOBS` toggle).
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
        "enabled_probe": "queue_job_installed",
    },
}


def _log(msg):
    sys.stdout.write(f"[supervisor] {msg}\n")
    sys.stdout.flush()


def _env_truthy(key, default="1"):
    return os.environ.get(key, default) == "1"


_PROBES = {}


def _resolve_probe(name):
    """Lazy-import probes — keeps supervisor import-cheap when the probe
    backend (zodoo / postgres) isn't reachable yet."""
    if name == "queue_job_installed":
        from zodoo.odoo_config import _queue_job_installed

        return _queue_job_installed
    raise KeyError(f"unknown role probe: {name}")


def _is_role_enabled(spec):
    probe_name = spec.get("enabled_probe")
    if probe_name:
        try:
            probe = _PROBES.setdefault(probe_name, _resolve_probe(probe_name))
            return bool(probe())
        except Exception as ex:
            _log(f"role probe {probe_name!r} failed: {ex} — disabling role")
            return False
    return _env_truthy(spec["enabled_key"])


class Role:
    def __init__(self, name, spec):
        self.name = name
        self.spec = spec
        self.proc = None
        self.want_running = _is_role_enabled(spec)
        self.backoff = BACKOFF_INITIAL
        self.last_spawn = 0.0
        self.respawn_requested = False
        self._log_thread = None
        self._lock = threading.Lock()

    def spawn(self):
        with self._lock:
            if self.proc is not None and self.proc.poll() is None:
                return
            env = dict(os.environ)
            env.update(self.spec["env"])
            env["ZODOO_ROLE"] = self.name
            self.last_spawn = time.time()
            self.respawn_requested = False
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
            _log(f"[{self.name}] spawn — pid={self.proc.pid}")
            self._log_thread = threading.Thread(
                target=self._pump_logs, daemon=True
            )
            self._log_thread.start()

    def _pump_logs(self):
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        prefix = f"[{self.name}] "
        watched = self.name in _WATCHDOG_ROLES
        try:
            for line in proc.stdout:
                sys.stdout.write(prefix + line)
                sys.stdout.flush()
                # Guard against the old proc's pump thread setting the flag
                # after a fresh spawn — only the current generation may arm.
                if (
                    watched
                    and proc is self.proc
                    and not self.respawn_requested
                    and any(p in line for p in _WATCHDOG_PATTERNS)
                ):
                    _log(
                        f"[{self.name}] watchdog: stuck-pattern match "
                        f"→ requesting respawn"
                    )
                    self.respawn_requested = True
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
        """Spawn all enabled roles in parallel. Web's HTTP-warmup loop
        (pregenerate + Phase 2/3 in odoo/bin/tools.py) only gates the
        external nginx proxy, not the local cron/queuejob roles —
        background workers can settle their own caches the first time
        they hit the DB; there's no need to hold them back during a
        web restart.
        """
        enabled = [n for n, r in self.roles.items() if r.want_running]
        disabled = [n for n, r in self.roles.items() if not r.want_running]
        _log(f"roles: enabled={enabled or '∅'} disabled={disabled or '∅'}")
        if not enabled:
            _log("no roles to spawn")
            return
        _log(f"spawning roles: {enabled}")
        for name in enabled:
            self.roles[name].spawn()

    def supervise_loop(self):
        """Reap children and respawn per policy (restart: on-failure).

        Also services watchdog respawn requests posted by `_pump_logs` for
        watched worker roles (cronjobs/queuejobs). A respawn request that
        coincides with `want_running=False` (user did `odoo kill
        odoo_cronjobs`) is dropped — the user's stop intent wins.
        """
        while not self._shutdown.is_set():
            for role in self.roles.values():
                if role.respawn_requested:
                    role.respawn_requested = False
                    if not role.want_running:
                        _log(
                            f"[{role.name}] watchdog: ignored "
                            f"(want_running=False — user stopped it)"
                        )
                    else:
                        _log(f"[{role.name}] watchdog: respawning")
                        role.stop()
                        role.backoff = BACKOFF_INITIAL
                        if not self._shutdown.is_set():
                            role.spawn()
                    continue
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

        # Touch the proxy-gate sentinel as the *very first* thing in the
        # container lifecycle (before prepare_run_shared, before role
        # spawn) so external traffic gets the warming-up page during the
        # 20–50 s where Odoo isn't listening yet. Idempotent with the
        # touch in run.py. Skipped in DEVMODE (no warmup loop will run,
        # and we don't want devs staring at a maintenance page) and for
        # cron/queuejob-only containers (no web role → no one would
        # clear the sentinel).
        devmode = (
            os.environ.get("DEVMODE") == "1"
            or os.environ.get("ZODOO_DEVMODE") == "1"
        )
        web_role = self.roles.get("web")
        if web_role and web_role.want_running and not devmode:
            try:
                p = Path("/var/run/proxy_exchange/warmup_in_progress")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch()
                _log(f"  ▸ touched warmup-gate sentinel {p}")
            except Exception as e:
                _log(f"  ▸ could not touch warmup-gate sentinel: {e}")

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
        _prepare_shared()
        _pregenerate()
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


def _prepare_shared():
    _log("rendering shared odoo config (prepare_run_shared)")
    try:
        subprocess.run(
            [ZODOO_PYTHON, "-c", PREPARE_SHARED_CMD],
            check=True,
            cwd="/opt/src",
        )
    except subprocess.CalledProcessError as ex:
        _log(f"prepare_run_shared failed (rc={ex.returncode})")
        raise


def _pregenerate():
    """Phase 0: asset pre-generation in an isolated odoo-shell subprocess.

    Runs BEFORE any role is spawned so a single web-shell process owns
    the asset write window with no cron / queuejob workers running yet.
    Idempotent and best-effort: failures here NEVER block the supervisor
    from continuing to spawn roles (asset gen failures are non-fatal).
    No-op when ODOO_WARMUP_PREGENERATE != "1".
    """
    web_role = ROLES.get("web")
    if not (web_role and _env_truthy(web_role.get("enabled_key", ""), "0")):
        return
    _log("phase 0 ▸ asset pre-generation (single web-shell, before roles)")
    try:
        subprocess.run(
            [ZODOO_PYTHON, "-c", PREGENERATE_CMD],
            check=False,
            cwd="/opt/src",
        )
    except Exception as ex:
        _log(f"pregenerate failed (non-fatal, continuing): {ex}")


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
