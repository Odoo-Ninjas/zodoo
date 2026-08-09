import click

from .cli import cli, pass_config
from .lib_clickhelpers import AliasedGroup
from .tools import abort
from .tools import __get_cmd


@cli.group(
    cls=AliasedGroup,
    help="Verschluesseltes Offsite-Backup (BorgBackup, z.B. Hetzner Storage Box).",
)
@pass_config
def offsite(config):
    pass


def _ensure_offsite(config):
    if not getattr(config, "run_offsite", False):
        abort(
            "Offsite-Backup ist nicht aktiviert. RUN_OFFSITE=1 setzen (auf "
            "DEVMODE-Maschinen zusaetzlich OFFSITE_FORCE_IN_DEVMODE=1), dann "
            "`odoo reload && odoo build offsite`."
        )
    if not (config.OFFSITE_REPO or "").strip():
        abort(
            "OFFSITE_REPO ist leer - es ist kein Offsite-Ziel hinterlegt. "
            "Beispiel fuer eine Hetzner Storage Box:\n"
            "  OFFSITE_REPO=ssh://u123456@u123456.your-storagebox.de:23/./zodoo/projekt"
        )


def _offsite_run(config, args):
    """Startet den offsite-Container fuer einen einzelnen Lauf.

    Der Service liegt im Profil "manual" (kein Dauerlaeufer), deshalb hier
    profile="all" statt des Standardprofils - sonst kennt `docker compose run`
    den Service nicht.
    """
    import subprocess

    _ensure_offsite(config)
    # Fester Containername = Ausschluss paralleler Laeufe: docker verweigert
    # einen zweiten Container gleichen Namens. Darauf stuetzt sich der
    # Entrypoint, wenn er eine haengende Sperre aufbricht - ohne diesen
    # Ausschluss koennte er die Sperre eines noch laufenden Backups brechen.
    name = f"{config.project_name}_offsite_run"
    cmd = __get_cmd(config, profile="all") + [
        "run",
        "--rm",
        "-T",
        "--name",
        name,
        "offsite",
    ]
    cmd += args
    return subprocess.check_call(cmd)


@offsite.command(
    name="backup",
    help="Jetzt ein Offsite-Backup ziehen (derselbe Lauf wie der Cronjob).",
)
@pass_config
def offsite_backup(config):
    # Haengt im gemeinsamen Cronjobs-Daemon (CRONJOB_OFFSITE_BACKUP) und
    # laeuft damit auf JEDEM Projekt. Ohne Offsite-Konfiguration muss das ein
    # stiller Erfolg sein, sonst meldet jedes andere Projekt jede Nacht einen
    # Cron-Fehler.
    if not getattr(config, "run_offsite", False):
        click.secho(
            "Offsite-Backup ist nicht aktiviert (RUN_OFFSITE=0); uebersprungen.",
            fg="yellow",
        )
        return
    if not (config.OFFSITE_REPO or "").strip():
        click.secho(
            "Offsite-Backup ist aktiviert, aber OFFSITE_REPO ist leer - "
            "es wird nichts gesichert.",
            fg="red",
        )
        return
    _offsite_run(config, ["backup"])


@offsite.command(
    name="init",
    help="Repository anlegen (passiert beim ersten Backup automatisch).",
)
@pass_config
def offsite_init(config):
    _offsite_run(config, ["init"])


@offsite.command(name="list", help="Archive im Offsite-Repository auflisten.")
@pass_config
def offsite_list(config):
    _offsite_run(config, ["list"])


@offsite.command(name="info", help="Repository-Kennzahlen (Groesse, Dedup).")
@pass_config
def offsite_info(config):
    _offsite_run(config, ["info"])


@offsite.command(
    name="check",
    help="Integritaet pruefen - liest die Daten neu (dauert und kostet Traffic).",
)
@pass_config
def offsite_check(config):
    _offsite_run(config, ["check"])


@offsite.command(name="prune", help="Aufbewahrungsregeln jetzt anwenden.")
@pass_config
def offsite_prune(config):
    _offsite_run(config, ["prune"])


@offsite.command(
    name="borg",
    help="Beliebiges borg-Kommando im Repository ausfuehren (Notausgang).",
    context_settings=dict(ignore_unknown_options=True),
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@pass_config
def offsite_borg(config, args):
    _offsite_run(config, ["borg"] + list(args))
