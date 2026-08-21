"""End-to-end test for the write-only filestore backup.

What this proves, and why it needs a live stack to prove it: the value of this
path is that the SECOND run uploads only what is new. That is not a property of
a function, it is a property of the ledger surviving between two container runs
and the delta being computed against it. A unit test cannot see that.

So: run against a real project, with a throwaway receiver on the host standing
in for the backup server, and assert on the manifests that arrive:

    run 1  -> N files in one bundle
    run 2  -> nothing new, no new object at all
    run 3  -> exactly the one file added in between

The bundle from run 3 is then decrypted (inside the container, which is the only
place with the private key material this test uses) and must contain exactly
that one file, under its filestore-relative path.

Marked slow: needs Docker and a built project. Runs in bake-test.yml.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from .conftest import requires_full_stack



class _Receiver(BaseHTTPRequestHandler):
    """Minimal stand-in for the write-only receiver.

    Deliberately enforces the two rules the real one enforces, because the
    client relies on them: never overwrite, and verify the checksum.
    """

    objects: dict[str, bytes] = {}
    manifests: list[dict] = []

    def log_message(self, *a):  # keep pytest output readable
        pass

    def do_PUT(self):
        parts = [p for p in self.path.split("/") if p]
        if len(parts) != 3:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        _area, kind, name = parts
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        if kind == "objects":
            if name in self.objects:
                self.send_response(409)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            want = (self.headers.get("X-Content-Sha256") or "").lower()
            if hashlib.sha256(body).hexdigest() != want:
                self.send_response(400)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.objects[name] = body
        else:
            self.manifests.append(json.loads(body))

        self.send_response(201)
        self.send_header("Content-Length", "0")
        self.end_headers()


@pytest.fixture
def receiver():
    _Receiver.objects = {}
    _Receiver.manifests = []
    httpd = ThreadingHTTPServer(("0.0.0.0", 0), _Receiver)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()


def _gateway_ip(project):
    """The address the container reaches the host on.

    The receiver runs in this pytest process, i.e. on the host, so the
    container needs the docker network's gateway rather than localhost.
    """
    out = subprocess.run(
        [
            "docker",
            "network",
            "inspect",
            f"{project.name}_default",
            "--format",
            "{{range .IPAM.Config}}{{.Gateway}}{{end}}",
        ],
        capture_output=True,
        text=True,
    )
    gw = (out.stdout or "").strip()
    if not gw:
        pytest.skip("could not determine the docker network gateway")
    return gw


def _setting(project, key):
    """Read one effective setting out of the project's settings file."""
    path = project.home / ".odoo" / f"settings.{project.name}"
    if not path.exists():
        pytest.skip(f"no settings file at {path}")
    for line in path.read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip()
    return None


def _filestore_dir(project) -> Path:
    """$ODOO_FILES/filestore/<db> on the host."""
    files = _setting(project, "ODOO_FILES")
    dbname = _setting(project, "DBNAME") or project.name
    if not files:
        pytest.skip("ODOO_FILES is not set in the project settings")
    d = Path(files).expanduser() / "filestore" / dbname
    if not d.is_dir():
        pytest.skip(f"no filestore at {d}")
    return d


def _decrypt_listing(project, private, bundle: bytes, tmp_path: Path) -> list[str]:
    """Decrypt a bundle inside the offsite container and list its members.

    The container is the one place that has `age` and `tar`, and using it also
    proves the bundle is readable by the same toolchain that wrote it.
    """
    key_file = tmp_path / "key.txt"
    key_file.write_text(private + "\n")
    bundle_file = tmp_path / "bundle.age"
    bundle_file.write_bytes(bundle)
    res = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "-v",
            f"{tmp_path}:/w:ro",
            "--entrypoint",
            "bash",
            f"{project.name}-offsite",
            "-c",
            "age -d -i /w/key.txt /w/bundle.age | tar tzf -",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    return sorted(
        line.strip()
        for line in res.stdout.splitlines()
        if line.strip() and not line.strip().endswith("/")
    )


@pytest.fixture
def age_keypair(odoo_project_19_running):
    """A throwaway keypair, generated in the offsite image.

    Generated rather than committed: a private key in the repository is a bad
    habit even when it protects nothing, and the image already ships `age`, so
    there is nothing to install on the runner.
    """
    res = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "age-keygen",
            f"{odoo_project_19_running.name}-offsite",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    private = public = None
    for line in (res.stdout + res.stderr).splitlines():
        line = line.strip()
        if line.startswith("AGE-SECRET-KEY-"):
            private = line
        elif "public key:" in line:
            public = line.split("public key:")[1].strip()
    assert private and public, (res.stdout, res.stderr)
    return public, private


@pytest.mark.slow
@requires_full_stack
def test_filestore_uploads_only_the_delta(
    odoo_project_19_running, receiver, age_keypair, tmp_path
):
    project = odoo_project_19_running
    public, private = age_keypair
    port = receiver.server_address[1]
    url = f"http://{_gateway_ip(project)}:{port}/e2etest/"

    project.run("setting", f"OFFSITE_WO_URL={url}", timeout=60)
    project.run("setting", f"OFFSITE_WO_RECIPIENT={public}", timeout=60)
    project.run("setting", "OFFSITE_REST_USER=e2etest", timeout=60)
    project.run("setting", "OFFSITE_REST_PASSWORD=irrelevant-for-the-double", timeout=60)
    project.run("reload", timeout=60 * 10)
    project.run("build", "offsite", timeout=60 * 20)

    filestore = _filestore_dir(project)

    # --- run 1: everything that is there now -----------------------------
    project.run("offsite", "filestore", timeout=60 * 10)
    assert len(_Receiver.manifests) == 1, _Receiver.manifests
    first = _Receiver.manifests[0]
    assert first["kind"] == "filestore"
    assert first["files_added"] == first["files_total"] > 0
    assert first["bundle"] in _Receiver.objects
    # The receiver verified the checksum on arrival; assert the manifest agrees
    # with what actually landed, so a client that lies is caught too.
    assert (
        hashlib.sha256(_Receiver.objects[first["bundle"]]).hexdigest()
        == first["sha256"]
    )

    # --- run 2: nothing changed -> nothing may be uploaded ---------------
    project.run("offsite", "filestore", timeout=60 * 10)
    assert len(_Receiver.manifests) == 1, "a run with no new files uploaded something"
    assert len(_Receiver.objects) == 1

    # --- run 3: exactly one new file -------------------------------------
    # Written the way Odoo writes attachments: the name IS the sha1 of the
    # content, so this is indistinguishable from a real new attachment.
    content = b"zodoo write-only filestore e2e\n"
    digest = hashlib.sha1(content).hexdigest()
    target = filestore / digest[:2] / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    project.run("offsite", "filestore", timeout=60 * 10)
    assert len(_Receiver.manifests) == 2, "the new file was not picked up"
    second = _Receiver.manifests[1]
    assert second["files_added"] == 1, second
    assert second["files_total"] == first["files_total"] + 1
    assert second["bundle"] != first["bundle"]
    # The delta bundle must be far smaller than the initial one - that is the
    # whole point of the exercise.
    assert len(_Receiver.objects[second["bundle"]]) < len(
        _Receiver.objects[first["bundle"]]
    )

    # And it really is that one file, not just a small bundle: decrypt it with
    # the private half and list what is inside.
    members = _decrypt_listing(
        project, private, _Receiver.objects[second["bundle"]], tmp_path
    )
    assert members == [f"{digest[:2]}/{digest}"], members
