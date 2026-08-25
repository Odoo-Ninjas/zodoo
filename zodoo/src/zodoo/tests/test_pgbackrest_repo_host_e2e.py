"""End-to-end test of the REPO HOST topology, with a real receiving side.

The other pgbackrest end-to-end test uses a local repository, which proves
backup and recovery but not the shape that production actually runs: the
repository on a different machine, reached over TLS with a client certificate.
That path has its own failure modes and none of them are visible locally -
certificate rejection, ``tls-server-auth`` naming the wrong stanza, a version
mismatch between the two binaries, retention living on the wrong side.

So this brings up an actual ``pgbackrest server`` as the repository host, in a
container, and drives a real project against it.

Two details make the imitation faithful rather than decorative:

* The repository server runs **the project's own pgbackrest image**. pgbackrest
  requires the same version on both ends and refuses to talk across a
  mismatch, so building the receiver from the same image is what guarantees
  the test cannot pass for the wrong reason - and would catch a PGBR_VERSION
  that only landed in one of the two images.
* The client certificate's CN and the stanza are bound by ``tls-server-auth``,
  exactly as ``pgbackrest-area create`` does it on the real backup server. A
  certificate that is merely signed by the CA is not enough, and that is the
  property worth testing.

What it asserts is the thing the operator cares about: full, differential and
incremental backups all arrive on the far side, and the incremental costs a
fraction of the full.
"""

import json
import shutil
import subprocess

import pytest

from .conftest import _run, requires_full_stack

REPO_PORT = 8433  # not 8432: leave the default free for a real repo host


def _docker(*args, **kw):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, **kw
    )


def _openssl(*args):
    subprocess.run(
        ["openssl", *args],
        check=True,
        capture_output=True,
    )


def _make_certs(cert_dir, stanza, server_cn):
    """A CA, a server certificate and a client certificate whose CN is the stanza.

    Mirrors what `pgbackrest-area create` does on the backup server: the
    client certificate is an identity, not a key - it says who may write, and
    `tls-server-auth` says which stanza that identity may write to.
    """
    cert_dir.mkdir(parents=True, exist_ok=True)
    ca_crt, ca_key = cert_dir / "ca.crt", cert_dir / "ca.key"
    _openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "2",
        "-keyout",
        str(ca_key),
        "-out",
        str(ca_crt),
        "-subj",
        "/O=zodoo-test/CN=zodoo-test-ca",
    )
    for name, cn, usage in (
        ("server", server_cn, "serverAuth"),
        ("client", stanza, "clientAuth"),
    ):
        csr = cert_dir / f"{name}.csr"
        ext = cert_dir / f"{name}.ext"
        ext.write_text(
            f"extendedKeyUsage = {usage}\n"
            + (
                f"subjectAltName = DNS:{cn}, IP:{cn}\n"
                if usage == "serverAuth" and cn[0].isdigit()
                else f"subjectAltName = DNS:{cn}\n"
            )
        )
        _openssl(
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(cert_dir / f"{name}.key"),
            "-out",
            str(csr),
            "-subj",
            f"/O=zodoo-test/CN={cn}",
        )
        _openssl(
            "x509",
            "-req",
            "-in",
            str(csr),
            "-CA",
            str(ca_crt),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(cert_dir / f"{name}.crt"),
            "-days",
            "2",
            "-extfile",
            str(ext),
        )
        csr.unlink()
        ext.unlink()
    for f in cert_dir.glob("*.key"):
        f.chmod(0o600)
    return cert_dir


def _project_image(project, service):
    """The image tag compose built for a service of this project."""
    out = _docker("compose", "-p", project.name, "ps", "-q", service)
    cid = (out.stdout or "").strip().splitlines()
    if not cid:
        return None
    out = _docker("inspect", cid[0], "--format", "{{.Config.Image}}")
    return (out.stdout or "").strip() or None


@pytest.fixture(scope="module")
def repo_host(pgbackrest_project, tmp_path_factory):
    """A real `pgbackrest server` receiving side, in a container.

    Uses the project's OWN pgbackrest image so the two ends cannot differ in
    version - which is both realistic and the only way this test fails for the
    right reasons.
    """
    project = pgbackrest_project
    stanza = project.name
    image = _project_image(project, "pgbackrest")
    if not image:
        pytest.skip("the project's pgbackrest image is not available")

    work = tmp_path_factory.mktemp("pgbrrepo")
    certs = _make_certs(work / "cert", stanza, "repo-host")
    repo = work / "repo"
    repo.mkdir()
    repo.chmod(0o777)  # the container runs as uid 999, this is a tmp dir

    conf = work / "pgbackrest.conf"
    conf.write_text(
        "[global]\n"
        "repo1-path=/var/lib/pgbackrest\n"
        "repo1-block=y\n"
        "repo1-bundle=y\n"
        # Retention lives on the machine that owns the disk. The client side
        # deliberately ships none, so if it ever started emitting retention
        # again this file is where the difference shows.
        "repo1-retention-full-type=count\n"
        "repo1-retention-full=2\n"
        "log-level-console=info\n"
        "log-path=/var/log/pgbackrest\n"
        "tls-server-address=0.0.0.0\n"
        f"tls-server-port={REPO_PORT}\n"
        "tls-server-ca-file=/etc/pgbackrest/cert/ca.crt\n"
        "tls-server-cert-file=/etc/pgbackrest/cert/server.crt\n"
        "tls-server-key-file=/etc/pgbackrest/cert/server.key\n"
        # The binding that matters: this client certificate, this stanza.
        f"tls-server-auth={stanza}={stanza}\n"
        f"\n[{stanza}]\n"
    )

    name = f"{project.name}_repo_host"
    _docker("rm", "-f", name)
    up = _docker(
        "run",
        "-d",
        "--name",
        name,
        "--network",
        f"{project.name}_default",
        "-v",
        f"{conf}:/etc/pgbackrest/pgbackrest.conf:ro",
        "-v",
        f"{certs}:/etc/pgbackrest/cert:ro",
        "-v",
        f"{repo}:/var/lib/pgbackrest",
        "--entrypoint",
        "/usr/sbin/gosu",
        image,
        "pgbackrest",
        "pgbackrest",
        "server",
    )
    if up.returncode != 0:
        pytest.skip(f"could not start the repo host: {up.stderr}")
    try:
        yield {
            "container": name,
            "certs": certs,
            "repo": repo,
            "stanza": stanza,
        }
    finally:
        logs = _docker("logs", name)
        print(
            "--- repo host logs ---\n"
            + (logs.stdout or "")
            + (logs.stderr or "")
        )
        _docker("rm", "-f", name)


def _info(project):
    out = project.run("pgbackrest-info", check=False, timeout=120)
    return out


@pytest.mark.slow
@requires_full_stack
def test_full_diff_and_incr_reach_a_real_repo_host(
    pgbackrest_project, repo_host
):
    """All three backup types land on a separate machine, over TLS.

    The assertion on sizes is the point of the exercise, not decoration: a
    differential after a small change must cost a fraction of the full. If
    block incrementals or bundling silently stopped working, every backup
    would still succeed and only this number would notice.
    """
    project = pgbackrest_project
    stanza = repo_host["stanza"]

    # Point the project at the repo host and hand it the client certificate.
    run_dir = project.home / ".odoo" / "run" / project.name
    dest = run_dir / "pgbackrest" / "cert"
    dest.mkdir(parents=True, exist_ok=True)
    for src, tgt in (
        ("ca.crt", "ca.crt"),
        ("client.crt", "client.crt"),
        ("client.key", "client.key"),
    ):
        shutil.copy(repo_host["certs"] / src, dest / tgt)
    (dest / "client.key").chmod(0o600)

    project.run("setting", f"PGBR_REPO_HOST={repo_host['container']}")
    project.run("setting", f"PGBR_REPO_HOST_PORT={REPO_PORT}")
    project.run("setting", "PGBR_BACKUP_FROM=here")
    project.run("reload", timeout=600)

    conf = (run_dir / "pgbackrest" / "pgbackrest.conf").read_text()
    directives = [
        ln.strip()
        for ln in conf.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    # The repository is over there, and so is retention - see
    # docs/12-pgbackrest.md. Emitting it here would mean the same number
    # maintained in two places.
    assert f"repo1-host={repo_host['container']}" in directives
    assert not any(d.startswith("repo1-path") for d in directives)
    assert not any(d.startswith("repo1-retention") for d in directives)

    project.run("up", "-d", timeout=600)
    project.run("pgbackrest", "stanza-create", check=False, timeout=300)
    project.run("pgbackrest", "check", timeout=300)

    project.run("pgbackrest", "backup", "--type", "full", timeout=900)
    _sql_insert(project, 20000)
    project.run("pgbackrest", "backup", "--type", "diff", timeout=900)
    _sql_insert(project, 100)
    project.run("pgbackrest", "backup", "--type", "incr", timeout=900)

    backups = _backups_on_repo_host(project)
    kinds = [b["type"] for b in backups]
    assert kinds == ["full", "diff", "incr"], kinds

    # And they really are on the far side, not in a local directory that
    # happened to work.
    listing = _docker(
        "exec",
        repo_host["container"],
        "ls",
        f"/var/lib/pgbackrest/backup/{stanza}",
    ).stdout
    for b in backups:
        assert b["label"] in listing, listing

    full = next(b for b in backups if b["type"] == "full")
    incr = next(b for b in backups if b["type"] == "incr")
    assert incr["repo_size"] < full["repo_size"] / 2, (
        f"incremental {incr['repo_size']} is not meaningfully smaller than "
        f"full {full['repo_size']} - block incrementals or bundling are off"
    )


def _sql_insert(project, rows):
    _run(
        [
            "docker",
            "compose",
            "-p",
            project.name,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            project.name.replace("-", "_"),
            "-c",
            "CREATE TABLE IF NOT EXISTS pgbr_probe(id serial, note text);",
            "-c",
            f"INSERT INTO pgbr_probe(note) SELECT 'x'||g "
            f"FROM generate_series(1,{rows}) g;",
        ],
        cwd=project.path,
        timeout=300,
    )


def _backups_on_repo_host(project):
    """Parse `info --output=json`, which is the documented machine format."""
    out = _run(
        [
            "docker",
            "compose",
            "-p",
            project.name,
            "exec",
            "-T",
            "pgbackrest",
            "gosu",
            "pgbackrest",
            "pgbackrest",
            "--stanza",
            project.name,
            "info",
            "--output=json",
        ],
        cwd=project.path,
        timeout=300,
    )
    data = json.loads(out.stdout)
    return [
        {
            "label": b["label"],
            "type": b["type"],
            "repo_size": b["info"]["repository"]["delta"],
        }
        for b in data[0]["backup"]
    ]
