#!/usr/bin/env python3
"""Trigger sidecar: exposes HTTP endpoints that execute predefined Docker actions.

The coding container calls these endpoints instead of having Docker access.
"""

import base64
import os
import socket
import subprocess
import json
import tempfile
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

PROJECT_NAME = os.environ.get("PROJECT_NAME", "")
COMPOSE_FILE = os.environ.get("COMPOSE_FILE", "")


def _run(*args, timeout=180):
    """Run a command and return result dict."""
    result = subprocess.run(
        list(args), capture_output=True, text=True, timeout=timeout
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _dc(*args):
    """Run docker compose command for the project."""
    cmd = ["docker", "compose", "-p", PROJECT_NAME]
    if COMPOSE_FILE:
        cmd = ["docker", "compose", "-p", PROJECT_NAME, "-f", COMPOSE_FILE]
    cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _container_name(service):
    return f"{PROJECT_NAME}_{service}"


def _wait_for_port(host, port=5678, timeout=60):
    """Wait until a TCP port is accepting connections (without consuming the debugpy slot)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket()
            s.settimeout(2)
            s.connect((host, port))
            s.close()
            return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _get_container_ip(name):
    ip_result = _run(
        "docker",
        "inspect",
        "-f",
        "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
        name,
    )
    return ip_result["stdout"].strip()


def _debug():
    """Stop odoo, restart with debug command, wait until debugpy ready."""
    name = _container_name("odoo")

    # Create temp override that sets the debug command
    override = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", delete=False, prefix="debug_override_"
    )
    override.write(f"""services:
  odoo:
    command: ["/bin/bash", "-c", "/odoolib/debug --wait-for-remote --one-action debug"]
""")
    override.close()

    try:
        # Stop odoo
        _dc("stop", "-t", "5", "odoo")

        # Start with debug override
        cmd = [
            "docker",
            "compose",
            "-p",
            PROJECT_NAME,
            "-f",
            COMPOSE_FILE,
            "-f",
            override.name,
            "up",
            "-d",
            "odoo",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180
        )
        if result.returncode != 0:
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
    finally:
        os.unlink(override.name)

    # Wait for debugpy to start listening.
    # IMPORTANT: Do NOT connect to port 5678 to check — debugpy with
    # --wait-for-client treats any TCP connection as THE client, consuming the
    # slot. Instead, wait for the adapter process to appear.
    odoo_ip = _get_container_ip(name)
    if not odoo_ip:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "Could not determine odoo container IP",
        }

    deadline = time.time() + 60
    while time.time() < deadline:
        check = _run(
            "docker",
            "exec",
            name,
            "bash",
            "-c",
            "pgrep -f 'debugpy/adapter' > /dev/null 2>&1",
        )
        if check["returncode"] == 0:
            # Give the adapter a moment to bind the port
            time.sleep(1)
            return {"returncode": 0, "stdout": "debugpy ready", "stderr": ""}
        time.sleep(1)

    return {
        "returncode": 1,
        "stdout": "",
        "stderr": "Timeout waiting for debugpy",
    }


def _robot(test_file):
    """Start seleniumdriver, then run robot test via docker compose run."""
    # Ensure seleniumdriver is running
    result = _dc("up", "-d", "seleniumdriver")
    if result["returncode"] != 0:
        return result

    # Wait for Selenium to be ready
    selenium_name = _container_name("seleniumdriver")
    selenium_ip = _get_container_ip(selenium_name)
    if not selenium_ip:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "Could not determine seleniumdriver IP",
        }
    if not _wait_for_port(selenium_ip, 4444, timeout=30):
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "Timeout waiting for seleniumdriver:4444",
        }

    # Build archive params (base64-encoded JSON piped to robot stdin)
    params = {
        "SELENIUM_SERVICE_NAME": "seleniumdriver",
        "test_files": [test_file],
        "params": {
            "browser": "chrome",
            "parallel": 1,
        },
        "token": "latest",
        "results_file": "results.json",
        "debug": False,
    }
    archive = base64.b64encode(json.dumps(params).encode())

    # Run robot container with archive on stdin
    cmd = ["docker", "compose", "-p", PROJECT_NAME]
    if COMPOSE_FILE:
        cmd.extend(["-f", COMPOSE_FILE])
    cmd.extend(["run", "--rm", "-T", "robot"])

    result = subprocess.run(
        cmd,
        input=archive,
        capture_output=True,
        timeout=600,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout.decode(errors="replace")[-2000:],
        "stderr": result.stderr.decode(errors="replace")[-2000:],
    }


ACTIONS = {
    "/restart": lambda: _dc("restart", "odoo"),
    "/debug": _debug,
    "/up": lambda: _dc("up", "-d", "odoo"),
    "/logs": lambda: _dc("logs", "--tail=100", "odoo"),
}


class Handler(BaseHTTPRequestHandler):
    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # /robot endpoint: accepts {"test_file": "relative/path.robot"}
        if path == "/robot":
            try:
                body = self._read_body()
                test_file = body.get("test_file", "")
                if not test_file:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(
                        json.dumps({"error": "test_file required"}).encode()
                    )
                    return
                result = _robot(test_file)
                self.send_response(200 if result["returncode"] == 0 else 500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(ex)}).encode())
            return

        action = ACTIONS.get(path)
        if not action:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": f"Unknown action: {path}"}).encode()
            )
            return

        try:
            result = action()
            self.send_response(200 if result["returncode"] == 0 else 500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as ex:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(ex)}).encode())

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self.path == "/actions":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(list(ACTIONS.keys())).encode())
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        print(f"[trigger] {args[0]}")


if __name__ == "__main__":
    port = int(os.environ.get("TRIGGER_PORT", "8090"))
    print(f"Trigger sidecar listening on :{port}")
    print(f"Project: {PROJECT_NAME}")
    print(f"Compose file: {COMPOSE_FILE}")
    print(f"Available actions: {list(ACTIONS.keys())}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
