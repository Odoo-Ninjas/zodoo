#!/usr/bin/env python3
"""Checks what the trigger passes on to Docker.

The trigger holds the Docker socket, the `coding` container does not -- it
calls the trigger over HTTP. That makes the list of allowed commands the
actual boundary: whatever gets through runs with the socket's rights, and
that is the whole host. On a machine with several customers it is the route
to the neighbour.

Nothing is executed: `subprocess.run` is replaced, the tests only see the
argument list that would have been used.

Run with:  python3 test_server.py
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PROJECT_NAME", "customer")
os.environ.setdefault("COMPOSE_FILE", "/opt/run/docker-compose.yml")

import server  # noqa: E402


class Recorder:
    """Records what would have been executed."""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, *a, **kw):
        self.calls.append(list(cmd))
        return mock.Mock(returncode=0, stdout="", stderr="")

    @property
    def last(self):
        return self.calls[-1] if self.calls else []


class TriggerBoundary(unittest.TestCase):
    def command(self, text):
        recorder = Recorder()
        with mock.patch.object(server.subprocess, "run", recorder):
            result = server._odoo_command(text)
        return result, recorder

    # --- what has to keep working ------------------------------------------
    def test_restart_passes(self):
        result, recorder = self.command("restart odoo")
        self.assertEqual(result["returncode"], 0)
        self.assertIn("restart", recorder.last)
        self.assertIn("odoo", recorder.last)

    def test_up_passes(self):
        _, recorder = self.command("up -d --no-recreate postgres")
        self.assertIn("up", recorder.last)
        self.assertIn("-d", recorder.last)

    def test_update_passes(self):
        _, recorder = self.command("update sale_stock")
        self.assertIn("update", recorder.last)
        self.assertIn("sale_stock", recorder.last)

    # --- what must not get through -----------------------------------------
    def test_mounting_the_host_is_rejected(self):
        """`run -v /:/host` mounts the host's root directory.

        That lays open /etc, the data and the backups of every neighbour.
        """
        result, recorder = self.command("run --rm -v /:/host odoo bash")
        self.assertNotEqual(
            result["returncode"],
            0,
            f"The trigger would have mounted the host: {recorder.last!r}",
        )
        self.assertEqual(recorder.calls, [], "It should not have run at all")

    def test_custom_entrypoint_is_rejected(self):
        result, recorder = self.command("run --rm --entrypoint /bin/sh odoo")
        self.assertNotEqual(result["returncode"], 0, repr(recorder.last))

    def test_privileged_is_rejected(self):
        result, recorder = self.command("run --rm --privileged odoo bash")
        self.assertNotEqual(result["returncode"], 0, repr(recorder.last))

    def test_foreign_project_is_rejected(self):
        """A second -p picks the neighbour's compose project."""
        result, recorder = self.command("-p neighbour up -d odoo")
        self.assertNotEqual(result["returncode"], 0, repr(recorder.last))

    def test_foreign_compose_file_is_rejected(self):
        result, recorder = self.command(
            "-f /opt/odoo/neighbour/docker-compose.yml up -d"
        )
        self.assertNotEqual(result["returncode"], 0, repr(recorder.last))

    def test_unknown_verb_is_rejected(self):
        result, recorder = self.command("down --volumes")
        self.assertNotEqual(result["returncode"], 0, repr(recorder.last))

    def test_empty_command(self):
        result, _ = self.command("")
        self.assertNotEqual(result["returncode"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
