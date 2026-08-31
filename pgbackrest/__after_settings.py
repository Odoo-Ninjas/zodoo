def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _stanza(settings):
    """PGBR_STANZA with $PROJECT_NAME resolved - see __after_compose."""
    raw = (settings.get("PGBR_STANZA") or "").strip()
    project = (settings.get("PROJECT_NAME") or "").strip()
    if project:
        for placeholder in ("${PROJECT_NAME}", "$PROJECT_NAME"):
            raw = raw.replace(placeholder, project)
    return raw.strip() or project or "odoo"


def after_settings(settings, config):
    """Guard rails for the pgBackRest integration.

    Three of them, and the third exists because this replaces something that
    was already running in production.
    """
    import click

    # Continuous archiving plus nightly base backups are a production concern
    # and pure overhead on a developer box. Under DEVMODE the service is not
    # even merged into the compose, so postgres keeps its stock configuration
    # and never gets an archive_command. Opt back in to test the integration.
    if settings.get("DEVMODE") == "1" and not _truthy(
        settings.get("PGBR_FORCE_IN_DEVMODE", "0")
    ):
        settings["RUN_PGBACKREST"] = "0"

    # pgbackrest reads PGDATA directly and talks to postgres over its unix
    # socket. Neither is possible with an external postgres, so rather than
    # letting the compose merge fail on a dangling depends_on, say why.
    if _truthy(settings.get("RUN_PGBACKREST", "0")) and not _truthy(
        settings.get("RUN_POSTGRES", "0")
    ):
        click.secho(
            "RUN_PGBACKREST=1 needs a zodoo-managed postgres (RUN_POSTGRES=1): "
            "pgbackrest reads the data directory directly and connects through "
            "postgres' unix socket, and can do neither against an external "
            "server. Disabling pgbackrest for this project.",
            fg="red",
        )
        settings["RUN_PGBACKREST"] = "0"

    # The backup jobs are defined on every project, so they have to disappear
    # where they have nothing to do rather than starting the CLI only to have
    # it return. An empty CRONJOB_* value is skipped by the cron daemon
    # (`if not job: continue` in cronjobs/bin/run.py), so clearing it removes
    # the job instead of producing a broken schedule.
    if not _truthy(settings.get("RUN_PGBACKREST", "0")):
        for key in (
            "CRONJOB_PGBACKREST_FULL",
            "CRONJOB_PGBACKREST_DIFF",
            "CRONJOB_PGBACKREST_INCR",
            "CRONJOB_PGBACKREST_CHECK",
        ):
            settings[key] = ""
    elif not (settings.get("PGBR_INCR_CRON") or "").strip():
        # Intra-day incrementals are opt-in. Without a schedule the entry would
        # otherwise be a bare command with no cron expression in front of it,
        # which the daemon cannot parse at all.
        settings["CRONJOB_PGBACKREST_INCR"] = ""

    # With a repo host, retention is not configured here - which is a
    # deliberate hole and therefore has to be said out loud once. Nothing on
    # this machine will ever expire a backup, and if the backup server has no
    # scheduled expire either, the repository grows until the disk is full.
    # That is the same failure that filled the dump directory with 3.4 TB, so
    # it gets a message rather than a comment in a file nobody opens.
    if (
        _truthy(settings.get("RUN_PGBACKREST", "0"))
        and (settings.get("PGBR_REPO_HOST") or "").strip()
    ):
        click.secho(
            "pgbackrest: the repository lives on "
            f"{settings['PGBR_REPO_HOST']}, so retention is configured "
            "THERE, not here - the machine that manages the disk manages the "
            "retention.\n"
            "  -> the backup server needs repo1-retention-* in its own "
            "pgbackrest.conf and a scheduled `pgbackrest --stanza="
            f"{_stanza(settings)} expire`."
            "\n"
            "The PGBR_RETENTION_* settings are ignored in this mode; "
            "without an expire on the backup server nothing is ever deleted.",
            fg="yellow",
        )

    # Unencrypted backups on somebody else's storage. Worth a red line, not a
    # comment: with a repo host the data leaves this machine, and without a
    # passphrase it lands as plain zstd - the manifest is readable text and
    # every data file unpacks with `zstd -d`. The storage under the backup
    # server is rented, so "nobody can get at it" is not an argument.
    #
    # Said at reload time because it cannot be fixed later: pgBackRest cannot
    # convert an existing repository, so switching encryption on afterwards
    # means creating the stanza fresh and starting the history over.
    if (
        _truthy(settings.get("RUN_PGBACKREST", "0"))
        and (settings.get("PGBR_REPO_HOST") or "").strip()
        and not (settings.get("PGBR_CIPHER_PASS") or "").strip()
    ):
        click.secho(
            "pgbackrest: backups are sent to "
            f"{settings['PGBR_REPO_HOST']} UNENCRYPTED. Anyone with file "
            "access there - including the storage provider - can read them "
            "with `zstd -d`.\n"
            "  -> get a passphrase with `pgbackrest-area create "
            f"{_stanza(settings)}` on the backup server, put it in the "
            "hosting record, then set PGBR_CIPHER_PASS.\n"
            "This cannot be switched on later: the stanza would have to be "
            "recreated and the backup history would start over.",
            fg="red",
        )

    # Barman is gone, and a project that still carries RUN_BARMAN=1 in its
    # settings would otherwise simply stop being backed up without a word -
    # the service no longer exists, so nothing would fail, nothing would log,
    # and it would surface on the day somebody needs a restore.
    if _truthy(settings.get("RUN_BARMAN", "0")):
        click.secho(
            "RUN_BARMAN=1 is set, but the barman path has been replaced by "
            "pgBackRest and the barman service no longer exists.\n"
            "  -> set RUN_BARMAN=0 and RUN_PGBACKREST=1, then "
            "`odoo reload && odoo up -d`.\n"
            "Note the old barman catalogue is NOT migrated: pgbackrest starts "
            "a fresh stanza, so keep the barman volume until the first "
            "pgbackrest backup has been verified with `odoo pgbackrest check`.",
            fg="red",
        )
