import re
import subprocess
import sys
import time
import arrow
import inquirer
import click
from pathlib import Path

from .cli import cli, pass_config, Commands
from .lib_clickhelpers import AliasedGroup
from .tools import abort
from .tools import __dc
from .tools import __dcexec
from .tools import __get_cmd

SERVER = "odoo"


@cli.group(
    cls=AliasedGroup, help="Barman streaming backups + point-in-time recovery."
)
@pass_config
def barman(config):
    pass


def _ensure_barman(config):
    if not config.run_barman:
        abort(
            "Barman is not enabled. Set RUN_BARMAN=1 (and on DEVMODE machines "
            "BARMAN_FORCE_IN_DEVMODE=1), then `odoo reload && odoo up -d`."
        )


def _barman_exec(config, args, interactive=False):
    """Run `barman <args>` inside the barman service container.

    Defaults to non-interactive (``docker compose exec -T``): barman never
    prompts, and the daily ``odoo barman backup`` runs from the TTY-less
    cronjobs daemon where an interactive exec would fail with
    "the input device is not a TTY".
    """
    _ensure_barman(config)
    return __dcexec(
        config, ["barman", "barman"] + args, interactive=interactive
    )


@barman.command(
    name="backup",
    help="Take a full base backup now (the daily cronjob runs the same command).",
)
@pass_config
def barman_backup(config):
    # This is wired into the shared cronjobs daemon (CRONJOB_BARMAN_BACKUP), so
    # it runs daily on EVERY project. On projects without barman it must be a
    # quiet no-op (exit 0) instead of aborting, otherwise every non-barman
    # project logs a cron error every night.
    if not config.run_barman:
        click.secho(
            "Barman is not enabled (RUN_BARMAN=0); skipping backup.",
            fg="yellow",
        )
        return
    _barman_exec(config, ["backup", SERVER])


@barman.command(
    name="list", help="List available base backups for the server."
)
@pass_config
def barman_list(config):
    _barman_exec(config, ["list-backup", SERVER])


@barman.command(
    name="status", help="Show server status (streaming, slot, last backup)."
)
@pass_config
def barman_status(config):
    _barman_exec(config, ["status", SERVER])


@barman.command(
    name="check",
    help="Run barman's self-checks (connection, replication slot, WAL streaming).",
)
@pass_config
def barman_check(config):
    _barman_exec(config, ["check", SERVER])


@barman.command(
    name="recover",
    help=(
        "Recover postgres from a Barman backup. Without a target this is a plain "
        "restore of the chosen backup; with --target-time or --target-name it "
        "performs a point-in-time-recovery, replaying WAL up to that point and "
        "then promoting. DESTRUCTIVE: overwrites the postgres data volume."
    ),
)
@click.argument("backup_id", required=False, default=None)
@click.option(
    "--target-time",
    "target_time",
    default=None,
    help='PITR target timestamp, e.g. "2026-05-31 14:25:00". Recovers to the latest backup before it and replays WAL up to that point.',
)
@click.option(
    "--target-name",
    "target_name",
    default=None,
    help="PITR target named restore point (created with SELECT pg_create_restore_point('name')).",
)
@pass_config
@click.pass_context
def barman_recover(ctx, config, backup_id, target_time, target_name):
    _ensure_barman(config)
    if not config.run_postgres:
        abort("Recovery requires a zodoo-managed postgres (RUN_POSTGRES=1).")
    if target_time and target_name:
        abort("Use either --target-time or --target-name, not both.")

    # Nothing chosen on the CLI + a real terminal -> show an interactive picker
    # (base backups + point-in-time / age / named restore point).
    if (
        not backup_id
        and not target_time
        and not target_name
        and sys.stdin.isatty()
    ):
        backup_id, target_time, target_name = _interactive_select_target(
            config
        )

    # Normalise + validate the timestamp (format / not-in-future) for both the
    # CLI (`--target-time "..."`, usually no tz offset) and picker paths, so the
    # backup auto-selection below and barman get a consistent tz-aware value.
    if target_time:
        target_time = _parse_target_time(target_time)

    # PITR replays WAL forward from a base backup, so the base must predate the
    # target. When no explicit backup was chosen, pick the newest backup at or
    # before the target time (else "latest" would fail for a target that lies
    # before the most recent backup). Named restore points have no known time,
    # so we fall back to "latest" (correct for fresh markers e.g. update guard).
    if target_time and not backup_id:
        backup_id = _pick_backup_for_time(config, target_time)
        if not backup_id:
            abort(
                f"No base backup found at or before {target_time}. "
                "Cannot point-in-time-recover that far back."
            )

    if not backup_id:
        backup_id = "latest"

    _perform_recover(ctx, config, backup_id, target_time, target_name)


def _perform_recover(ctx, config, backup_id, target_time, target_name):
    target = target_time or target_name
    what = f"backup '{backup_id}'"
    if target:
        what += f" with point-in-time-recovery to '{target}'"
    if not config.force:
        click.secho(
            f"This will STOP postgres and OVERWRITE its data volume with {what}.",
            fg="red",
        )
        click.confirm("Continue?", abort=True)

    # 1) Let barman build the recovered datadir into the shared dumps dir
    #    (mounted as /host/dumps in the barman container, $DUMPS_PATH on the host).
    #    This happens BEFORE anything destructive (the postgres volume is only
    #    touched in step 2), so a failure here aborts cleanly with the live DB
    #    intact instead of an ugly traceback.
    recover_target = "/host/dumps/barman_recover"
    args = ["recover"]
    if target_time:
        args += ["--target-time", target_time]
    if target_name:
        args += ["--target-name", target_name]
    args += [SERVER, backup_id, recover_target]
    click.secho(
        f"Running barman recover into {recover_target} ...", fg="yellow"
    )
    try:
        # barman drops to the unprivileged `barman` user for file operations,
        # but /host/dumps is a host bind-mount owned by the host user, so
        # barman's rsync mkdir would fail. Pre-create the destination owned by
        # barman.
        __dcexec(
            config,
            [
                "barman",
                "bash",
                "-c",
                f"rm -rf {recover_target} && mkdir -p {recover_target} "
                f"&& chown barman:barman {recover_target}",
            ],
            interactive=False,
        )
        _barman_exec(config, args)
    except subprocess.CalledProcessError as ex:
        abort(
            f"barman recover failed ({ex}). The postgres volume was NOT "
            "touched - the live database is unchanged."
        )

    host_recovered = Path(config.dumps_path) / "barman_recover"
    if not host_recovered.exists():
        abort(f"Recovered datadir not found at {host_recovered} on the host.")

    # 2) Stop everything and swap the recovered datadir into the postgres
    #    volume. The swap runs inside a one-off postgres container
    #    (`docker compose run`) instead of against the volume's host
    #    mountpoint: /var/lib/docker/volumes/... is only reachable on a
    #    Linux host with a local daemon — on Docker Desktop / Colima /
    #    remote daemons it lives inside the VM, so host-side writes fail
    #    (and the old sudo fallback can't prompt in non-interactive runs).
    Commands.invoke(ctx, "down")
    # Paths inside the postgres service container: compose mounts the
    # postgres volume at /var/lib/postgresql/data and $DUMPS_PATH at
    # /opt/dumps (postgres/docker-compose.yml).
    data_mount = "/var/lib/postgresql/data"
    pgdata = f"{data_mount}/pgdata"
    # Build the recovered datadir alongside the live one and swap it in with an
    # atomic rename, so the live volume is never left half-written if the
    # operation is interrupted (e.g. power loss mid-copy). The previous datadir
    # is kept as a rollback.
    pgdata_new = f"{data_mount}/pgdata.barman_new"
    pgdata_prev = f"{data_mount}/pgdata.prev"
    recovered = "/opt/dumps/barman_recover"
    click.secho(f"Swapping recovered datadir into {pgdata} ...", fg="yellow")

    # For a targeted recovery, promote once the target is reached - otherwise
    # postgres' default recovery_target_action='pause' would leave it read-only
    # in perpetual recovery instead of a usable read-write database.
    promote_line = ""
    if target:
        promote_line = (
            "printf \"\\nrecovery_target_action = 'promote'\\n\" "
            f">> '{pgdata_new}/postgresql.auto.conf'\n"
        )

    swap_script = (
        "set -e\n"
        # 1) assemble the new datadir in a sibling dir (live one untouched)
        f"rm -Rf '{pgdata_new}'\n"
        f"mkdir -p '{pgdata_new}'\n"
        # copy contents (barman writes recovery.signal / postgresql.auto.conf in there)
        f"cp -a '{recovered}/.' '{pgdata_new}/'\n"
        # recovery.signal is what tells postgres to enter archive recovery
        # (replay WAL to the target + honour recovery_target_*). Without it
        # postgres attempts a plain crash recovery against backup_label and
        # dies with "could not locate required checkpoint record". barman
        # should create it; ensure it exists so the recovered datadir always
        # boots into recovery.
        f"touch '{pgdata_new}/recovery.signal'\n"
        # barman's restore_command/recovery_end_command reference the
        # staging path (valid only in the barman container). Rewrite them to
        # the path postgres sees (PGDATA in postgres/docker-compose.yml) so
        # postgres can fetch the WAL that shipped inside the datadir as
        # barman_wal/.
        f"sed -i 's#{recover_target}#{pgdata}#g' "
        f"'{pgdata_new}/postgresql.auto.conf'\n"
        f"echo '--- postgresql.auto.conf (rewritten) ---'; "
        f"cat '{pgdata_new}/postgresql.auto.conf' 2>/dev/null || true\n"
        f"{promote_line}"
        # postgres runs as uid/gid 999 inside the container
        f"chown -R 999:999 '{pgdata_new}'\n"
        f"chmod 700 '{pgdata_new}'\n"
        # 2) atomic swap: keep the old datadir as a rollback, move the new
        #    one into place. The only non-atomic window is two renames (ms).
        f"rm -Rf '{pgdata_prev}'\n"
        f"if [ -e '{pgdata}' ]; then mv '{pgdata}' '{pgdata_prev}'; fi\n"
        f"mv '{pgdata_new}' '{pgdata}'\n"
        # 3) drop the staging copy (a full datadir) from the dumps dir
        f"rm -Rf '{recovered}'\n"
        f"echo 'Previous datadir preserved at {pgdata_prev} "
        f"(remove once the recovery is verified).'\n"
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
                swap_script,
            ],
        )
    except subprocess.CalledProcessError:
        abort("Failed to write recovered datadir into the postgres volume.")

    # 3) Start postgres alone first so it can replay WAL + promote. Bringing the
    #    whole stack up immediately would let odoo connect while postgres is
    #    still in (read-only) recovery. Wait for the promotion, then start the
    #    rest so the site comes back on a writable database.
    click.secho(
        "Starting postgres; it replays WAL and (for PITR) recovers to the "
        "target, then promotes.",
        fg="yellow",
    )
    Commands.invoke(
        ctx, "up", daemon=True, machines=["postgres"], allow_build=True
    )
    if _wait_until_promoted(config):
        click.secho(
            "Postgres promoted. Bringing the rest of the stack up.", fg="green"
        )
    else:
        click.secho(
            "Postgres still in recovery after the timeout; bringing the stack "
            "up anyway - check `odoo logs postgres`.",
            fg="red",
        )
    Commands.invoke(ctx, "up", daemon=True, allow_build=True)

    # WAL streaming does NOT resume by itself after a recovery: the timeline
    # changed, and pg_receivewal is still holding a .partial of the old one, so
    # the slot stays uninitialised and `receive-wal` refuses to start. Nothing
    # says so - the instance simply stops archiving WAL, and the next
    # `barman backup` fails with "Impossible to start the backup".
    #
    # Resetting the receive-wal directory drops the stale .partial and creates
    # one for the new timeline. Without this, the advice printed below would
    # itself fail.
    click.secho("Resuming WAL streaming on the new timeline.", fg="yellow")
    try:
        _barman_exec(
            config, ["receive-wal", "--reset", SERVER], interactive=False
        )
        _barman_exec(config, ["cron"], interactive=False)
    except Exception as ex:  # noqa: BLE001
        click.secho(
            f"Could not resume WAL streaming automatically ({ex}).\n"
            "WAL is NOT being archived until this is fixed. Run:\n"
            f"  odoo barman receive-wal-reset\n"
            "then `odoo barman check` and take a fresh `odoo barman backup`.",
            fg="red",
        )

    click.secho(
        "Recovery done. After a PITR the timeline changed - take a fresh "
        "`odoo barman backup` so future backups continue cleanly.",
        fg="green",
    )


def _wait_until_promoted(config, timeout=180):
    """Poll until postgres has finished recovery (pg_is_in_recovery() = false)."""
    from .tools import _execute_sql

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            # query the always-present `postgres` db, not the odoo db (which may
            # not be cleanly available yet during early recovery startup)
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


def _barman_capture(config, args):
    """Run `barman <args>` in the barman container and return its stdout."""
    cmd = __get_cmd(config) + ["exec", "-T", "barman", "barman"] + args
    return subprocess.check_output(cmd, encoding="utf-8")


def _list_backups(config):
    """Return [(label, backup_id)] for the server's base backups, newest first."""
    rows = []
    try:
        out = _barman_capture(config, ["list-backup", SERVER])
    except subprocess.CalledProcessError:
        return rows
    for line in out.splitlines():
        line = line.strip()
        # format: "odoo 20260602T145039 - <weekday> <date> - Size: ... - WAL ..."
        parts = line.split()
        if len(parts) >= 2 and parts[0] == SERVER:
            rows.append((line, parts[1]))
    return rows


def _pick_backup_for_time(config, target_time):
    """Return the newest base-backup id whose start is <= target_time, or None.

    Backup ids are barman's ``YYYYMMDDTHHMMSS``. We parse the target back from
    the ``YYYY-MM-DD HH:mm:ssZZ`` string we produced. barman re-validates the
    chosen backup against the target, so a small clock/timezone skew at worst
    makes barman reject it with a clear message rather than recovering wrongly.
    """
    try:
        tgt = arrow.get(target_time, "YYYY-MM-DD HH:mm:ssZZ")
    except (arrow.parser.ParserError, ValueError):
        return None
    best = None  # (timestamp, backup_id)
    for _label, bid in _list_backups(config):
        try:
            bts = arrow.get(bid, "YYYYMMDDTHHmmss", tzinfo="local")
        except (arrow.parser.ParserError, ValueError):
            continue
        if bts <= tgt and (best is None or bts > best[0]):
            best = (bts, bid)
    return best[1] if best else None


def _parse_target_time(raw):
    """Parse a user-entered absolute timestamp; return a barman-ready string."""
    raw = (raw or "").strip()
    for fmt in [
        # tz-aware variants first so an already-normalised value (e.g. produced
        # by this function or by _parse_age) re-parses cleanly -> idempotent.
        "YYYY-MM-DD HH:mm:ssZZ",
        "YYYY-MM-DDTHH:mm:ssZZ",
        "YYYY-MM-DD HH:mm:ss",
        "YYYY-MM-DD HH:mm",
        "YYYY-MM-DDTHH:mm:ss",
        "YYYY-MM-DD",
    ]:
        try:
            dt = arrow.get(raw, fmt, tzinfo="local")
            break
        except (arrow.parser.ParserError, ValueError):
            dt = None
    if dt is None:
        abort(f"Invalid timestamp '{raw}'. Use e.g. 2026-05-31 14:25:00.")
    if dt > arrow.now():
        abort(f"Timestamp '{raw}' is in the future - nothing to recover to.")
    return dt.format("YYYY-MM-DD HH:mm:ssZZ")


def _parse_age(raw):
    """Parse an age like '30m' / '2h' / '90s' / '1d' into a barman-ready
    absolute timestamp (now - age)."""
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
    """Interactive picker. Returns (backup_id, target_time, target_name)."""
    choices = []
    for label, bid in _list_backups(config):
        choices.append((f"Backup  {label}", ("backup", bid)))
    choices += [
        ("Point-in-Time: enter an absolute timestamp", ("time", None)),
        ("Age: enter how far back (e.g. 30m, 2h, 1d)", ("age", None)),
        ("Named restore point: enter a name", ("name", None)),
        ("Abort", ("abort", None)),
    ]
    answer = inquirer.prompt(
        [
            inquirer.List(
                "sel", "Recover the database to which point?", choices=choices
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
        raw = click.prompt("Target timestamp (YYYY-MM-DD HH:MM:SS)")
        return None, _parse_target_time(raw), None
    if kind == "age":
        raw = click.prompt("How far back? (e.g. 30m, 2h, 90s, 1d)")
        return None, _parse_age(raw), None
    if kind == "name":
        raw = click.prompt("Restore point name").strip()
        if not raw:
            abort("Empty restore point name.")
        return None, None, raw
    abort("Aborted.")


@barman.command(
    name="switch-wal",
    help="Force a WAL switch + archive (useful to verify streaming).",
)
@pass_config
def barman_switch_wal(config):
    _barman_exec(config, ["switch-wal", "--force", "--archive", SERVER])


@barman.command(
    name="receive-wal-reset",
    help=(
        "Reset the WAL receiver so streaming resumes on the current timeline. "
        "Needed after a recovery - which `odoo barman recover` now does itself."
    ),
)
@pass_config
def barman_receive_wal_reset(config):
    # After a PITR the timeline changes while pg_receivewal still holds a
    # .partial of the old one, so the replication slot stays uninitialised and
    # nothing archives WAL any more - silently. This drops the stale file,
    # creates one for the new timeline and lets barman's cron start the
    # receiver again.
    _barman_exec(config, ["receive-wal", "--reset", SERVER], interactive=False)
    _barman_exec(config, ["cron"], interactive=False)


Commands.register(barman_backup)
Commands.register(barman_recover)


# Top-level shortcut: `odoo barman-status` → same as `odoo barman status`.
# The hyphenated name avoids the AliasedGroup tie with `setup status` that
# caused `odoo status` to resolve to barman's status instead of setup's.
# A dedicated command (not cli.add_command(barman_status, name=...)) so the
# command object's .name is really "barman-status" — re-registering the
# subgroup command under an alias keeps .name == "status", which breaks
# AliasedGroup's name-based tie-breaks and garbles its error messages.
@cli.command(
    name="barman-status",
    help="Show barman server status (streaming, slot, last backup).",
)
@pass_config
def barman_status_toplevel(config):
    _barman_exec(config, ["status", SERVER])


# --------------------------------------------------------------------------- #
# Update guard: take a PITR safepoint before `odoo update`, offer rollback on  #
# failure. Called from lib_module.update().                                    #
# --------------------------------------------------------------------------- #


def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def guard_update_enabled(config):
    """True when both barman and the update-guard setting are on."""
    return _truthy(getattr(config, "run_barman", "0")) and _truthy(
        getattr(config, "barman_guard_update", "0")
    )


def create_update_safepoint(config):
    """Create a named PITR restore point before an update and make sure its WAL
    is archived to barman. Returns the marker name (or None on failure)."""
    from .tools import _execute_sql

    marker = "pre_update_" + arrow.now().format("YYYYMMDDHHmmss")
    try:
        conn = config.get_odoo_conn()
        _execute_sql(conn, f"SELECT pg_create_restore_point('{marker}')")
        # force the WAL segment holding the marker to be completed + archived,
        # then give barman's ~30s cron a moment to move it into the catalog.
        _barman_exec(
            config,
            ["switch-wal", "--force", "--archive", SERVER],
            interactive=False,
        )
        time.sleep(35)
    except Exception as ex:  # noqa: BLE001
        click.secho(
            f"Could not create barman safepoint ({ex}); continuing without it.",
            fg="yellow",
        )
        return None
    return marker


def offer_safepoint_rollback(ctx, config, marker, non_interactive):
    """On update failure, offer (interactively) to roll the DB back to the
    pre-update safepoint. Non-interactive runs only print instructions."""
    click.secho(
        f"\nUpdate failed. A pre-update PITR safepoint exists: '{marker}'.",
        fg="red",
    )
    manual = f"odoo barman recover --target-name {marker}"
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
    # _perform_recover brings the whole stack back up itself.
    _perform_recover(ctx, config, "latest", None, marker)
