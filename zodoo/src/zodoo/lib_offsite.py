from pathlib import Path

import click

from .cli import cli, pass_config
from .lib_clickhelpers import AliasedGroup
from .tools import abort
from .tools import __get_cmd

# File name of the dump that the offsite run pulls itself when pgbackrest is off.
#
# A fixed name on purpose: the file is overwritten on every run instead of
# piling up in DUMPS_PATH. For restic that costs nothing - it deduplicates
# against last night's state and stores only the difference.
OFFSITE_DB_DUMP = "offsite-db.dump"


@cli.group(
    cls=AliasedGroup,
    help="Encrypted offsite backup (restic; normally against our backup server).",
)
@pass_config
def offsite(config):
    pass


def _ensure_offsite(config):
    if not getattr(config, "run_offsite", False):
        abort(
            "Offsite backup is not enabled. Set RUN_OFFSITE=1 (on DEVMODE "
            "machines also OFFSITE_FORCE_IN_DEVMODE=1), then "
            "`odoo reload && odoo build offsite`."
        )
    if not (config.OFFSITE_REPO or "").strip():
        abort(
            "OFFSITE_REPO is empty - no offsite target is configured.\n"
            "For our backup server just run `odoo offsite register`; that "
            "requests an area and stores everything needed.\n"
            "By hand, e.g. a Hetzner Storage Box:\n"
            "  OFFSITE_REPO=sftp:u123456@u123456.your-storagebox.de:23/zodoo/project"
        )


def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _state_dir(config):
    """Writable host directory for the offsite container's own state.

    Currently the ledger of already-uploaded filestore files. Separate from
    the read-only $HOST_RUN_DIR/offsite (keys, certificate) on purpose: that
    one is mounted read-only so a backup run cannot touch credentials.
    """
    d = Path(config.HOST_RUN_DIR) / "offsite.state"
    # If a compose run got here first, docker created the missing bind-mount
    # source itself - and it guesses, so it may well have created an empty
    # FILE. The mount then succeeds, /var/lib/offsite-state is a file inside
    # the container, and the ledger cannot be written. Same trap as /logs in
    # postgres/run.sh. An empty file here is a docker artefact and nothing
    # else, so it is safe to replace; anything non-empty we refuse to touch.
    if d.exists() and not d.is_dir():
        if d.is_file() and d.stat().st_size == 0:
            d.unlink()
        else:
            abort(
                f"{d} exists but is not a directory. It has to be the "
                "directory holding the offsite ledger; move it out of the way."
            )
    d.mkdir(parents=True, exist_ok=True)
    return d


def _wo_configured(config):
    return bool(
        (getattr(config, "OFFSITE_WO_URL", "") or "").strip()
        and (getattr(config, "OFFSITE_WO_RECIPIENT", "") or "").strip()
    )


def _wo_db_configured(config):
    return bool(
        (getattr(config, "OFFSITE_WO_URL", "") or "").strip()
        and (getattr(config, "OFFSITE_WO_DB_RECIPIENT", "") or "").strip()
    )


def _offsite_run(config, args, env=None):
    """Start the offsite container for a single run.

    The service sits in the "manual" profile (it is not a long-running
    service), hence profile="all" here instead of the default profile -
    otherwise `docker compose run` does not know the service.
    """
    import subprocess

    _ensure_offsite(config)
    # The write-only filestore ledger lives here. Created before compose runs:
    # a bind-mount source that does not exist is created by docker as
    # root-owned, and the container could then not write its ledger.
    _state_dir(config)
    # A fixed container name rules out concurrent runs: docker refuses a second
    # container of the same name. The entrypoint relies on that when it breaks a
    # stale lock - without this exclusion it could break the lock of a backup
    # that is still running.
    name = f"{config.project_name}_offsite_run"
    cmd = __get_cmd(config, profile="all") + [
        "run",
        "--rm",
        "-T",
        "--name",
        name,
    ]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += ["offsite"]
    cmd += args
    return subprocess.check_call(cmd)


def _offsite_run_raw(config, args, env=None, name_suffix="offsite_run"):
    """Run the offsite container without requiring a restic configuration.

    Used by the write-only paths, which have neither repository nor passphrase.

    ``name_suffix`` exists for the minutely WAL job. Everything else shares the
    fixed container name, which is what rules out concurrent runs - but docker
    rejects a duplicate name with a hard error, and a job that runs every minute
    must not fail every minute just because a nightly base backup upload is
    still going. The WAL job therefore gets its own container name and is
    serialised inside the container by a lock on the (host-mounted) state
    directory instead, where a busy lock is a quiet success.
    """
    import subprocess

    _state_dir(config)
    name = f"{config.project_name}_{name_suffix}"
    cmd = __get_cmd(config, profile="all") + [
        "run",
        "--rm",
        "-T",
        "--name",
        name,
    ]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += ["offsite"]
    cmd += args
    return subprocess.check_call(cmd)


def _dump_db_for_offsite(config):
    """Pull a fresh database dump for the offsite run.

    With pgbackrest running, the database is already in the archive via WAL plus
    base backup and there is nothing to do here. Without it, the container would
    find nothing but the filestore - and an archive of nothing but attachments
    looks like a backup until somebody wants to restore.

    Returns the file name the container should pick up.
    """
    from .lib_backup import _backup_pgdump

    dumps = Path(config.dumps_path)
    dumps.mkdir(parents=True, exist_ok=True)
    final = dumps / OFFSITE_DB_DUMP
    # Write next to it first, then rename: if the dump aborts, the previous
    # run's state is still there instead of both states being missing.
    tmp = dumps / (OFFSITE_DB_DUMP + ".new")
    if tmp.exists():
        tmp.unlink()

    click.secho(
        f"offsite: pgbackrest is not active - pulling a fresh dump to {final}",
        fg="yellow",
    )
    _backup_pgdump(
        config,
        tmp,
        config.DBNAME,
        config.DB_HOST,
        config.DB_PORT,
        config.DB_USER,
        config.DB_PWD,
        "custom",
        # Uncompressed (-Z0), and that is not an oversight: restic compares the
        # dump against last night's and stores only the changed blocks -
        # compression happens afterwards via OFFSITE_COMPRESSION anyway. A
        # gzipped dump, by contrast, changes over its whole length and lands in
        # the repository in full every night.
        0,
        1,
        False,
        False,
        (),
    )
    tmp.replace(final)
    return final.name


@offsite.command(
    name="backup",
    help="Run an offsite backup now (the same run as the cronjob).",
)
@pass_config
def offsite_backup(config):
    # This hangs in the shared cronjobs daemon (CRONJOB_OFFSITE_BACKUP) and
    # therefore runs on EVERY project. Without offsite configuration it has to
    # be a quiet success, otherwise every other project reports a cron failure
    # every night.
    if not getattr(config, "run_offsite", False):
        click.secho(
            "Offsite backup is not enabled (RUN_OFFSITE=0); skipped.",
            fg="yellow",
        )
        return
    # Both streams write-only means restic is not used at all - then a run must
    # not demand a repository or a passphrase. The passphrase is the most
    # expensive secret in the whole setup, and whoever does not need it should
    # not have to hold it.
    if _wo_configured(config) and _wo_db_configured(config):
        _state_dir(config)
        _offsite_run_raw(config, ["backup"])
        return

    if not (config.OFFSITE_REPO or "").strip():
        click.secho(
            "Offsite backup is enabled but neither OFFSITE_REPO nor a complete "
            "write-only target is configured - nothing is being backed up.",
            fg="red",
        )
        return

    # Without pgbackrest there is no database state for the container to pick
    # up - so we create it here. With OFFSITE_INCLUDE_DUMPS=1 all of DUMPS_PATH
    # is included anyway, which would make this duplicated work.
    env = {}
    if not _truthy(getattr(config, "run_pgbackrest", "0")) and not _truthy(
        getattr(config, "OFFSITE_INCLUDE_DUMPS", "0")
    ):
        env["OFFSITE_DB_DUMP"] = _dump_db_for_offsite(config)

    _offsite_run(config, ["backup"], env=env)


@offsite.command(
    name="filestore",
    help=(
        "Back up the filestore to the write-only target. Needs no repository "
        "key: this machine can neither read nor delete what it uploads."
    ),
)
@pass_config
def offsite_filestore(config):
    # Deliberately not going through _ensure_offsite(): the write-only path
    # needs no restic repository and no passphrase, so it must also work on a
    # machine that has nothing but a write-only target configured.
    if not _wo_configured(config):
        abort(
            "OFFSITE_WO_URL and OFFSITE_WO_RECIPIENT are not both set - no "
            "write-only target configured.\n"
            "OFFSITE_WO_RECIPIENT is an age PUBLIC key; generate a keypair "
            "with 'age-keygen', keep the private key in 1Password."
        )
    _state_dir(config)
    _offsite_run_raw(config, ["filestore"])


@offsite.command(
    name="db",
    help=(
        "Push base backups and WAL to the write-only target. Needs no "
        "repository key: this machine can neither read nor delete what it "
        "uploads."
    ),
)
@pass_config
def offsite_db(config):
    if not _wo_db_configured(config):
        abort(
            "OFFSITE_WO_URL and OFFSITE_WO_DB_RECIPIENT are not both set - no "
            "write-only database target configured.\n"
            "OFFSITE_WO_DB_RECIPIENT is an age PUBLIC key; generate a keypair "
            "with 'age-keygen' and keep the private key in 1Password."
        )
    _state_dir(config)
    _offsite_run_raw(config, ["db"])


@offsite.command(
    name="wal",
    help=(
        "Push newly archived WAL segments (runs every minute via "
        "CRONJOB_OFFSITE_WAL). Quiet no-op when there is nothing new or "
        "another run holds the lock."
    ),
)
@pass_config
def offsite_wal(config):
    # Deliberately silent rather than aborting when unconfigured: this runs
    # 1440 times a day on every project, and a project without a write-only
    # database target must not produce a cron failure every minute.
    if not _wo_db_configured(config):
        return
    _state_dir(config)
    _offsite_run_raw(config, ["wal"], name_suffix="offsite_wal")


@offsite.command(
    name="reset",
    help=(
        "Forget what has already been uploaded, so the next run offers "
        "everything again. Deletes nothing on the receiver."
    ),
)
@click.argument(
    "what",
    type=click.Choice(["all", "filestore", "db"]),
    default="all",
    required=False,
)
@pass_config
def offsite_reset(config, what):
    # The ledger is only a memory of what was sent, never the backup itself, so
    # losing or discarding it is recoverable: the next run asks the receiver
    # which objects it already has (HEAD) and only sends what is missing. What
    # this command does NOT do is delete anything on the receiver - this machine
    # cannot, and should not be able to.
    _state_dir(config)
    _offsite_run_raw(config, ["reset", what], name_suffix="offsite_reset")


@offsite.command(
    name="init",
    help="Create the repository (the first backup does this anyway).",
)
@pass_config
def offsite_init(config):
    _offsite_run(config, ["init"])


@offsite.command(
    name="list", help="List the archives in the offsite repository."
)
@pass_config
def offsite_list(config):
    _offsite_run(config, ["list"])


@offsite.command(name="info", help="Repository stats (size, deduplication).")
@pass_config
def offsite_info(config):
    _offsite_run(config, ["info"])


@offsite.command(
    name="check",
    help="Verify integrity by re-reading the data (slow, costs traffic).",
)
@pass_config
def offsite_check(config):
    _offsite_run(config, ["check"])


@offsite.command(
    name="prune",
    help=(
        "Apply the retention rules now. Against append-only targets (our "
        "backup server) that is only possible there, not from here."
    ),
)
@pass_config
def offsite_prune(config):
    _offsite_run(config, ["prune"])


@offsite.command(
    name="restic",
    help="Run an arbitrary restic command against the repository (escape hatch).",
    context_settings=dict(ignore_unknown_options=True),
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@pass_config
def offsite_restic(config, args):
    _offsite_run(config, ["restic"] + list(args))


# --------------------------------------------------------------------------- #
# Enrollment against the backup server
# --------------------------------------------------------------------------- #
def _enroll_dir(config):
    """The directory that is mounted read-only into the container."""
    d = Path(config.HOST_RUN_DIR) / "offsite"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _area_name(config, name):
    """Derive the area name from the project name.

    The server allows a-z, 0-9, _ and -, starting with a letter. So a project
    name like "ZO-05123_Kunde" is lower-cased and cleaned up here rather than
    bouncing off the server with an error.
    """
    import re

    raw = (name or config.project_name or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9_-]", "-", raw).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if cleaned and not cleaned[0].isalpha():
        cleaned = "p" + cleaned
    if not re.match(r"^[a-z][a-z0-9_-]{1,40}$", cleaned or ""):
        abort(
            f"No valid area name can be formed from '{raw}'. "
            "Pass one with --name (a-z, 0-9, _ and -, starting with a letter)."
        )
    return cleaned


def _enroll_ssl_context(cert_file):
    """TLS context for the enrollment service.

    The backup server uses a self-issued certificate. If it is already here, it
    is verified against. On FIRST contact there is nothing to verify against -
    the certificate is then fetched, pinned, and its fingerprint printed so it
    can be held against the server once. After that, any change is noticed. The
    same procedure as ssh's accept-new.
    """
    import ssl

    if cert_file.exists():
        ctx = ssl.create_default_context(cafile=str(cert_file))
        # The certificate is issued for the name "restic-backup" and carries
        # the IP addresses as SANs; so this verifies against exactly it.
        return ctx
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _enroll_call(config, method, path, payload=None):
    import json as _json
    import urllib.error
    import urllib.request

    base = (getattr(config, "OFFSITE_ENROLL_URL", "") or "").rstrip("/")
    if not base:
        abort(
            "OFFSITE_ENROLL_URL is empty - the backup server's enrollment "
            "service is not configured."
        )
    cert = _enroll_dir(config) / "rest-server.crt"
    data = _json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(
            req, timeout=30, context=_enroll_ssl_context(cert)
        ) as resp:
            return _json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        abort(f"Enrollment service answered {exc.code}: {body[:300]}")
    except urllib.error.URLError as exc:
        abort(
            f"Enrollment service {base} is unreachable: {exc.reason}.\n"
            "The service is only reachable over the zebroo VPN - is this "
            "machine in a VPN group together with the backup server?"
        )


@offsite.command(
    name="register",
    help=(
        "Request a customer area on the backup server and pick up the "
        "credentials. The first call files a request for an admin to approve; "
        "the same call then collects everything needed."
    ),
)
@click.option(
    "--name",
    default=None,
    help="Area name (default: derived from the project name).",
)
@click.option("--note", default="", help="Note for the admin.")
@pass_config
def offsite_register(config, name, note):
    import json as _json
    import socket
    import ssl
    import urllib.request

    from .tools import update_setting

    area = _area_name(config, name)
    edir = _enroll_dir(config)
    cert = edir / "rest-server.crt"
    state_file = edir / "enroll.json"

    # The server certificate comes first: without it restic cannot verify the
    # server, and the fingerprint deserves a look on first contact.
    if not cert.exists():
        base = (config.OFFSITE_ENROLL_URL or "").rstrip("/")
        req = urllib.request.Request(base + "/api/ca")
        with urllib.request.urlopen(
            req, timeout=30, context=_enroll_ssl_context(cert)
        ) as resp:
            pem = resp.read()
        cert.write_bytes(pem)
        cert.chmod(0o644)
        import hashlib

        der = ssl.PEM_cert_to_DER_cert(pem.decode())
        fp = hashlib.sha256(der).hexdigest()
        fp = ":".join(fp[i : i + 2] for i in range(0, len(fp), 2)).upper()
        click.secho(
            "Server certificate accepted and pinned on first contact.\n"
            f"  SHA256 {fp}\n"
            "Hold it against the backup server once; any later change aborts "
            "the connection.",
            fg="yellow",
        )

    state = {}
    if state_file.exists():
        state = _json.loads(state_file.read_text())

    # If the machine already brings its own passphrase (the shop and zCICD
    # store one per project in the backend), the server must not invent a second
    # key - otherwise there are two truths for the same repository.
    own_key = bool((config.OFFSITE_PASSPHRASE or "").strip())

    if state.get("area") != area or not state.get("request_id"):
        answer = _enroll_call(
            config,
            "POST",
            "/api/request",
            {
                "area": area,
                "hostname": socket.gethostname(),
                "project": config.project_name,
                "note": note,
                "own_repo_key": own_key,
            },
        )
        state = {
            "area": area,
            "request_id": answer["request_id"],
            "token": answer.get("pickup_token", state.get("token", "")),
        }
        state_file.write_text(_json.dumps(state, indent=2))
        state_file.chmod(0o600)
        click.secho(
            f"Area '{area}' requested (request {state['request_id']}).\n"
            f"{answer.get('note', '')}\n"
            "Run the same command again once it has been approved.",
            fg="green",
        )
        return

    answer = _enroll_call(
        config,
        "GET",
        f"/api/status?request_id={state['request_id']}&token={state['token']}",
    )
    status = answer.get("status")
    if status == "pending":
        click.secho(
            f"Request {state['request_id']} for '{area}' is still awaiting approval."
            + (f"\n{answer['note']}" if answer.get("note") else ""),
            fg="yellow",
        )
        return
    if status == "rejected":
        state_file.unlink(missing_ok=True)
        abort(f"The request for '{area}' was rejected.")
    if status == "delivered":
        abort(
            "The credentials have already been picked up - the server hands "
            "them out exactly once. They are in 1Password; copy them from "
            "there into the settings (OFFSITE_REPO, OFFSITE_REST_USER, "
            "OFFSITE_REST_PASSWORD, OFFSITE_PASSPHRASE)."
        )
    if status != "approved":
        abort(f"Unexpected answer from the enrollment service: {answer}")

    if answer.get("ca_cert"):
        cert.write_text(answer["ca_cert"])
        cert.chmod(0o644)

    update_setting(config, "OFFSITE_REST_USER", answer["user"])
    update_setting(config, "OFFSITE_REST_PASSWORD", answer["password"])
    # The write-only target and the two PUBLIC age keys. Public means they may
    # travel and may sit in a settings file: they encrypt, they decrypt nothing.
    if answer.get("wo_url"):
        update_setting(config, "OFFSITE_WO_URL", answer["wo_url"])
    if answer.get("wo_recipient"):
        update_setting(config, "OFFSITE_WO_RECIPIENT", answer["wo_recipient"])
    if answer.get("wo_db_recipient"):
        update_setting(
            config, "OFFSITE_WO_DB_RECIPIENT", answer["wo_db_recipient"]
        )
    # A server that still hands out a repository key is the old, restic-based
    # arrangement - then keep taking it, so an older backup server keeps working.
    if answer.get("repo_url"):
        update_setting(config, "OFFSITE_REPO", answer["repo_url"])
    if answer.get("repo_key"):
        update_setting(config, "OFFSITE_PASSPHRASE", answer["repo_key"])
    update_setting(config, "RUN_OFFSITE", "1")
    # The request is done; its state is no longer needed and should not linger
    # as an apparently open request.
    state_file.unlink(missing_ok=True)

    click.secho(
        f"Area '{area}' is set up and stored in the settings.",
        fg="green",
    )
    if answer.get("wo_recipient") and answer.get("wo_db_recipient"):
        click.secho(
            "Write-only: this machine holds no key that could read the backup. "
            "It encrypts to public keys and can neither read nor delete what it "
            "uploaded.",
            fg="green",
        )
    elif answer.get("repo_key"):
        click.secho(
            "This backup server still issues repository keys (the restic "
            "arrangement). The key is in 1Password - without it the backup is "
            "worthless, and this machine can read its own history.",
            fg="yellow",
        )
    click.secho(
        "Next steps:\n"
        "  odoo reload && odoo build offsite\n"
        "  odoo offsite backup      # first run",
        fg="green",
    )
