"""Tests for the pgBackRest service integration.

Fast unit tests cover the two compose-time hooks (no Docker needed):
- ``pgbackrest/__after_settings.py`` forces RUN_PGBACKREST off on DEVMODE
  machines, refuses an external postgres, and clears the cron entries where
  they would have nothing to do
- ``pgbackrest/__after_compose.py`` injects the archive_command into postgres
  and mounts the shared configuration and socket - but only when enabled.
Plus smoke tests that the ``odoo pgbackrest`` CLI group is wired up.

A slow end-to-end test (`-m slow`) proves point-in-time recovery actually
undoes a change against a live stack.
"""

from __future__ import annotations

import importlib.util
import platform
import time
from pathlib import Path

import arrow
import pytest

from .conftest import requires_full_stack

# repo root: .../images/zodoo/src/zodoo/tests/test_lib_pgbackrest.py -> parents[4]
_PGBR_DIR = Path(__file__).resolve().parents[4] / "pgbackrest"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        f"pgbackrest_{name}", str(_PGBR_DIR / f"__{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def after_settings():
    return _load("after_settings").after_settings


@pytest.fixture(scope="module")
def after_compose():
    return _load("after_compose").after_compose


def _enabled_settings(**extra):
    """Baseline settings for an enabled project, with a throwaway HOST_RUN_DIR.

    after_compose renders the real configuration file, so every test that calls
    it needs somewhere to write - otherwise the tests would scribble into the
    developer's actual project directory.
    """
    base = {
        "RUN_PGBACKREST": "1",
        "PGBR_STANZA": "unittest",
        "POSTGRES_VERSION": "17",
    }
    base.update(extra)
    return base


# --------------------------------------------------------------------------- #
# __after_settings                                                             #
# --------------------------------------------------------------------------- #


def test_devmode_forces_pgbackrest_off(after_settings):
    settings = {
        "DEVMODE": "1",
        "RUN_PGBACKREST": "1",
        "RUN_POSTGRES": "1",
        "PGBR_FORCE_IN_DEVMODE": "0",
    }
    after_settings(settings, None)
    assert settings["RUN_PGBACKREST"] == "0"


def test_devmode_force_flag_keeps_pgbackrest_on(after_settings):
    settings = {
        "DEVMODE": "1",
        "RUN_PGBACKREST": "1",
        "RUN_POSTGRES": "1",
        "PGBR_FORCE_IN_DEVMODE": "1",
        "PGBR_INCR_CRON": "0 */6 * * *",
    }
    after_settings(settings, None)
    assert settings["RUN_PGBACKREST"] == "1"


def test_no_devmode_leaves_pgbackrest_untouched(after_settings):
    settings = {
        "DEVMODE": "0",
        "RUN_PGBACKREST": "1",
        "RUN_POSTGRES": "1",
        "PGBR_INCR_CRON": "0 */6 * * *",
    }
    after_settings(settings, None)
    assert settings["RUN_PGBACKREST"] == "1"


def test_external_postgres_disables_pgbackrest(after_settings):
    # pgbackrest reads PGDATA directly and connects over postgres' unix socket;
    # neither works against a server this stack does not manage.
    settings = {"DEVMODE": "0", "RUN_PGBACKREST": "1", "RUN_POSTGRES": "0"}
    after_settings(settings, None)
    assert settings["RUN_PGBACKREST"] == "0"


def test_cron_entries_cleared_when_disabled(after_settings):
    """A defined-but-idle job still starts the CLI on every tick.

    Measured at 0.44 s per start in #161; across a hundred instances that is
    real CPU spent to do nothing. An empty CRONJOB_* value is skipped by the
    cron daemon, so clearing is what removes the job.
    """
    settings = {"DEVMODE": "0", "RUN_PGBACKREST": "0", "RUN_POSTGRES": "1"}
    after_settings(settings, None)
    assert settings["CRONJOB_PGBACKREST_FULL"] == ""
    assert settings["CRONJOB_PGBACKREST_DIFF"] == ""
    assert settings["CRONJOB_PGBACKREST_INCR"] == ""


def test_incr_cron_cleared_when_no_schedule(after_settings):
    # Intra-day incrementals are opt-in. Without a schedule the entry would be
    # a bare command with no cron expression, which the daemon cannot parse.
    settings = {
        "DEVMODE": "0",
        "RUN_PGBACKREST": "1",
        "RUN_POSTGRES": "1",
        "PGBR_INCR_CRON": "",
    }
    after_settings(settings, None)
    assert settings["CRONJOB_PGBACKREST_INCR"] == ""
    # ... while the two that always have work keep theirs.
    assert "CRONJOB_PGBACKREST_FULL" not in settings


def test_incr_cron_kept_when_scheduled(after_settings):
    settings = {
        "DEVMODE": "0",
        "RUN_PGBACKREST": "1",
        "RUN_POSTGRES": "1",
        "PGBR_INCR_CRON": "0 */6 * * *",
    }
    after_settings(settings, None)
    assert "CRONJOB_PGBACKREST_INCR" not in settings


# --------------------------------------------------------------------------- #
# __after_compose                                                              #
# --------------------------------------------------------------------------- #


def test_archive_command_injected_when_enabled(after_compose, tmp_path):
    yml = {"services": {"postgres": {"environment": {}}}}
    after_compose(
        None,
        _enabled_settings(
            HOST_RUN_DIR=str(tmp_path), POSTGRES_CONFIG="shared_buffers=2GB;"
        ),
        yml,
        {},
    )
    pgconf = yml["services"]["postgres"]["environment"]["POSTGRES_CONFIG"]
    # existing config preserved, archiving appended
    assert "shared_buffers=2GB" in pgconf
    assert "wal_level=replica" in pgconf
    assert "archive_mode=on" in pgconf
    assert "archive-push" in pgconf
    # the stanza has to travel in the command - it is what tells pgbackrest
    # which repository path the segment belongs to
    assert "--stanza=unittest" in pgconf
    # and the whole command must be single-quoted: run.sh turns each entry
    # into `-c <entry>` on a bash command line, so unquoted spaces split the
    # value and postgres refuses to start with
    # `unrecognized configuration parameter "stanza"`.
    assert (
        "archive_command='pgbackrest --stanza=unittest archive-push %p'"
        in pgconf
    )


def test_nothing_injected_when_disabled(after_compose, tmp_path):
    yml = {"services": {"postgres": {"environment": {}, "volumes": []}}}
    after_compose(
        None, {"RUN_PGBACKREST": "0", "HOST_RUN_DIR": str(tmp_path)}, yml, {}
    )
    assert "POSTGRES_CONFIG" not in yml["services"]["postgres"]["environment"]
    assert yml["services"]["postgres"]["volumes"] == []


def test_socket_and_config_mounted(after_compose, tmp_path):
    """The two mounts the integration stands or falls on.

    pgbackrest cannot reach postgres over TCP, so the socket directory has to
    be shared; and the archive_command runs inside the postgres container, so
    that container needs the same configuration file the sidecar reads.

    All of them in the LONG form. This hook runs after `docker compose
    config`, which is the step that normalises "source:target" strings - a
    string added here reaches create_directories unnormalised, which then
    takes the volume name for a host path and raises NotImplementedError.
    """
    yml = {"services": {"postgres": {"environment": {}, "volumes": []}}}
    after_compose(None, _enabled_settings(HOST_RUN_DIR=str(tmp_path)), yml, {})
    vols = yml["services"]["postgres"]["volumes"]
    assert all(isinstance(v, dict) for v in vols)
    by_target = {v["target"]: v for v in vols}
    sock = by_target["/var/run/postgresql"]
    if platform.system() == "Linux":
        # On Linux it MUST be the same host directory zodoo itself connects
        # through - see the comment in __after_compose.py. A named volume here
        # locks the host out and breaks `odoo psql` and `odoo db reset`.
        assert sock["type"] == "bind", sock
        assert sock["source"].endswith("/postgres.socket"), sock
    else:
        assert sock["type"] == "volume" and sock["source"] == "postgres_socket"
    assert by_target["/var/spool/pgbackrest"]["source"] == "pgbackrest_spool"
    conf = by_target["/etc/pgbackrest"]
    assert conf["type"] == "bind"
    assert conf["source"].endswith("/pgbackrest")
    assert conf["read_only"] is True


def test_local_repository_is_mounted_into_postgres(after_compose, tmp_path):
    """archive-push runs in the POSTGRES container, so it needs the repository.

    The archive_command is executed by the postgres server process. With a
    local repository that means the repository volume has to be mounted there
    too - without it every segment fails with a missing archive.info and
    postgres retries forever while pg_wal grows.
    """
    yml = {"services": {"postgres": {"environment": {}, "volumes": []}}}
    after_compose(None, _enabled_settings(HOST_RUN_DIR=str(tmp_path)), yml, {})
    targets = {v["target"]: v for v in yml["services"]["postgres"]["volumes"]}
    assert targets["/var/lib/pgbackrest"]["source"] == "pgbackrest_data"


def test_repo_host_does_not_mount_a_local_repository(after_compose, tmp_path):
    # With a repo host, archive-push talks to the backup server over TLS and
    # never touches a local repository path. Mounting one would suggest this
    # machine owns storage that it does not.
    yml = {"services": {"postgres": {"environment": {}, "volumes": []}}}
    after_compose(
        None,
        _enabled_settings(
            HOST_RUN_DIR=str(tmp_path), PGBR_REPO_HOST="backup.example"
        ),
        yml,
        {},
    )
    targets = [v["target"] for v in yml["services"]["postgres"]["volumes"]]
    assert "/var/lib/pgbackrest" not in targets


def test_mounts_are_idempotent(after_compose, tmp_path):
    # `odoo reload` regenerates the compose file and the hook runs again; a
    # duplicated mount would make docker compose refuse to start.
    yml = {"services": {"postgres": {"environment": {}, "volumes": []}}}
    settings = _enabled_settings(HOST_RUN_DIR=str(tmp_path))
    after_compose(None, settings, yml, {})
    first = list(yml["services"]["postgres"]["volumes"])
    after_compose(None, settings, yml, {})
    assert yml["services"]["postgres"]["volumes"] == first


def test_list_environment_is_normalised(after_compose, tmp_path):
    yml = {"services": {"postgres": {"environment": ["FOO=bar"]}}}
    after_compose(None, _enabled_settings(HOST_RUN_DIR=str(tmp_path)), yml, {})
    env = yml["services"]["postgres"]["environment"]
    assert isinstance(env, dict)
    assert env["FOO"] == "bar"
    assert "archive_mode=on" in env["POSTGRES_CONFIG"]


def _directives(tmp_path):
    """The rendered configuration with comments and blank lines removed.

    The template explains itself at length - it names repo1-path and pg1-host
    in prose precisely to say when they must NOT be used. Asserting against the
    raw text would therefore match the explanation instead of the setting, so
    these tests look at the effective directives only.
    """
    conf = (tmp_path / "pgbackrest" / "pgbackrest.conf").read_text()
    return [
        line.strip()
        for line in conf.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_conf_written_with_local_repo(after_compose, tmp_path):
    after_compose(
        None,
        _enabled_settings(HOST_RUN_DIR=str(tmp_path)),
        {"services": {"postgres": {"environment": {}}}},
        {},
    )
    directives = _directives(tmp_path)
    assert "repo1-path=/var/lib/pgbackrest" in directives
    assert "[unittest]" in directives
    # A local repository is this machine's own, so retention applies here - and
    # it must be emitted even though no retention setting was passed in.
    # Without repo1-retention-full pgbackrest expires nothing at all, silently.
    assert "repo1-retention-full=14" in directives
    assert "repo1-retention-full-type=time" in directives
    # and postgres is reached through the socket, never over TCP
    assert "pg1-socket-path=/var/run/postgresql" in directives
    assert not any(d.startswith("pg1-host") for d in directives)


def test_conf_written_with_repo_host(after_compose, tmp_path):
    """When the repo host PULLS there must be no repo1-path and no retention.

    Both belong to the machine that owns the storage. Emitting them here would
    not just be noise - it would suggest this machine can expire backups, which
    is precisely the ability this shape exists to withhold.
    """
    after_compose(
        None,
        _enabled_settings(
            HOST_RUN_DIR=str(tmp_path),
            PGBR_REPO_HOST="backup.example",
            PGBR_REPO_HOST_TYPE="tls",
            PGBR_REPO_HOST_PORT="8432",
            PGBR_BACKUP_FROM="repo-host",
        ),
        {"services": {"postgres": {"environment": {}}}},
        {},
    )
    directives = _directives(tmp_path)
    assert "repo1-host=backup.example" in directives
    assert "repo1-host-type=tls" in directives
    assert not any(d.startswith("repo1-path") for d in directives)
    assert not any(d.startswith("repo1-retention") for d in directives)
    # the client certificate is an identity, not a key to the repository
    assert "repo1-host-cert-file=/etc/pgbackrest/cert/client.crt" in directives
    # and this side has to answer the repo host, which is what pulls
    assert "tls-server-auth=backup.example=unittest" in directives


def test_the_two_tls_ports_are_independent(after_compose, tmp_path):
    """Outbound (to the repo host) and inbound (from it) are separate ports.

    They are two listeners on two machines in opposite directions. Sharing one
    setting means a firewall rule written for one silently describes the other,
    and it makes "put it on 443 because that is all that gets out" impossible.
    """
    yml = {
        "services": {"postgres": {"environment": {}}, "pgbackrest": {}},
    }
    after_compose(
        None,
        _enabled_settings(
            HOST_RUN_DIR=str(tmp_path),
            PGBR_REPO_HOST="backup.example",
            PGBR_REPO_HOST_PORT="443",
            PGBR_TLS_SERVER_PORT="9443",
            PGBR_BACKUP_FROM="repo-host",
        ),
        yml,
        {},
    )
    directives = _directives(tmp_path)
    assert "repo1-host-port=443" in directives
    assert "tls-server-port=9443" in directives
    # the inbound port has to be reachable from outside the compose network,
    # because the repo host is the side that runs the backup and pulls
    # long form: this hook runs after `docker compose config`, so nothing
    # normalises a "9443:9443" string any more
    assert yml["services"]["pgbackrest"]["ports"] == [
        {
            "mode": "ingress",
            "target": 9443,
            "published": "9443",
            "protocol": "tcp",
        }
    ]


def test_no_port_published_without_a_repo_host(after_compose, tmp_path):
    # A local repository serves nobody. Opening a port for it would be an
    # attack surface in exchange for nothing.
    yml = {
        "services": {"postgres": {"environment": {}}, "pgbackrest": {}},
    }
    after_compose(None, _enabled_settings(HOST_RUN_DIR=str(tmp_path)), yml, {})
    assert "ports" not in yml["services"]["pgbackrest"]


def test_pushing_to_a_repo_host_still_leaves_retention_over_there(
    after_compose, tmp_path
):
    """BACKUP_FROM=here: outbound only, and STILL no retention on this side.

    Retention belongs to whoever manages the disk, which is the backup server
    in both repo-host modes. Emitting it here would mean the same number
    maintained on every Odoo host, drifting from the one that actually governs
    the free space. The backup server runs its own scheduled `expire` instead.
    """
    yml = {"services": {"postgres": {"environment": {}}, "pgbackrest": {}}}
    after_compose(
        None,
        _enabled_settings(
            HOST_RUN_DIR=str(tmp_path),
            PGBR_REPO_HOST="backup.example",
            PGBR_BACKUP_FROM="here",
            PGBR_RETENTION_FULL="30",
        ),
        yml,
        {},
    )
    directives = _directives(tmp_path)
    assert "repo1-host=backup.example" in directives
    assert not any(d.startswith("repo1-retention") for d in directives)
    # the repository still lives over there
    assert not any(d.startswith("repo1-path") for d in directives)
    # nothing listens here, so no server certificate and no open port
    assert not any(d.startswith("tls-server") for d in directives)
    assert "ports" not in yml["services"]["pgbackrest"]


def test_backup_from_defaults_to_pushing(after_compose, tmp_path):
    # An unset value must not silently produce the shape that needs an inbound
    # port - that one would simply never connect, and only at backup time.
    after_compose(
        None,
        _enabled_settings(
            HOST_RUN_DIR=str(tmp_path),
            PGBR_REPO_HOST="backup.example",
        ),
        {"services": {"postgres": {"environment": {}}}},
        {},
    )
    directives = _directives(tmp_path)
    assert not any(d.startswith("tls-server") for d in directives)


def test_a_local_repository_always_gets_retention(after_compose, tmp_path):
    """The one case where an empty setting must NOT mean "keep everything".

    With no repo host there is no other machine to run expire, so leaving
    retention out would mean nothing ever cleans up - pgbackrest says so once
    in a log line and then keeps every backup forever.
    """
    after_compose(
        None,
        _enabled_settings(HOST_RUN_DIR=str(tmp_path), PGBR_RETENTION_FULL=""),
        {"services": {"postgres": {"environment": {}}}},
        {},
    )
    assert "repo1-retention-full=14" in _directives(tmp_path)


def test_cipher_emitted_in_global_for_both_shapes(after_compose, tmp_path):
    """Encryption belongs in [global], and to both repository shapes.

    [global] rather than the stanza section because the pgBackRest guide says
    so: `info` has to be able to read every stanza. And to both shapes because
    encryption is what makes a repository on somebody else's storage
    acceptable - which is exactly the repo-host case.
    """
    for extra in ({}, {"PGBR_REPO_HOST": "backup.example"}):
        after_compose(
            None,
            _enabled_settings(
                HOST_RUN_DIR=str(tmp_path),
                PGBR_CIPHER_PASS="s3cret-passphrase",
                **extra,
            ),
            {"services": {"postgres": {"environment": {}}}},
            {},
        )
        conf = (tmp_path / "pgbackrest" / "pgbackrest.conf").read_text()
        directives = _directives(tmp_path)
        assert "repo1-cipher-type=aes-256-cbc" in directives
        assert "repo1-cipher-pass=s3cret-passphrase" in directives
        # in [global], not inside the stanza section
        head = conf.split("[" + _enabled_settings()["PGBR_STANZA"] + "]")[0]
        assert "repo1-cipher-pass" in head


def test_no_cipher_without_a_passphrase(after_compose, tmp_path):
    """An empty passphrase means OFF, never a made-up default.

    Unlike retention, guessing here would be actively harmful: a passphrase
    this code invented would be unknown to anybody, and the backups would be
    unrecoverable while looking encrypted and healthy.
    """
    after_compose(
        None,
        _enabled_settings(HOST_RUN_DIR=str(tmp_path), PGBR_CIPHER_PASS=""),
        {"services": {"postgres": {"environment": {}}}},
        {},
    )
    assert not any(d.startswith("repo1-cipher") for d in _directives(tmp_path))


def test_retention_archive_only_emitted_when_set(after_compose, tmp_path):
    # Empty means "keep WAL for every retained full backup", i.e. a continuous
    # PITR window. Writing a default here would silently narrow that.
    after_compose(
        None,
        _enabled_settings(HOST_RUN_DIR=str(tmp_path)),
        {"services": {"postgres": {"environment": {}}}},
        {},
    )
    assert not any(
        d.startswith("repo1-retention-archive") for d in _directives(tmp_path)
    )


# --------------------------------------------------------------------------- #
# CLI wiring                                                                   #
# --------------------------------------------------------------------------- #


def test_pgbackrest_cli_group_registered():
    from zodoo.cli import cli

    grp = cli.commands.get("pgbackrest")
    assert grp is not None
    assert {
        "backup",
        "info",
        "check",
        "expire",
        "restore",
        "switch-wal",
        "stanza-create",
    } <= set(grp.commands.keys())


def test_status_resolves_to_setup_status():
    """`odoo status` must show the project info (setup status).

    The original bug was barman/status winning an AliasedGroup tie by
    registration order. pgbackrest deliberately names its listing command
    `info` rather than `status` so the tie cannot arise again - this guards
    that it stays that way.
    """
    import click
    from zodoo.cli import cli
    from zodoo import lib_setup

    ctx = click.Context(cli)
    assert cli.get_command(ctx, "status") is lib_setup.status


def test_pgbackrest_info_toplevel_shortcut_registered():
    from zodoo.cli import cli
    from zodoo import lib_pgbackrest

    cmd = cli.commands.get("pgbackrest-info")
    assert cmd is not None
    assert cmd.name == "pgbackrest-info"
    assert cmd is lib_pgbackrest.pgbackrest_info_toplevel


def test_pgbackrest_prefix_resolves_to_the_group():
    """`odoo pgb` must resolve to the group, not to the top-level shortcut."""
    import click
    from zodoo.cli import cli

    ctx = click.Context(cli)
    for prefix in ("pgb", "pgback", "pgbackrest"):
        assert (
            cli.get_command(ctx, prefix) is cli.commands["pgbackrest"]
        ), prefix
    assert (
        cli.get_command(ctx, "pgbackrest-i") is cli.commands["pgbackrest-info"]
    )


def test_guard_update_enabled():
    from zodoo import lib_pgbackrest as p

    class C:
        run_pgbackrest = "1"
        pgbr_guard_update = "1"

    class D:
        run_pgbackrest = "1"
        pgbr_guard_update = "0"

    class E:
        run_pgbackrest = "0"
        pgbr_guard_update = "1"

    assert p.guard_update_enabled(C()) is True
    assert p.guard_update_enabled(D()) is False
    assert p.guard_update_enabled(E()) is False


# --------------------------------------------------------------------------- #
# target parsing                                                               #
# --------------------------------------------------------------------------- #


def test_parse_age_valid_is_in_past():
    from zodoo import lib_pgbackrest as p

    parsed = arrow.get(p._parse_age("2h"), "YYYY-MM-DD HH:mm:ssZZ")
    assert parsed < arrow.now()


def test_parse_age_invalid_aborts():
    from zodoo import lib_pgbackrest as p

    with pytest.raises(SystemExit):
        p._parse_age("soon")


def test_parse_target_time_valid():
    from zodoo import lib_pgbackrest as p

    assert p._parse_target_time("2026-05-31 14:25:00").startswith(
        "2026-05-31 14:25:00"
    )


def test_parse_target_time_never_silently_truncates_to_midnight():
    """The regression that a real PITR run found, and the tests did not.

    `select now()` gives "2026-08-25 18:57:24.353049+00". Parsed with a list
    of arrow formats tried in order, every format containing a time fails on
    the fractional seconds and "YYYY-MM-DD" then matches the PREFIX - arrow
    does not anchor. The result was midnight, silently, and the database was
    recovered to 18 hours before the requested point.

    A backup tool that succeeds at the wrong thing is worse than one that
    fails, so this asserts the time survives rather than just that it parses.
    """
    from zodoo import lib_pgbackrest as p

    for raw in (
        "2026-05-31 14:25:24.353049+00",
        "2026-05-31 14:25:24+00:00",
        "2026-05-31T14:25:24.353049",
        "2026-05-31 14:25:24",
    ):
        got = p._parse_target_time(raw)
        assert "14:25:24" in got, f"{raw} -> {got}"
        assert not got.startswith("2026-05-31 00:00:00"), f"{raw} -> {got}"


def test_parse_target_time_bare_date_is_midnight():
    # Still allowed - somebody typing a bare date means midnight. The defect
    # was truncating a full timestamp TO it, not honouring an explicit date.
    from zodoo import lib_pgbackrest as p

    assert p._parse_target_time("2026-05-31").startswith("2026-05-31 00:00:00")


def test_parse_target_time_future_aborts():
    from zodoo import lib_pgbackrest as p

    future = arrow.now().shift(days=1).format("YYYY-MM-DD HH:mm:ss")
    with pytest.raises(SystemExit):
        p._parse_target_time(future)


def test_parse_target_time_idempotent():
    # The CLI passes a plain timestamp; the normalised tz-aware result must
    # re-parse to itself, because the value passes through here more than once.
    from zodoo import lib_pgbackrest as p

    once = p._parse_target_time("2026-05-31 14:25:00")
    assert p._parse_target_time(once) == once
    assert p._parse_target_time(p._parse_age("2h"))


def test_list_backups_parses_info_json(monkeypatch):
    """`info --output=json` is the source, not the human-readable text.

    Unlike barman's list-backup there is a documented machine format here, and
    it carries the backup type - which now matters, because a label alone no
    longer says whether a state is self-contained.
    """
    from zodoo import lib_pgbackrest as p

    payload = """[{"name":"unittest","backup":[
      {"label":"20260601-020000F","type":"full",
       "timestamp":{"start":1780000000,"stop":1780000600},
       "info":{"repository":{"delta":1048576}}},
      {"label":"20260602-020000D","type":"diff",
       "timestamp":{"start":1780086400,"stop":1780086500},
       "info":{"repository":{"delta":2097152}}}]}]"""
    monkeypatch.setattr(p, "_pgbr_capture", lambda config, args: payload)
    rows = p._list_backups(None)
    assert [r[1] for r in rows] == ["20260602-020000D", "20260601-020000F"]
    assert "diff" in rows[0][0]
    assert "MiB in repo" in rows[0][0]


def test_list_backups_survives_broken_output(monkeypatch):
    # A repository that cannot be reached must not crash the picker - it should
    # simply offer no backups, so the operator still gets the time/name options.
    from zodoo import lib_pgbackrest as p

    monkeypatch.setattr(p, "_pgbr_capture", lambda config, args: "not json")
    assert p._list_backups(None) == []


# --------------------------------------------------------------------------- #
# Slow end-to-end: point-in-time recovery actually undoes a change             #
# --------------------------------------------------------------------------- #


def _sql(project, sql, check=True):
    """Run a single SQL statement via `odoo psql --sql` and return stdout."""
    res = project.run("psql", "--sql", sql, check=check, timeout=120)
    return res.stdout or ""


def _retry(fn, *, timeout, interval=3.0, what="condition"):
    """Poll fn() until it returns truthy or timeout (seconds) elapses."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = fn()
            if last:
                return last
        except Exception as ex:  # noqa: BLE001 - surfaced on timeout
            last = ex
        time.sleep(interval)
    raise AssertionError(f"Timed out waiting for {what} (last={last!r})")


@pytest.mark.slow
@requires_full_stack
def test_e2e_pitr_undoes_a_change(pgbackrest_project):
    """Full PITR cycle: a change made after a restore point is rolled back.

    1. take a full backup
    2. write a row we want to KEEP, then create a named restore point
    3. write a row we want to UNDO (the "mistake"), after the restore point
    4. restore to the restore point
    5. assert the KEEP row survived, the UNDO row is gone, and postgres came
       back read-write (auto-promoted, not stuck in read-only recovery)
    """
    project = pgbackrest_project

    # Archiving has to work before a backup can complete: with archive-check=y
    # pgbackrest waits for the WAL written during the backup to arrive in the
    # repository and fails the backup if it does not. `check` output is printed
    # each attempt so a CI failure says which part of the path is broken.
    def _backup_ready():
        project.run("pgbackrest", "check", check=False, timeout=120)
        return (
            project.run(
                "pgbackrest",
                "backup",
                "--type",
                "full",
                check=False,
                timeout=600,
            ).returncode
            == 0
        )

    _retry(
        _backup_ready,
        timeout=900,
        interval=15,
        what="first pgbackrest full backup to succeed",
    )

    # KEEP data + restore point (the recovery target).
    _sql(project, "DROP TABLE IF EXISTS pitr_demo")
    _sql(project, "CREATE TABLE pitr_demo (note text)")
    _sql(project, "INSERT INTO pitr_demo VALUES ('keep')")
    _sql(project, "SELECT pg_create_restore_point('pitr_marker')")
    # Complete and archive the segment holding the restore point. Unlike the
    # barman path this needs no sleep afterwards: `switch-wal` ends with a
    # `check`, which returns only once the segment is really in the repository.
    project.run("pgbackrest", "switch-wal", check=False, timeout=180)

    # The change to undo, made strictly AFTER the restore point.
    _sql(project, "INSERT INTO pitr_demo VALUES ('undo_me')")
    project.run("pgbackrest", "switch-wal", check=False, timeout=180)

    # Destructive: overwrites the postgres data directory.
    project.run_force(
        "pgbackrest",
        "restore",
        "--target-name",
        "pitr_marker",
        timeout=900,
    )

    _retry(
        lambda: project.run(
            "psql", "--sql", "SELECT 1", check=False, timeout=60
        ).returncode
        == 0,
        timeout=300,
        interval=5,
        what="postgres to accept connections after the restore",
    )
    _retry(
        lambda: "f"
        in _sql(project, "SELECT pg_is_in_recovery()", check=False)
        .lower()
        .split(),
        timeout=300,
        interval=5,
        what="postgres to finish recovery and promote (read-write)",
    )

    # The KEEP row survived; the UNDO row was rolled back.
    notes = _sql(project, "SELECT string_agg(note, ',') FROM pitr_demo")
    assert (
        "keep" in notes
    ), f"expected the pre-restore-point row to survive: {notes!r}"
    assert (
        "undo_me" not in notes
    ), f"post-restore-point row should be gone: {notes!r}"

    # Promotion check: a write must succeed (not stuck in read-only recovery).
    project.run(
        "psql", "--sql", "CREATE TABLE pitr_promote_check (x int)", timeout=60
    )


# --------------------------------------------------------------------------- #
# Enrolment
#
# What is worth testing here is not the HTTP plumbing but the two ways this
# can quietly go wrong: writing a private key that others can read, and
# accepting a stanza name the server will reject anyway - the second one only
# surfacing after an admin has already been asked to approve something.
# --------------------------------------------------------------------------- #
class _Cfg:
    """Minimal stand-in for the click config object."""

    def __init__(self, tmp_path, **kw):
        self.HOST_RUN_DIR = str(tmp_path)
        self.project_name = kw.pop("project_name", "demo")
        self.PGBR_ENROLL_URL = kw.pop(
            "PGBR_ENROLL_URL", "https://backup.example:8444"
        )
        self.pgbr_stanza = kw.pop("pgbr_stanza", None)
        for k, v in kw.items():
            setattr(self, k, v)


@pytest.fixture
def enroll(monkeypatch):
    """The register command with its network and settings calls captured."""
    from zodoo import lib_pgbackrest as mod

    written = {}
    monkeypatch.setattr(
        mod, "update_setting", lambda c, k, v: written.__setitem__(k, v), raising=False
    )
    import zodoo.tools as _tools

    monkeypatch.setattr(
        _tools, "update_setting", lambda c, k, v: written.__setitem__(k, v)
    )
    return mod, written


def _approved(stanza="demo"):
    return {
        "status": "approved",
        "stanza": stanza,
        "repo_host": "10.222.0.106",
        "repo_port": 8443,
        "cipher_type": "aes-256-cbc",
        "cipher_pass": "s3cret-passphrase",
        "ca_cert": "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----\n",
        "client_cert": "-----BEGIN CERTIFICATE-----\ncrt\n-----END CERTIFICATE-----\n",
        "client_key": "-----BEGIN PRIVATE KEY-----\nkey\n-----END PRIVATE KEY-----\n",
    }


def _run_register(mod, config, calls, name=None, note=""):
    """Invoke the command body directly, past click's decorators."""
    monkey = calls
    mod._enroll_call = lambda cfg, method, path, payload=None: monkey(
        method, path, payload
    )
    return mod.pgbackrest_register.callback.__wrapped__(config, name, note)


def test_register_writes_the_private_key_unreadable_to_others(
    enroll, tmp_path, monkeypatch
):
    """A client key others can read is a key pgBackRest refuses - rightly.

    The mode is the whole point of this test: everything else about the
    handover can be repeated, but a key written 0644 into a shared run
    directory has already leaked by the time anyone notices.
    """
    mod, written = enroll
    cdir = tmp_path / "pgbackrest" / "cert"
    cdir.mkdir(parents=True)
    (cdir / "enroll.json").write_text(
        '{"stanza": "demo", "request_id": "r1", "token": "t1"}'
    )

    def calls(method, path, payload=None):
        assert method == "GET" and "request_id=r1" in path
        return _approved()

    _run_register(mod, _Cfg(tmp_path), calls)

    key = cdir / "client.key"
    assert key.read_text().startswith("-----BEGIN PRIVATE KEY-----")
    assert (key.stat().st_mode & 0o077) == 0, oct(key.stat().st_mode)
    assert written["PGBR_CIPHER_PASS"] == "s3cret-passphrase"
    assert written["PGBR_REPO_HOST"] == "10.222.0.106"
    assert written["PGBR_REPO_HOST_PORT"] == "8443"
    assert written["PGBR_BACKUP_FROM"] == "here"
    assert written["RUN_PGBACKREST"] == "1"
    # A finished request must not linger and look open forever.
    assert not (cdir / "enroll.json").exists()


def test_register_refuses_a_stanza_name_the_server_would_reject(enroll, tmp_path):
    """Better to stop here than after an admin has approved something.

    The server enforces the same pattern. Letting a bad name through means the
    failure lands after a human has already been pulled in.
    """
    mod, _ = enroll

    def calls(*a, **kw):  # pragma: no cover - must never be reached
        raise AssertionError("the service was contacted despite a bad name")

    # "Demo" is deliberately absent: the command lowercases the name, exactly
    # as the service does, so it is a valid name and not a rejected one.
    for bad in ("1demo", "a", "demo!", "x" * 42, "-demo", "de mo"):
        with pytest.raises(SystemExit):
            _run_register(mod, _Cfg(tmp_path), calls, name=bad)


def _approved_with_filestore(**over):
    d = _approved()
    d.update(
        {
            "wo_url": "https://10.222.0.106:8444/demo/",
            "wo_user": "demo",
            "wo_password": "upload-password",
            "wo_recipient": "age1qqqq",
        }
    )
    d.update(over)
    return d


def _prepared(tmp_path, answer):
    cdir = tmp_path / "pgbackrest" / "cert"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "enroll.json").write_text(
        '{"stanza": "demo", "request_id": "r1", "token": "t1"}'
    )
    return lambda method, path, payload=None: answer


def test_register_sets_up_both_streams(enroll, tmp_path):
    """One approval, two streams.

    A machine that only backs up its database is a machine whose restore is
    missing every attachment - so the answer carries the filestore access too,
    and it has to land in the settings.
    """
    mod, written = enroll
    _run_register(
        mod, _Cfg(tmp_path), _prepared(tmp_path, _approved_with_filestore())
    )
    assert written["OFFSITE_WO_URL"] == "https://10.222.0.106:8444/demo/"
    assert written["OFFSITE_REST_USER"] == "demo"
    assert written["OFFSITE_REST_PASSWORD"] == "upload-password"
    assert written["OFFSITE_WO_RECIPIENT"] == "age1qqqq"
    assert written["RUN_OFFSITE"] == "1"
    assert written["RUN_PGBACKREST"] == "1"


def test_filestore_stays_off_without_a_public_key(enroll, tmp_path):
    """No recipient means no encryption - so the stream must not switch on.

    This is the one failure mode worth a test of its own: everything would
    look configured, the runs would report success, and attachments would be
    leaving the machine in the clear.
    """
    mod, written = enroll
    _run_register(
        mod,
        _Cfg(tmp_path),
        _prepared(tmp_path, _approved_with_filestore(wo_recipient="")),
    )
    assert "RUN_OFFSITE" not in written
    assert "OFFSITE_WO_RECIPIENT" not in written
    # The database stream is unaffected - one missing key must not cost both.
    assert written["RUN_PGBACKREST"] == "1"


# --------------------------------------------------------------------------- #
# Archivierung darf nicht still scheitern
# --------------------------------------------------------------------------- #
def _deps(yml):
    d = yml["services"]["postgres"].get("depends_on") or []
    return list(d.keys()) if isinstance(d, dict) else list(d)


def test_postgres_pulls_the_sidecar_up_with_it(after_compose, tmp_path):
    """Starting postgres alone must bring the sidecar too.

    postgres archives from its first second, and the stanza that archive-push
    writes into is created by the sidecar's entrypoint. Without this
    dependency, `docker compose up -d postgres` - or a partial restart, or
    `odoo db reset` - leaves every WAL push failing on a missing
    archive.info, and nothing says so: postgres keeps serving, the WAL piles
    up, and the backup everyone believes in does not exist.

    This is exactly how the end-to-end test failed for days: postgres up,
    sidecar one step later, the reset timing out behind an archive queue that
    could never drain.
    """
    yml = {"services": {"postgres": {"environment": {}}}}
    after_compose(None, _enabled_settings(HOST_RUN_DIR=str(tmp_path)), yml, {})
    assert "pgbackrest" in _deps(yml), _deps(yml)


def test_no_such_dependency_when_disabled(after_compose, tmp_path):
    """A project without pgBackRest must not gain a dependency on it."""
    yml = {"services": {"postgres": {"environment": {}}}}
    after_compose(
        None,
        {"RUN_PGBACKREST": "0", "HOST_RUN_DIR": str(tmp_path)},
        yml,
        {},
    )
    assert "pgbackrest" not in _deps(yml), _deps(yml)


def test_archive_queue_is_bounded(after_compose, tmp_path):
    """A failing archive must not be able to fill the disk.

    archive-push-queue-max lets pgBackRest give up on the oldest segments
    instead of letting the volume run full. That loses WAL - loudly, with a
    warning - which is the better of two bad outcomes: a gap in the archive is
    recoverable from the next full backup, a full disk takes the database down
    with it.
    """
    after_compose(
        None,
        _enabled_settings(HOST_RUN_DIR=str(tmp_path)),
        {"services": {"postgres": {"environment": {}}}},
        {},
    )
    assert any(
        d.startswith("archive-push-queue-max=") for d in _directives(tmp_path)
    ), "no bound on the archive queue"


def test_the_dependency_points_one_way_only():
    """postgres -> pgbackrest, and never back.

    Both directions at once is not a redundancy, it is a cycle: compose
    refuses the whole project with "dependency cycle detected: pgbackrest ->
    postgres -> pgbackrest", and nothing starts at all. That is how it failed
    in CI once the postgres side was added.

    The sidecar waits in its entrypoint instead, on the postgres socket -
    which is the path that actually has to work, and which a compose health
    state says nothing about.
    """
    import yaml

    compose = yaml.safe_load((_PGBR_DIR / "docker-compose.yml").read_text())
    sidecar = compose["services"]["pgbackrest"]
    assert "depends_on" not in sidecar, (
        "the sidecar must not depend on postgres - postgres depends on it, "
        "and both together is a cycle"
    )


def test_sidecar_and_postgres_share_one_socket_source(after_compose, tmp_path):
    """Both must mount the SAME thing at /var/run/postgresql.

    pgbackrest cannot reach postgres over TCP - it needs the socket. If the
    two mount different sources there, the sidecar sits in front of an empty
    directory and every command fails with "could not connect".

    And on Linux the shared source has to be the host directory zodoo uses
    too, or `odoo psql` and `odoo db reset` stop working the moment pgBackRest
    is switched on. That is not hypothetical: it is what made the end-to-end
    test time out for days, invisible on macOS because zodoo falls back to TCP
    there.
    """
    yml = {
        "services": {
            "postgres": {"environment": {}, "volumes": []},
            "pgbackrest": {"volumes": []},
        }
    }
    after_compose(None, _enabled_settings(HOST_RUN_DIR=str(tmp_path)), yml, {})
    def _sock(svc):
        for v in yml["services"][svc]["volumes"]:
            if v.get("target") == "/var/run/postgresql":
                return v
        raise AssertionError(f"{svc} has no socket mount")
    a, b = _sock("postgres"), _sock("pgbackrest")
    assert (a["type"], a["source"]) == (b["type"], b["source"]), (a, b)
