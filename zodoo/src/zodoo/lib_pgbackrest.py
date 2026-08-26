import json
import re
import subprocess
import sys
import time
import arrow
import inquirer
import click

from .cli import cli, pass_config, Commands
from .lib_clickhelpers import AliasedGroup
from .tools import abort
from .tools import __dc
from .tools import __dcexec
from .tools import __get_cmd


def _stanza(config):
    """The stanza name = one postgres cluster in the repository.

    Defaults to the project name rather than a fixed "odoo": on a shared repo
    host every instance's backups live under the stanza name, so a constant
    would make two projects write into each other's history.

    The default in default.settings is the literal string "$PROJECT_NAME".
    Settings values are not expanded recursively - only the compose files get
    variable substitution - so it arrives here unexpanded and has to be
    resolved rather than used as a stanza called "$PROJECT_NAME".
    """
    raw = (getattr(config, "pgbr_stanza", None) or config.project_name).strip()
    for placeholder in ("${PROJECT_NAME}", "$PROJECT_NAME"):
        raw = raw.replace(placeholder, config.project_name)
    return raw.strip()


@cli.group(
    cls=AliasedGroup,
    help="pgBackRest base backups, WAL archive and point-in-time recovery.",
)
@pass_config
def pgbackrest(config):
    pass


def _ensure_pgbackrest(config):
    if not config.run_pgbackrest:
        abort(
            "pgBackRest is not enabled. Set RUN_PGBACKREST=1 (and on DEVMODE "
            "machines PGBR_FORCE_IN_DEVMODE=1), then "
            "`odoo reload && odoo up -d`."
        )


def _pgbr(config, args, interactive=False):
    """Run pgbackrest inside the running sidecar.

    Non-interactive by default: pgbackrest never prompts, and the scheduled
    backups run from the TTY-less cronjobs daemon where an interactive exec
    fails with "the input device is not a TTY".

    gosu because pgbackrest refuses to run as root, and the container's
    pgbackrest user shares uid 999 with postgres so it can read PGDATA.
    """
    _ensure_pgbackrest(config)
    return __dcexec(
        config,
        [
            "pgbackrest",
            "gosu",
            "pgbackrest",
            "pgbackrest",
            "--stanza",
            _stanza(config),
        ]
        + args,
        interactive=interactive,
    )


def _pgbr_oneoff(config, args):
    """Run pgbackrest in a throwaway container, without starting postgres.

    Needed for restore: the database has to be down while its data directory is
    rewritten, but the sidecar `depends_on: postgres` and its entrypoint waits
    for the socket - so with postgres stopped there is nothing to exec into.
    `--no-deps` plus an overridden entrypoint gives a container that has the
    volumes and nothing else.
    """
    return __dc(
        config,
        [
            "run",
            "-T",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "/usr/sbin/gosu",
            "pgbackrest",
            "pgbackrest",
            "pgbackrest",
            "--stanza",
            _stanza(config),
        ]
        + args,
    )


def _pgbr_capture(config, args):
    """Run pgbackrest in the sidecar and return stdout."""
    cmd = (
        __get_cmd(config)
        + [
            "exec",
            "-T",
            "pgbackrest",
            "gosu",
            "pgbackrest",
            "pgbackrest",
            "--stanza",
            _stanza(config),
        ]
        + args
    )
    return subprocess.check_output(cmd, encoding="utf-8")


# --------------------------------------------------------------------------- #
# backup                                                                       #
# --------------------------------------------------------------------------- #


@pgbackrest.command(
    name="backup",
    help=(
        "Take a backup now. --type full is a complete copy, diff holds "
        "everything changed since the last full, incr everything since the "
        "last backup of any type. The scheduled jobs run the same command."
    ),
)
@click.option(
    "--type",
    "backup_type",
    type=click.Choice(["full", "diff", "incr"]),
    default="incr",
    help="Backup type (default: incr).",
)
@pass_config
def pgbackrest_backup(config, backup_type):
    # Wired into the shared cronjobs daemon, so this runs on EVERY project.
    # On projects without pgbackrest it has to be a quiet no-op rather than an
    # abort, otherwise every other project logs a cron error every night.
    if not config.run_pgbackrest:
        click.secho(
            "pgBackRest is not enabled (RUN_PGBACKREST=0); skipping backup.",
            fg="yellow",
        )
        return
    # expire runs as part of backup, so retention is applied on every run and
    # cannot be forgotten - which is exactly how the dump directory grew to
    # 3.4 TB with a cleanup job that was defined but never scheduled.
    _pgbr(config, ["--type", backup_type, "backup"])


@pgbackrest.command(
    name="info",
    help="Show the repository: stanzas, backups, sizes and the WAL range.",
)
@pass_config
def pgbackrest_info(config):
    _pgbr(config, ["info"])


@pgbackrest.command(
    name="check",
    help=(
        "Verify the whole path: the repository is reachable, the "
        "archive_command works, and a freshly switched WAL segment really "
        "arrives. This is the command that tells you whether the backups are "
        "worth anything."
    ),
)
@pass_config
def pgbackrest_check(config):
    _check_versions_match(config)
    _pgbr(config, ["check"])


def _binary_version(config, service):
    """`pgbackrest version` as seen from one of our two containers.

    Not via _pgbr_capture: that one always targets the sidecar and adds a
    --stanza, and the point here is to ask each container separately.
    """
    cmd = __get_cmd(config) + [
        "exec",
        "-T",
        service,
        "pgbackrest",
        "version",
    ]
    try:
        raw = subprocess.check_output(
            cmd, encoding="utf-8", stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    m = re.search(r"pgBackRest\s+([0-9][0-9.]*)", raw)
    return m.group(1) if m else None


def _check_versions_match(config):
    """The sidecar and postgres must carry the SAME pgbackrest.

    pgbackrest speaks a versioned protocol and refuses to talk across a
    mismatch - archiving and backups stop with

        [ProtocolError] expected value '2.59' for greeting key 'version'
                        but got '2.50'

    The two binaries are installed into two different images from two
    different base distributions, so they can drift apart the moment one is
    rebuilt and the other is not. Saying it here, in the command whose whole
    job is "are the backups worth anything", beats discovering it at 2 a.m.

    Only a warning: a mismatch between OUR two containers is usually harmless
    for a local repository, and pgbackrest itself refuses clearly where it is
    not. What this catches is the silent half - the rebuild nobody redid.
    """
    sidecar = _binary_version(config, "pgbackrest")
    pg = _binary_version(config, "postgres")
    if sidecar and pg and sidecar != pg:
        click.secho(
            f"pgbackrest versions differ: sidecar {sidecar}, postgres {pg}.\n"
            "  -> `odoo reload && odoo build postgres pgbackrest`.\n"
            "Both images pin PGBR_VERSION; one of them was not rebuilt after "
            "it changed.",
            fg="red",
        )
    elif sidecar:
        click.secho(f"pgbackrest {sidecar} (sidecar and postgres agree)")


@pgbackrest.command(
    name="expire",
    help=(
        "Apply the retention policy now. Normally unnecessary - every backup "
        "expires as its final step - but useful right after changing the "
        "retention settings."
    ),
)
@pass_config
def pgbackrest_expire(config):
    _pgbr(config, ["expire"])


@pgbackrest.command(
    name="stanza-create",
    help="Create the stanza in the repository (the entrypoint does this too).",
)
@pass_config
def pgbackrest_stanza_create(config):
    _pgbr(config, ["stanza-create"])


@pgbackrest.command(
    name="stanza-upgrade",
    help="Tell the repository about a new postgres major version.",
)
@pass_config
def pgbackrest_stanza_upgrade(config):
    _pgbr(config, ["stanza-upgrade"])


@pgbackrest.command(
    name="switch-wal",
    help="Force a WAL switch so the archiving path is exercised end to end.",
)
@pass_config
def pgbackrest_switch_wal(config):
    from .tools import _execute_sql

    _ensure_pgbackrest(config)
    _execute_sql(
        config.get_odoo_conn().clone(dbname="postgres"),
        "SELECT pg_switch_wal()",
    )
    # check waits for the segment to actually land in the repository, so this
    # proves the path rather than just asking postgres to rotate a file.
    _pgbr(config, ["check"])


# --------------------------------------------------------------------------- #
# restore                                                                      #
# --------------------------------------------------------------------------- #


@pgbackrest.command(
    name="restore",
    help=(
        "Restore postgres from the repository. Without a target this restores "
        "the chosen backup; with --target-time or --target-name it replays WAL "
        "up to that point and promotes. DESTRUCTIVE: overwrites the postgres "
        "data directory."
    ),
)
@click.argument("backup_label", required=False, default=None)
@click.option(
    "--target-time",
    "target_time",
    default=None,
    help='Point-in-time target, e.g. "2026-05-31 14:25:00".',
)
@click.option(
    "--target-name",
    "target_name",
    default=None,
    help="Named restore point (SELECT pg_create_restore_point('name')).",
)
@click.option(
    "--keep-previous",
    is_flag=True,
    default=False,
    help=(
        "Move the current data directory aside instead of overwriting it, so "
        "the pre-restore state can be rolled back to. Costs a second full copy "
        "of the database on disk."
    ),
)
@click.option(
    "--no-delta",
    is_flag=True,
    default=False,
    help=(
        "Restore every file instead of only those that differ. Slower, but the "
        "right choice when the existing data directory is suspected corrupt."
    ),
)
@pass_config
@click.pass_context
def pgbackrest_restore(
    ctx,
    config,
    backup_label,
    target_time,
    target_name,
    keep_previous,
    no_delta,
):
    _ensure_pgbackrest(config)
    if not config.run_postgres:
        abort("Restore requires a zodoo-managed postgres (RUN_POSTGRES=1).")
    if target_time and target_name:
        abort("Use either --target-time or --target-name, not both.")

    if (
        not backup_label
        and not target_time
        and not target_name
        and sys.stdin.isatty()
    ):
        backup_label, target_time, target_name = _interactive_select_target(
            config
        )

    if target_time:
        target_time = _parse_target_time(target_time)

    _perform_restore(
        ctx,
        config,
        backup_label,
        target_time,
        target_name,
        keep_previous,
        no_delta,
    )


def _perform_restore(
    ctx,
    config,
    backup_label,
    target_time,
    target_name,
    keep_previous=False,
    no_delta=False,
):
    target = target_time or target_name
    what = f"backup '{backup_label}'" if backup_label else "the latest backup"
    if target:
        what += f" with point-in-time recovery to '{target}'"

    if not config.force:
        click.secho(
            f"This will STOP postgres and OVERWRITE its data directory with "
            f"{what}.",
            fg="red",
        )
        if not keep_previous:
            # Worth saying out loud, because it differs from what the barman
            # path did: that one staged the recovery elsewhere and kept the old
            # data directory as a rollback. pgbackrest restores in place, which
            # is what makes --delta fast, but it means there is no way back.
            click.secho(
                "There will be NO rollback copy - the current data directory "
                "is overwritten in place. Use --keep-previous to preserve it "
                "(needs a second full copy of the database on disk).",
                fg="red",
            )
        click.confirm("Continue?", abort=True)

    data_mount = "/var/lib/postgresql/data"
    pgdata = f"{data_mount}/pgdata"

    # Postgres has to be down: pgbackrest refuses to restore over a running
    # cluster, and rightly so.
    Commands.invoke(ctx, "down")

    if keep_previous:
        prev = f"{data_mount}/pgdata.prev"
        click.secho(
            f"Preserving the current data directory as {prev} ...", fg="yellow"
        )
        try:
            __dc(
                config,
                [
                    "run",
                    "-T",
                    "--rm",
                    "--no-deps",
                    "--entrypoint",
                    "/bin/bash",
                    "postgres",
                    "-c",
                    f"set -e\nrm -Rf '{prev}'\n"
                    f"if [ -e '{pgdata}' ]; then cp -a '{pgdata}' '{prev}'; fi\n",
                ],
            )
        except subprocess.CalledProcessError:
            abort(
                "Could not preserve the current data directory. Nothing was "
                "restored - the database is unchanged."
            )

    # A stale postmaster.pid makes pgbackrest refuse the restore:
    #
    #   ERROR: [038]: unable to restore while PostgreSQL is running
    #   HINT: presence of 'postmaster.pid' ... indicates PostgreSQL is running
    #
    # and it is left behind routinely, not exceptionally: docker stops the
    # container with SIGTERM, which postgres reads as a SMART shutdown - wait
    # for every client to disconnect. That outlives compose's stop timeout,
    # the container is killed, and the pid file survives.
    #
    # Safe to remove here because the cluster is provably down: the containers
    # were just removed, and this runs in a throwaway container of its own.
    try:
        __dc(
            config,
            [
                "run",
                "-T",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/bin/bash",
                "postgres",
                "-c",
                f"if [ -f '{pgdata}/postmaster.pid' ]; then\n"
                f"  echo 'Removing a stale postmaster.pid (postgres is down).'\n"
                f"  rm -f '{pgdata}/postmaster.pid'\n"
                f"fi\n",
            ],
        )
    except subprocess.CalledProcessError:
        # Not fatal on its own - if the file really is a problem the restore
        # below says so, with pgbackrest's own wording.
        pass

    args = ["restore"]
    if not no_delta:
        # Only fetch files whose checksum differs from what is already there.
        # On a machine that still has its data directory this turns a restore
        # from "copy the whole database" into "copy what changed" - often
        # seconds instead of minutes.
        args.append("--delta")
    if backup_label:
        args += ["--set", backup_label]
    if target_time:
        args += ["--type", "time", "--target", target_time]
    elif target_name:
        args += ["--type", "name", "--target", target_name]
    if target:
        # Without this postgres would stop at the target and sit there in
        # perpetual read-only recovery (recovery_target_action defaults to
        # 'pause') - which looks like a hung restore.
        args += ["--target-action", "promote"]

    click.secho("Running pgbackrest restore ...", fg="yellow")
    try:
        _pgbr_oneoff(config, args)
    except subprocess.CalledProcessError as ex:
        abort(
            f"pgbackrest restore failed ({ex}). Check "
            "`odoo pgbackrest info` and the log in "
            "$HOST_RUN_DIR/pgbackrest.logs."
        )

    # pgbackrest writes recovery.signal and the restore_command into
    # postgresql.auto.conf itself, so unlike the barman path there is nothing
    # to rewrite here - postgres boots straight into archive recovery and
    # fetches the WAL it needs from the repository.
    click.secho(
        "Starting postgres; it replays WAL from the archive"
        + (" and promotes at the target." if target else "."),
        fg="yellow",
    )
    Commands.invoke(
        ctx, "up", daemon=True, machines=["postgres"], allow_build=True
    )
    if _wait_until_promoted(config):
        click.secho(
            "Postgres finished recovery. Bringing the rest of the stack up.",
            fg="green",
        )
    else:
        click.secho(
            "Postgres is still in recovery after the timeout; bringing the "
            "stack up anyway - check `odoo logs postgres`.",
            fg="red",
        )
    Commands.invoke(ctx, "up", daemon=True, allow_build=True)

    click.secho(
        "Restore done. The timeline changed, so take a fresh full backup:\n"
        "  odoo pgbackrest backup --type full",
        fg="green",
    )


def _wait_until_promoted(config, timeout=600):
    """Poll until postgres has left recovery.

    The timeout is generous on purpose: replay is single-threaded, and a target
    far from the base backup can take considerably longer than the restore
    itself did.
    """
    from .tools import _execute_sql

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            row = _execute_sql(
                config.get_odoo_conn().clone(dbname="postgres"),
                "SELECT pg_is_in_recovery()",
                fetchone=True,
            )
            if row is not None and not row[0]:
                return True
        except Exception:  # noqa: BLE001 - postgres may be mid-restart
            pass
        time.sleep(3)
    return False


# --------------------------------------------------------------------------- #
# target selection                                                             #
# --------------------------------------------------------------------------- #


def _list_backups(config):
    """Return [(label, backup_label, stop_time)] newest first.

    Read from `info --output=json` rather than by scraping the text output:
    the JSON carries the backup type and the timestamps as numbers, so the
    picker can show what a backup actually is instead of a parsed line.
    """
    rows = []
    try:
        out = _pgbr_capture(config, ["--output", "json", "info"])
    except subprocess.CalledProcessError:
        return rows
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return rows
    for stanza in data:
        for backup in stanza.get("backup", []):
            label = backup.get("label")
            if not label:
                continue
            btype = backup.get("type", "?")
            stop = backup.get("timestamp", {}).get("stop")
            when = (
                arrow.get(stop).to("local").format("YYYY-MM-DD HH:mm:ss")
                if stop
                else "?"
            )
            size = backup.get("info", {}).get("repository", {}).get("delta")
            size_txt = (
                f", {size / 1024 / 1024:.0f} MiB in repo" if size else ""
            )
            rows.append(
                (f"{when}  {btype:<4}  {label}{size_txt}", label, stop)
            )
    rows.sort(key=lambda r: r[2] or 0, reverse=True)
    return rows


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_target_time(raw):
    """Parse a user-entered timestamp into what pgbackrest expects.

    Deliberately NOT a list of arrow formats tried in order. arrow matches a
    PREFIX, so "2026-08-25 18:57:24.353049+00" falls through every format with
    a time in it and is then happily matched by "YYYY-MM-DD" - yielding
    midnight, silently, and recovering the database to the wrong point. For a
    backup tool that is the worst possible failure: it succeeds.

    dateutil parses the whole string or raises, which is the property needed
    here. A date without a time is accepted as midnight because somebody who
    types a bare date means that; a timestamp is never truncated to it.
    """
    from dateutil import parser as _dateparser

    raw = (raw or "").strip()
    if not raw:
        abort("No timestamp given. Use e.g. 2026-05-31 14:25:00.")
    try:
        parsed = _dateparser.parse(raw)
    except (ValueError, OverflowError):
        abort(f"Invalid timestamp '{raw}'. Use e.g. 2026-05-31 14:25:00.")

    dt = arrow.get(parsed)
    if parsed.tzinfo is None:
        # A bare timestamp means local time - the same clock the operator read
        # the incident off.
        dt = arrow.get(parsed, tzinfo="local")

    if _DATE_ONLY.match(raw):
        click.secho(
            f"Recovering to {dt.format('YYYY-MM-DD HH:mm:ssZZ')} "
            "(midnight - no time of day was given).",
            fg="yellow",
        )

    if dt > arrow.now():
        abort(f"Timestamp '{raw}' is in the future - nothing to recover to.")
    # pgbackrest hands the target to postgres' recovery_target_time, which
    # wants an offset to be unambiguous across a DST boundary.
    return dt.format("YYYY-MM-DD HH:mm:ssZZ")


def _parse_age(raw):
    """Turn an age like '30m' / '2h' / '1d' into an absolute target."""
    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", (raw or "").lower())
    if not m:
        abort(f"Invalid age '{raw}'. Use e.g. 30m, 2h, 90s, 1d.")
    n, unit = int(m.group(1)), m.group(2)
    units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    dt = arrow.now().shift(**{units[unit]: -n})
    click.secho(
        f"Age {n}{unit} -> recovery target {dt.format('YYYY-MM-DD HH:mm:ss')}",
        fg="cyan",
    )
    return dt.format("YYYY-MM-DD HH:mm:ssZZ")


def _interactive_select_target(config):
    """Interactive picker. Returns (backup_label, target_time, target_name)."""
    choices = [
        (f"Backup  {label}", ("backup", bid))
        for label, bid, _ in _list_backups(config)
    ]
    choices += [
        ("Point-in-Time: enter an absolute timestamp", ("time", None)),
        ("Age: enter how far back (e.g. 30m, 2h, 1d)", ("age", None)),
        ("Named restore point: enter a name", ("name", None)),
        ("Abort", ("abort", None)),
    ]
    answer = inquirer.prompt(
        [
            inquirer.List(
                "sel", "Restore the database to which point?", choices=choices
            )
        ]
    )
    if not answer:
        abort("Aborted.")
    kind, value = answer["sel"]
    if kind == "abort":
        abort("Aborted.")
    if kind == "backup":
        return value, None, None
    if kind == "time":
        return (
            None,
            _parse_target_time(
                click.prompt("Target timestamp (YYYY-MM-DD HH:MM:SS)")
            ),
            None,
        )
    if kind == "age":
        return (
            None,
            _parse_age(click.prompt("How far back? (e.g. 30m, 2h, 90s, 1d)")),
            None,
        )
    if kind == "name":
        raw = click.prompt("Restore point name").strip()
        if not raw:
            abort("Empty restore point name.")
        return None, None, raw
    abort("Aborted.")


Commands.register(pgbackrest_backup)
Commands.register(pgbackrest_restore)


# Top-level shortcut. A dedicated command rather than an alias of the subgroup
# command: re-registering keeps .name == "info", which breaks AliasedGroup's
# name-based tie-breaks and garbles its error messages.
@cli.command(
    name="pgbackrest-info",
    help="Show the pgBackRest repository (backups, sizes, WAL range).",
)
@pass_config
def pgbackrest_info_toplevel(config):
    _pgbr(config, ["info"])


# --------------------------------------------------------------------------- #
# Update guard: named restore point before `odoo update`, rollback on failure. #
# Called from lib_module.update().                                             #
# --------------------------------------------------------------------------- #


def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def guard_update_enabled(config):
    """True when both pgbackrest and the update-guard setting are on."""
    return _truthy(getattr(config, "run_pgbackrest", "0")) and _truthy(
        getattr(config, "pgbr_guard_update", "0")
    )


def create_update_safepoint(config):
    """Create a named restore point and make sure its WAL reaches the archive.

    Returns the marker name, or None if that could not be arranged - in which
    case the update goes ahead without a safety net rather than being blocked.
    """
    from .tools import _execute_sql

    marker = "pre_update_" + arrow.now().format("YYYYMMDDHHmmss")
    try:
        conn = config.get_odoo_conn()
        _execute_sql(conn, f"SELECT pg_create_restore_point('{marker}')")
        # The marker lives in a WAL record, so the segment holding it has to be
        # completed and archived before it can be recovered to. Unlike the
        # barman path this needs no sleep: `check` returns once the segment has
        # actually arrived in the repository.
        _execute_sql(conn.clone(dbname="postgres"), "SELECT pg_switch_wal()")
        _pgbr(config, ["check"], interactive=False)
    except Exception as ex:  # noqa: BLE001
        click.secho(
            f"Could not create a pgbackrest safepoint ({ex}); continuing "
            "without one.",
            fg="yellow",
        )
        return None
    return marker


def offer_safepoint_rollback(ctx, config, marker, non_interactive):
    """On update failure, offer to roll back to the pre-update safepoint."""
    click.secho(
        f"\nUpdate failed. A pre-update restore point exists: '{marker}'.",
        fg="red",
    )
    manual = f"odoo pgbackrest restore --target-name {marker}"
    if non_interactive or not sys.stdin.isatty():
        click.secho(
            "Non-interactive run - not rewinding automatically. To roll the "
            f"database back later run:\n  {manual}",
            fg="yellow",
        )
        return
    if not click.confirm(
        f"Rewind the database to the pre-update state ('{marker}') now?",
        default=False,
    ):
        click.secho(f"Skipped. Roll back later with:\n  {manual}", fg="yellow")
        return
    config.force = True
    _perform_restore(ctx, config, None, None, marker)


# --------------------------------------------------------------------------- #
# Enrolment
#
# Getting a machine onto the backup server by hand means moving three files and
# a passphrase, and the passphrase is the one value that cannot be replaced
# later. Doing that over chat or copy-paste is exactly where it goes wrong.
#
# The flow mirrors `odoo offsite register`, which has been carrying the restic
# side for a while: the first call files a request, an admin approves it in the
# service's own screen, and the same call then collects everything. The
# credentials are handed out exactly once - a second call gets nothing.
# --------------------------------------------------------------------------- #
def _enroll_dir(config):
    """Where the client certificate lives - mounted into the sidecar."""
    from pathlib import Path

    d = Path(config.HOST_RUN_DIR) / "pgbackrest" / "cert"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _enroll_ssl_context(ca_file):
    """TLS context for the enrolment service.

    The backup server issues its own certificate. Once the CA is here it is
    verified against. On FIRST contact there is nothing to verify against - it
    is then fetched, pinned and its fingerprint printed, so it can be held
    against the server once. The same bargain ssh makes with accept-new.
    """
    import ssl

    if ca_file.exists():
        return ssl.create_default_context(cafile=str(ca_file))
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _enroll_call(config, method, path, payload=None):
    import json as _json
    import urllib.error
    import urllib.request

    base = (getattr(config, "PGBR_ENROLL_URL", "") or "").strip().rstrip("/")
    if not base:
        abort(
            "PGBR_ENROLL_URL is empty - the backup server's enrolment service "
            "is not configured."
        )
    data = _json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(
            req,
            timeout=30,
            context=_enroll_ssl_context(_enroll_dir(config) / "ca.crt"),
        ) as resp:
            return _json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        abort(f"The enrolment service answered {exc.code}: {body[:300]}")
    except urllib.error.URLError as exc:
        abort(
            f"The enrolment service {base} is unreachable: {exc.reason}.\n"
            "It is only reachable over the zebroo VPN - is this machine in a "
            "VPN group together with the backup server?"
        )


@pgbackrest.command(
    name="register",
    help=(
        "Request a stanza on the backup server and collect the credentials. "
        "The first call files a request for an admin to approve; calling it "
        "again once approved writes certificate and passphrase into place."
    ),
)
@click.option(
    "--name",
    default=None,
    help="Stanza name (default: the project name).",
)
@click.option("--note", default="", help="Note for the admin.")
@pass_config
def pgbackrest_register(config, name, note):
    import json as _json
    import socket
    import ssl
    import urllib.request

    from .tools import update_setting

    stanza = (name or _stanza(config)).strip().lower()
    if not re.match(r"^[a-z][a-z0-9_-]{1,40}$", stanza):
        abort(
            f"'{stanza}' is not a usable stanza name. Allowed: a-z, 0-9, _ and "
            "-, starting with a letter, 2-41 characters. Pass one with --name."
        )
    cdir = _enroll_dir(config)
    ca_file = cdir / "ca.crt"
    state_file = cdir / "enroll.json"

    # The CA comes first: without it nothing that follows can be verified.
    if not ca_file.exists():
        base = (config.PGBR_ENROLL_URL or "").strip().rstrip("/")
        with urllib.request.urlopen(
            urllib.request.Request(base + "/api/ca"),
            timeout=30,
            context=_enroll_ssl_context(ca_file),
        ) as resp:
            pem = resp.read()
        ca_file.write_bytes(pem)
        ca_file.chmod(0o644)
        import hashlib

        fp = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem.decode())).hexdigest()
        fp = ":".join(fp[i : i + 2] for i in range(0, len(fp), 2)).upper()
        click.secho(
            "Certificate authority accepted and pinned on first contact.\n"
            f"  SHA256 {fp}\n"
            "Hold it against the backup server once; any later change aborts "
            "the connection.",
            fg="yellow",
        )

    state = _json.loads(state_file.read_text()) if state_file.exists() else {}

    if state.get("stanza") != stanza or not state.get("request_id"):
        answer = _enroll_call(
            config,
            "POST",
            "/api/request",
            {
                "area": stanza,
                "hostname": socket.gethostname(),
                "project": config.project_name,
                "note": note,
            },
        )
        state = {
            "stanza": stanza,
            "request_id": answer["request_id"],
            "token": answer.get("pickup_token", state.get("token", "")),
        }
        state_file.write_text(_json.dumps(state, indent=2))
        state_file.chmod(0o600)
        click.secho(
            f"Stanza '{stanza}' requested (request {state['request_id']}).\n"
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
            f"Request {state['request_id']} for '{stanza}' is still awaiting "
            "approval." + (f"\n{answer['note']}" if answer.get("note") else ""),
            fg="yellow",
        )
        return
    if status == "rejected":
        state_file.unlink(missing_ok=True)
        abort(f"The request for '{stanza}' was rejected.")
    if status == "delivered":
        abort(
            "The credentials have already been collected - the server hands "
            "them out exactly once. The passphrase is in 1Password; copy it "
            "and the certificate from there into PGBR_CIPHER_PASS and "
            f"{cdir}."
        )
    if status != "approved":
        abort(f"Unexpected answer from the enrolment service: {answer}")

    if answer.get("ca_cert"):
        ca_file.write_text(answer["ca_cert"])
        ca_file.chmod(0o644)
    (cdir / "client.crt").write_text(answer["client_cert"])
    (cdir / "client.crt").chmod(0o644)
    (cdir / "client.key").write_text(answer["client_key"])
    # pgBackRest refuses a key that others can read, and it is right to.
    (cdir / "client.key").chmod(0o600)

    update_setting(config, "PGBR_STANZA", answer["stanza"])
    update_setting(config, "PGBR_REPO_HOST", answer["repo_host"])
    update_setting(config, "PGBR_REPO_HOST_PORT", str(answer["repo_port"]))
    update_setting(config, "PGBR_CIPHER_TYPE", answer["cipher_type"])
    update_setting(config, "PGBR_CIPHER_PASS", answer["cipher_pass"])
    # The repository is over there, so this machine backs up from itself into
    # it - it does not serve one.
    update_setting(config, "PGBR_BACKUP_FROM", "here")
    update_setting(config, "RUN_PGBACKREST", "1")
    # The request is finished; leaving its state behind would look like an
    # open request forever.
    state_file.unlink(missing_ok=True)

    click.secho(
        f"Stanza '{stanza}' is set up and written to the settings.\n"
        "The passphrase is now in the settings of this project AND in "
        "1Password - it cannot be recovered from the backup server, which "
        "only ever stores ciphertext.\n\n"
        "Next:  odoo reload && odoo up -d && odoo pgbackrest check",
        fg="green",
    )
