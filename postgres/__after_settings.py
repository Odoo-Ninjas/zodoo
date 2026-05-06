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

    # DB_MAXCONN (odoo-side connection-pool ceiling) must always be
    # computed — even when RUN_POSTGRES=0 (external DB) — otherwise
    # the __DB_MAXCONN__ placeholder in odoo config templates stays
    # unsubstituted and odoo crashes at CLI parse time.
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

    # Track whether the user already pinned postgres max_connections — affects
    # only POSTGRES_CONFIG, not DB_MAXCONN. DB_MAXCONN is the odoo-side
    # connection-pool ceiling and must always be set, otherwise the
    # `__DB_MAXCONN__` placeholder in the odoo config templates is left
    # unsubstituted and odoo crashes at CLI parse time.
    user_override_max_conn = False

    existing_config = settings.get("POSTGRES_CONFIG", "")
    if "max_connections" in existing_config:
        user_override_max_conn = True

    # Also respect override in ~/.odoo/postgres.conf or ~/.odoo/<project>/postgres.conf
    from pathlib import Path

    if not user_override_max_conn:
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
                    user_override_max_conn = True
                    break

    def _parse_channels(raw):
        parts = [x.strip().split(":") for x in raw.split(",") if x.strip()]
        parts = [(k.strip(), int(v)) for k, v in parts]
        non_root = [p for p in parts if p[0] != "root"]
        if non_root:
            return sum(v for _, v in non_root)
        elif parts:
            return sum(v for _, v in parts)
        return 1

    try:
        web = int(settings.get("ODOO_WORKERS_WEB", 6))
        cron = int(settings.get("ODOO_MAX_CRON_THREADS", 2))

        # Check both spelling variants; use the larger result.
        # ODOO_QUEUEJOB_CHANNELS (singular) is the per-channel concurrency
        # config written into config_queuejob; ODOO_QUEUEJOBS_CHANNELS
        # (plural) is a legacy alias.  Prefer the singular form when set.
        qj_singular = settings.get("ODOO_QUEUEJOB_CHANNELS", "")
        qj_plural = settings.get("ODOO_QUEUEJOBS_CHANNELS", "root:1")
        channels_raw = qj_singular if qj_singular else qj_plural
        qj_sum = max(
            _parse_channels(qj_singular) if qj_singular else 1,
            _parse_channels(qj_plural),
        )
        queuejob_workers = qj_sum * 2  # matches _get_queuejob_channels

        total = web + cron + queuejob_workers
        PER_PROCESS = 3.0
        # HEADROOM covers: superuser/monitoring sessions, `odoo update`
        # transient workers, AND the overhead of zodoo running web/cron/
        # queuejobs as separate containers (each adds its own master process
        # plus at least one extra cursor).  3 containers × ~5 extra = 15,
        # plus the original 30 for maintenance → 50 total.
        HEADROOM = 50
        MIN_FLOOR = 100
        extra = int(settings.get("EXTRA_DB_CONN", 0))
        max_conn = max(MIN_FLOOR, math.ceil(total * PER_PROCESS) + HEADROOM) + extra
    except (ValueError, TypeError):
        return

    settings["DB_MAXCONN"] = str(max_conn)

    if not user_override_max_conn:
        glue = (
            "" if not existing_config or existing_config.endswith(";") else ";"
        )
        settings["POSTGRES_CONFIG"] = (
            f"{existing_config}{glue}max_connections={max_conn}"
        )

        # superuser_reserved_connections: ~10 % of max_connections (min 3, capped at 20)
        # so admins / monitoring can still connect when the regular pool is exhausted.
        # Skipped if the user already set the key in POSTGRES_CONFIG.
        if "superuser_reserved_connections" not in settings.get(
            "POSTGRES_CONFIG", ""
        ):
            reserved = max(3, min(20, math.ceil(max_conn * 0.1)))
            current = settings["POSTGRES_CONFIG"]
            glue2 = "" if current.endswith(";") else ";"
            settings["POSTGRES_CONFIG"] = (
                f"{current}{glue2}superuser_reserved_connections={reserved}"
            )
