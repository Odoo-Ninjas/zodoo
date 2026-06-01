def _truthy(val):
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def after_compose(config, settings, yml, globals):
    """Enable WAL streaming on postgres when Barman is active.

    This hook only runs when the ``barman`` service is part of the merged
    compose (i.e. RUN_BARMAN=1), because ``_execute_after_compose`` discovers
    ``__after_compose.py`` via the present services' source-path labels. We
    still guard defensively.

    We inject the streaming-replication settings through the existing
    ``POSTGRES_CONFIG`` mechanism (consumed by postgres/run.sh) rather than
    editing postgres/config statically, so a project without Barman keeps the
    stock postgres configuration untouched. The ``environment`` block wins over
    the value coming from the settings env_file.
    """
    if not _truthy(settings.get("RUN_BARMAN", "0")):
        return
    if "postgres" not in yml.get("services", {}):
        return

    # The replication slot retains all WAL the streamer hasn't received yet,
    # so wal_keep_size is unnecessary. Avoiding it also keeps this compatible
    # with PG <= 12 where the parameter is named wal_keep_segments instead.
    params = [
        "wal_level=replica",
        "max_wal_senders=10",
        "max_replication_slots=10",
    ]

    # Cap how much WAL the slot may retain so a long barman outage cannot fill
    # the primary's disk. 0 / empty means unlimited (postgres default).
    # max_slot_wal_keep_size only exists on PG >= 13 - injecting it on an older
    # server would make postgres refuse to start, so gate on the version.
    try:
        pg_major = int(
            str(settings.get("POSTGRES_VERSION", "17")).split(".")[0]
        )
    except (TypeError, ValueError):
        pg_major = 17
    cap = str(settings.get("BARMAN_MAX_SLOT_WAL_KEEP_SIZE", "") or "").strip()
    if cap and cap != "0" and pg_major >= 13:
        params.append(f"max_slot_wal_keep_size={cap}")

    wal_config = ";".join(params)

    pg = yml["services"]["postgres"]
    env = pg.setdefault("environment", {})
    # docker-compose config normalises environment to a mapping at this stage.
    if isinstance(env, list):
        env_map = {}
        for item in env:
            k, _, v = str(item).partition("=")
            env_map[k] = v
        env = env_map
        pg["environment"] = env

    existing = (
        env.get("POSTGRES_CONFIG") or settings.get("POSTGRES_CONFIG") or ""
    ).strip()
    existing = existing.rstrip(";").strip()
    env["POSTGRES_CONFIG"] = ";".join(filter(None, [existing, wal_config]))
