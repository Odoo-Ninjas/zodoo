def after_settings(settings, config):
    if settings.get("USE_DOCKER", "1") == "0":
        settings["RUN_POSTGRES"] = "0"
    if "RUN_POSTGRES" in settings.keys() and settings["RUN_POSTGRES"] == "1":
        values = {
            "DB_HOST": "postgres",
            "DB_PORT": "5432",
            "DB_USER": "odoo",
            "DB_PWD": "odoo",
        }
        for k, v in values.items():
            settings[k] = v

        _compute_max_connections(settings)


def _compute_max_connections(settings):
    """
    Derive postgres max_connections from the odoo process counts:

        max_connections = max(
            MIN_FLOOR,
            ceil(
                (ODOO_WORKERS_WEB
                 + ODOO_MAX_CRON_THREADS
                 + queuejob_workers) * PER_PROCESS
            ) + HEADROOM,
        )

    where queuejob_workers mirrors the formula in odoo/bin/tools.py:
    sum of the non-root channel capacities (or the root channel if it's
    the only one) * 2.

    PER_PROCESS = 3 because each odoo worker holds steady-state at least
    a main + longpoll + occasional snapshot/maintenance cursor; the old
    1.2 multiplier underestimated this and caused "too many clients
    already" on `odoo update` of small dev installs (default 6 web + 2
    cron + 2 queuejob → 22 conns, instantly exhausted).

    HEADROOM = 30 covers superuser / monitoring / maintenance sessions
    plus the side processes that an `odoo update` spawns transiently.

    MIN_FLOOR = 100 keeps even tiny installs (e.g. 1 web worker) above
    the threshold where postgres clients exhaust during init.

    Additionally compute postgres `superuser_reserved_connections` as
    ~10% of max_connections (min 3, capped at 20) so admin / monitoring
    can still log in when regular workers exhausted the pool.

    Both values are appended to POSTGRES_CONFIG so they override any
    static defaults from postgres/config.  Skipped if the user already
    set the corresponding key in POSTGRES_CONFIG explicitly.
    """
    import math

    existing_config = settings.get("POSTGRES_CONFIG", "")
    if "max_connections" in existing_config:
        return  # user took over — don't second-guess

    # Also respect override in ~/.odoo/postgres.conf or ~/.odoo/<project>/postgres.conf
    from pathlib import Path

    for candi in [
        Path("~/.odoo/postgres.conf").expanduser(),
        Path(
            f"~/.odoo/{settings.get('PROJECT_NAME', '')}/postgres.conf"
        ).expanduser(),
    ]:
        if candi.is_file():
            try:
                content = candi.read_text()
            except OSError:
                continue
            lines = [
                ln.strip()
                for ln in content.splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            if any("max_connections" in ln for ln in lines):
                return

    try:
        web = int(settings.get("ODOO_WORKERS_WEB", 6))
        cron = int(settings.get("ODOO_MAX_CRON_THREADS", 2))
        channels_raw = settings.get("ODOO_QUEUEJOBS_CHANNELS", "root:1")
        parts = [
            x.strip().split(":") for x in channels_raw.split(",") if x.strip()
        ]
        parts = [(k.strip(), int(v)) for k, v in parts]
        non_root = [p for p in parts if p[0] != "root"]
        if non_root:
            qj_sum = sum(v for _, v in non_root)
        elif parts:
            qj_sum = sum(v for _, v in parts)
        else:
            qj_sum = 1
        queuejob_workers = qj_sum * 2  # matches _get_queuejob_channels

        total = web + cron + queuejob_workers
        PER_PROCESS = 3.0
        HEADROOM = 30
        MIN_FLOOR = 100
        max_conn = max(MIN_FLOOR, math.ceil(total * PER_PROCESS) + HEADROOM)
    except (ValueError, TypeError):
        return

    glue = "" if not existing_config or existing_config.endswith(";") else ";"
    settings["POSTGRES_CONFIG"] = (
        f"{existing_config}{glue}max_connections={max_conn}"
    )

    # superuser_reserved_connections: ~10 % of max_connections (min 3, capped at 20)
    # so admins / monitoring can still connect when the regular pool is exhausted.
    # Skipped if the user already set the key in POSTGRES_CONFIG.
    if "superuser_reserved_connections" not in settings.get("POSTGRES_CONFIG", ""):
        reserved = max(3, min(20, math.ceil(max_conn * 0.1)))
        current = settings["POSTGRES_CONFIG"]
        glue2 = "" if current.endswith(";") else ";"
        settings["POSTGRES_CONFIG"] = (
            f"{current}{glue2}superuser_reserved_connections={reserved}"
        )
