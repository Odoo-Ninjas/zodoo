import json
import re
import socket
import subprocess
import traceback
import sys
import time
import uuid
from pathlib import Path
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


# --------------------------------------------------------------------------- #
# verify - die Rueckspielprobe                                                 #
# --------------------------------------------------------------------------- #

# Derselbe Pfad, unter dem auch die echte Instanz ihr Datenverzeichnis sieht.
# Das ist der Kniff, der diese Probe einfach macht: die Konfiguration des
# Projekts stimmt dann unveraendert weiter, es liegt nur ein Wegwerf-Volume
# darunter statt der echten Platte.
VERIFY_PGDATA = "/var/lib/postgresql/data/pgdata"

# Wieviel Zeit die zurueckgespielte Instanz zum Hochfahren bekommt.
VERIFY_STARTUP_TIMEOUT = 300

# Was Postgres beim Wiederherstellen mindestens so gross braucht wie auf der
# Quelle, sonst: "recovery aborted because of insufficient parameter settings".
# Links der Name in pg_controldata, rechts der Serverparameter.
VERIFY_MINIMUMS = {
    "max_connections": "max_connections",
    "max_worker_processes": "max_worker_processes",
    "max_wal_senders": "max_wal_senders",
    "max_prepared_xacts": "max_prepared_transactions",
    "max_locks_per_xact": "max_locks_per_transaction",
}


class VerifyFailed(Exception):
    """Ein Schritt der Probe ist gescheitert - mit Grund."""


def _compose_config(config):
    out = subprocess.check_output(
        __get_cmd(config) + ["config", "--format", "json"], encoding="utf-8"
    )
    return json.loads(out)


def _verify_repo_is_local(config):
    """Liegt das Repository auf dieser Maschine oder auf dem Backup-Server?

    Steht ein repo1-path in der Konfiguration, gehoert die Ablage diesem
    Verbund selbst - dann muss die Probe das Volume mitbekommen, sonst findet
    sie nichts. Steht dort ein repo1-host, ist die Ablage anderswo und wird
    ueber das Netz gelesen.
    """
    conf = Path(config.HOST_RUN_DIR) / "pgbackrest" / "pgbackrest.conf"
    try:
        zeilen = conf.read_text().splitlines()
    except OSError:
        return False
    return any(
        z.strip().startswith("repo1-path") for z in zeilen
    )


def _volume_targets(service):
    """Die Einhaengungen eines Dienstes als (Quelle, Ziel).

    `compose config` liefert je nach Version zwei Formen - die ausfuehrliche
    als Abbildung und die kurze als "quelle:ziel[:optionen]". Beide kommen
    vor, also werden beide gelesen. Wer nur eine kennt, findet auf der anderen
    Maschine nichts und meldet dann etwas Irrefuehrendes.
    """
    for vol in service.get("volumes", []) or []:
        if isinstance(vol, dict):
            quelle, ziel = vol.get("source"), vol.get("target")
        else:
            teile = str(vol).split(":")
            if len(teile) < 2:
                continue
            quelle, ziel = teile[0], teile[1]
        if quelle and ziel:
            yield quelle, ziel


def _verify_mounts(config):
    """Die Einhaengungen der Probe - und vor allem: welche NICHT.

    Bewusst NICHT dabei ist das Datenvolume des Projekts. Nicht, weil wir
    aufpassen wuerden, nichts hineinzuschreiben, sondern damit es gar nicht
    erreichbar ist: was nicht eingehaengt ist, kann auch ein Fehler in diesem
    Code nicht ueberschreiben. Eine Probe, die im Zweifel die Produktion
    plaettet, waere schlimmer als gar keine.

    Das Repository wird, wenn es lokal liegt, NUR LESEND eingehaengt. Eine
    Rueckspielprobe hat im Bestand nichts zu schreiben.
    """
    services = _compose_config(config).get("services", {})
    sidecar = services.get("pgbackrest") or {}

    run_pgbr = Path(config.HOST_RUN_DIR) / "pgbackrest"
    mounts = [f"{run_pgbr}:/etc/pgbackrest:ro"]

    for quelle, ziel in _volume_targets(sidecar):
        if ziel == "/var/lib/pgbackrest":
            mounts.append(f"{quelle}:/var/lib/pgbackrest:ro")

    if _verify_repo_is_local(config) and len(mounts) == 1:
        # Lieber hier klar scheitern als pgbackrest gleich "missing stanza
        # path" sagen lassen - das klingt nach einem kaputten Bestand und
        # schickt den Suchenden ins Repository, obwohl nur die Einhaengung
        # fehlt.
        raise VerifyFailed(
            "das Repository liegt lokal, aber sein Volume ist in der "
            "compose-Konfiguration nicht zu finden - ohne das kann die Probe "
            "den Bestand nicht lesen"
        )
    return mounts


def _verify_images(config):
    """Die Abbilder, mit denen die Probe arbeitet.

    `compose config` fuehrt bei GEBAUTEN Diensten kein `image` - es steht dort
    nur ein `build`. Compose vergibt dann selbst den Namen
    <projekt>-<dienst>, und genau der wird hier hilfsweise gebildet. Ohne das
    landet ein None in der docker-Zeile, und der Fehler taucht erst tief in
    subprocess auf, wo ihn niemand mehr zuordnet.
    """
    services = _compose_config(config).get("services", {})
    fehlend = [n for n in ("pgbackrest", "postgres") if n not in services]
    if fehlend:
        raise VerifyFailed(
            "diesem Projekt fehlen die Dienste " + ", ".join(fehlend)
        )
    return tuple(
        services[dienst].get("image")
        or f"{config.project_name}-{dienst}"
        for dienst in ("pgbackrest", "postgres")
    )


def _docker(*args, timeout=1800, check=True):
    out = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )
    if check and out.returncode != 0:
        raise VerifyFailed(
            f"{' '.join(args[:3])} ...: rc={out.returncode}\n"
            + (out.stderr or out.stdout).strip()[-2000:]
        )
    return out


def _verify_latest_backup(config, stanza, image, mounts):
    out = _docker(
        "run", "--rm",
        *sum((["-v", m] for m in mounts), []),
        "--entrypoint", "/usr/sbin/gosu", image,
        "pgbackrest", "pgbackrest",
        "--stanza", stanza, "info", "--output=json",
        timeout=300,
    )
    try:
        daten = json.loads(out.stdout)
    except ValueError as ex:
        raise VerifyFailed(f"info lieferte kein JSON: {ex}") from ex
    if not daten:
        raise VerifyFailed(f"das Repository kennt die Stanza '{stanza}' nicht")

    # Zwischen "leer" und "unlesbar" unterscheiden. Beides sieht in der Ausgabe
    # gleich aus - null Sicherungen - hat aber voellig verschiedene Ursachen:
    # das eine ist eine Instanz, die noch nie gesichert hat, das andere eine
    # falsche Passphrase oder ein beschaedigtes Repository. Wer beides "keine
    # Sicherung" nennt, schickt den Suchenden in die falsche Richtung.
    status = daten[0].get("status") or {}
    code = status.get("code")
    if code == 1:
        # Der Bestand ist erreichbar, diese Stanza aber nicht darin. Das ist
        # etwas anderes als "nicht lesbar" und braucht eine andere Suche.
        raise VerifyFailed(
            f"im Repository gibt es keinen Bereich '{stanza}' "
            f"({status.get('message')}) - entweder wurde nie eine Stanza "
            "angelegt, oder es wird am falschen Ort gesucht"
        )
    if code not in (0, 2):
        raise VerifyFailed(
            f"das Repository ist nicht lesbar (Status {code}: "
            f"{status.get('message')}) - haeufigste Ursache: falsche "
            "Passphrase oder falsches Zertifikat"
        )
    if not daten[0].get("backup"):
        raise VerifyFailed(f"'{stanza}' ist angemeldet, hat aber nie gesichert")
    return daten[0]["backup"][-1]["label"]


def _verify_minimums(postgres_image, volume, mounts):
    """Die Mindestwerte der QUELLE aus dem zurueckgespielten pg_control lesen.

    Warum nicht die zurueckgespielte postgresql.conf: zodoo reicht diese Werte
    als Startparameter (-c) an Postgres, sie stehen also gar nicht in der
    Datei. In pg_control stehen sie immer - dort hat Postgres selbst
    festgehalten, womit der Cluster lief. Ausgelesen statt geraten: zu klein
    laesst die Probe scheitern, zu gross verdeckt nichts, kostet aber Speicher.
    """
    out = _docker(
        "run", "--rm",
        "-v", f"{volume}:{VERIFY_PGDATA}",
        *sum((["-v", m] for m in mounts), []),
        "--user", "0",
        "--entrypoint", "pg_controldata", postgres_image, VERIFY_PGDATA,
        check=False, timeout=300,
    )
    werte = {}
    for zeile in (out.stdout or "").splitlines():
        if ":" not in zeile:
            continue
        links, rechts = zeile.split(":", 1)
        for feld, parameter in VERIFY_MINIMUMS.items():
            if feld in links and rechts.strip().isdigit():
                werte[parameter] = rechts.strip()
    return werte


def _verify_query(container, frage, db="postgres", timeout=180):
    return _docker(
        "exec", container, "psql", "-U", "postgres", "-d", db, "-tAc", frage,
        check=False, timeout=timeout,
    )


def _verify_read_user_data(container):
    """Die eigentliche Frage - und sie geht an NUTZDATEN, nicht an den Katalog.

    Ein Cluster, der hochfaehrt und erst beim ersten echten Lesen auf eine
    kaputte Seite laeuft, soll hier durchfallen. Deshalb die groesste Tabelle
    der groessten Datenbank: dort ist am meisten zu holen und am ehesten etwas
    kaputt.
    """
    db = _verify_query(
        container,
        "SELECT datname FROM pg_database WHERE datallowconn "
        "AND NOT datistemplate ORDER BY pg_database_size(oid) DESC LIMIT 1",
    ).stdout.strip()
    if not db:
        raise VerifyFailed("in der zurueckgespielten Instanz ist keine Datenbank")

    tabelle = _verify_query(
        container,
        "SELECT quote_ident(n.nspname)||'.'||quote_ident(c.relname) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind = 'r' "
        "AND n.nspname NOT IN ('pg_catalog','information_schema') "
        "ORDER BY c.relpages DESC LIMIT 1",
        db=db,
    ).stdout.strip()
    if not tabelle:
        raise VerifyFailed(
            f"in '{db}' gibt es keine einzige Nutztabelle - die Sicherung ist "
            "zwar lesbar, aber leer"
        )

    out = _verify_query(container, f"SELECT count(*) FROM {tabelle}", db=db)
    if out.returncode != 0 or not out.stdout.strip().isdigit():
        raise VerifyFailed(
            f"{db}.{tabelle} laesst sich nicht lesen: "
            + (out.stderr or out.stdout).strip()[-800:]
        )
    return {"database": db, "table": tabelle, "rows": int(out.stdout.strip())}


def _verify_start_and_read(postgres_image, volume, mounts, container):
    parameter = []
    for schluessel, wert in sorted(
        _verify_minimums(postgres_image, volume, mounts).items()
    ):
        parameter += ["-c", f"{schluessel}={wert}"]

    _docker(
        "run", "-d", "--name", container,
        "-v", f"{volume}:{VERIFY_PGDATA}",
        # Die Repo-Konfiguration muss AUCH hier hinein: Postgres holt sich
        # waehrend der Wiederherstellung die fehlenden WAL-Segmente selbst aus
        # dem Repository (archive-get). Damit prueft die Probe nicht nur die
        # Sicherungsdateien, sondern auch die Archivstrecke.
        *sum((["-v", m] for m in mounts), []),
        "-e", f"PGDATA={VERIFY_PGDATA}",
        "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
        "--entrypoint", "docker-entrypoint.sh", postgres_image, "postgres",
        *parameter,
        timeout=300,
    )

    def protokoll():
        out = _docker("logs", "--tail", "40", container, check=False, timeout=120)
        return ((out.stdout or "") + (out.stderr or "")).strip()[-1800:]

    ende = time.time() + VERIFY_STARTUP_TIMEOUT
    while time.time() < ende:
        zustand = _docker(
            "inspect", container, "--format", "{{.State.Status}}",
            check=False, timeout=120,
        ).stdout.strip()
        if zustand == "exited":
            # Nicht bis zum Zeitablauf warten - der Start ist gescheitert, und
            # das Protokoll sagt warum.
            raise VerifyFailed(
                "die zurueckgespielte Datenbank ist beim Start ausgestiegen:\n"
                + protokoll()
            )
        if _verify_query(container, "SELECT 1").stdout.strip() == "1":
            return _verify_read_user_data(container)
        time.sleep(5)

    raise VerifyFailed(
        f"die zurueckgespielte Datenbank antwortet nach "
        f"{VERIFY_STARTUP_TIMEOUT}s nicht:\n" + protokoll()
    )


def _verify_cleanup(container, volume):
    for cmd in (("rm", "-f", container), ("volume", "rm", "-f", volume)):
        try:
            _docker(*cmd, check=False, timeout=300)
        except Exception:  # noqa: BLE001 - Aufraeumen darf nie das Ergebnis kippen
            pass


def run_verify(config, stanza=None):
    """Eine Rueckspielprobe durchfuehren und das Ergebnis zurueckgeben."""
    stanza = stanza or _stanza(config)
    kennung = uuid.uuid4().hex[:10]
    container = f"verify-{stanza}-{kennung}"
    volume = f"verify_{stanza}_{kennung}".replace("-", "_")
    begonnen = time.time()

    ergebnis = {
        "area": stanza,
        "bench": socket.gethostname(),
        "checked_at": int(begonnen),
    }
    try:
        pgbr_image, pg_image = _verify_images(config)
        mounts = _verify_mounts(config)

        ergebnis["backup"] = _verify_latest_backup(
            config, stanza, pgbr_image, mounts
        )

        _docker("volume", "create", volume, timeout=120)
        # Ein frisches Volume gehoert root; pgbackrest laeuft als pgbackrest
        # und verweigert sonst ("not owned by current user"). Zu Recht: als
        # root angelegte Dateien koennte der Postgres danach nicht lesen.
        _docker(
            "run", "--rm", "-v", f"{volume}:{VERIFY_PGDATA}", "--user", "0",
            "--entrypoint", "chown", pgbr_image,
            "-R", "pgbackrest:pgbackrest", VERIFY_PGDATA,
            timeout=300,
        )
        # --type=immediate: bis zum Ende der Sicherung, nicht weiter. Die Frage
        # ist "laeuft sie wieder an", nicht "spiele WAL bis heute nach" - das
        # waere eine andere Frage und dauert um Groessenordnungen laenger.
        _docker(
            "run", "--rm",
            "-v", f"{volume}:{VERIFY_PGDATA}",
            *sum((["-v", m] for m in mounts), []),
            "--entrypoint", "/usr/sbin/gosu", pgbr_image,
            "pgbackrest", "pgbackrest",
            "--stanza", stanza, "restore",
            "--type=immediate", "--target-action=promote",
            timeout=3600,
        )
        ergebnis.update(
            _verify_start_and_read(pg_image, volume, mounts, container)
        )
        ergebnis["result"] = "passed"
    except VerifyFailed as ex:
        ergebnis["result"] = "failed"
        ergebnis["error"] = str(ex)[-2000:]
    except Exception as ex:  # noqa: BLE001
        # Mit Rueckverfolgung: ein unerwarteter Fehler in der Probe selbst ist
        # sonst nicht auffindbar - "TypeError: expected str" ohne Stelle sagt
        # niemandem, wo er suchen soll.
        ergebnis["result"] = "failed"
        ergebnis["error"] = (
            f"{type(ex).__name__}: {ex}\n" + traceback.format_exc()
        )[-2000:]
    finally:
        _verify_cleanup(container, volume)

    ergebnis["seconds"] = int(time.time() - begonnen)
    return ergebnis


@pgbackrest.command(
    name="verify",
    help=(
        "Restore test: bring the newest backup up as a throwaway postgres and "
        "read real data from it. The only check that says anything about the "
        "CONTENT of the backups - everything else only proves the bytes are "
        "there. Never touches this project's data directory."
    ),
)
@click.option("--stanza", default=None, help="verify another stanza")
@click.option("--json", "as_json", is_flag=True, help="machine readable")
@click.option(
    "--report-to",
    default=None,
    help="directory for the result file, named <stanza>-<timestamp>.json",
)
@pass_config
def pgbackrest_verify(config, stanza, as_json, report_to):
    _ensure_pgbackrest(config)
    ergebnis = run_verify(config, stanza)

    if report_to:
        ziel = Path(report_to)
        ziel.mkdir(parents=True, exist_ok=True)
        stempel = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        datei = ziel / f"{ergebnis['area']}-{stempel}.json"
        datei.write_text(json.dumps(ergebnis, indent=1, sort_keys=True) + "\n")
        click.secho(f"geschrieben: {datei}", fg="green")

    if as_json:
        click.echo(json.dumps(ergebnis, indent=1, sort_keys=True))
    elif ergebnis["result"] == "passed":
        click.secho(
            f"Rueckspielprobe bestanden: Sicherung {ergebnis['backup']} laeuft, "
            f"{ergebnis['rows']} Zeilen aus {ergebnis['table']} gelesen "
            f"({ergebnis['seconds']}s).",
            fg="green",
        )
    else:
        click.secho(
            f"Rueckspielprobe GESCHEITERT: {ergebnis.get('error')}", fg="red"
        )

    if ergebnis["result"] != "passed":
        sys.exit(1)


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


def _enroll_ssl_context(config):
    """TLS context for the enrolment service.

    Plain system trust: the service sits behind the same proxy as every other
    site and carries a publicly issued certificate, so there is a chain to
    verify against and nothing to pin.

    It used to be different. While the service answered with a self-issued
    certificate there was nothing to verify against on first contact, so the
    CA was fetched, pinned and its fingerprint printed - ssh's accept-new
    bargain. That step is gone, and with it the one instruction in the setup
    that people got wrong.

    PGBR_ENROLL_CA still allows pointing at an own CA file, for a service that
    is not reachable under a public name - a test instance, or a customer who
    runs their own.
    """
    import ssl

    own = (getattr(config, "PGBR_ENROLL_CA", "") or "").strip()
    if own:
        return ssl.create_default_context(cafile=own)
    return ssl.create_default_context()


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
            context=_enroll_ssl_context(config),
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

    # Second stream: the filestore goes to the write-only receiver. One
    # approval covers both, so the answer carries both - and a machine that
    # only backs up its database is a machine whose restore is missing every
    # attachment.
    #
    # The upload password is replaceable (`wo-area passwd`); it decides who may
    # upload and decrypts nothing. What must not be lost is the PRIVATE age key
    # in the vault, and that is not created here - the recipient below is the
    # public half, which is why it may sit in a settings file.
    if answer.get("wo_url"):
        update_setting(config, "OFFSITE_WO_URL", answer["wo_url"])
        update_setting(config, "OFFSITE_REST_USER", answer["wo_user"])
        update_setting(config, "OFFSITE_REST_PASSWORD", answer["wo_password"])
        recipient = answer.get("wo_recipient") or ""
        if recipient:
            update_setting(config, "OFFSITE_WO_RECIPIENT", recipient)
            update_setting(config, "RUN_OFFSITE", "1")
        else:
            # Without a public key the filestore run would upload plaintext.
            # Better to leave the stream off and say so than to enable
            # something that quietly ships attachments in the clear.
            click.secho(
                "The backup server did not supply a public age key for the "
                "filestore. The filestore stream stays OFF - switching it on "
                "without a key would upload attachments unencrypted. Ask for "
                "wo-recipient.pub on the backup server, then run this again.",
                fg="red",
            )

    # The request is finished; leaving its state behind would look like an
    # open request forever.
    state_file.unlink(missing_ok=True)

    click.secho(
        f"Stanza '{stanza}' is set up and written to the settings"
        + (", filestore stream included.\n" if answer.get("wo_url") else ".\n")
        + "The passphrase is now in the settings of this project AND in "
        "1Password - it cannot be recovered from the backup server, which "
        "only ever stores ciphertext.\n\n"
        "Next:  odoo reload && odoo up -d && odoo pgbackrest check",
        fg="green",
    )
