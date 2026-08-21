def after_compose(config, settings, yml, globals):
    """Mount the local offsite target, if one is configured.

    Why not simply hard-code it in docker-compose.yml: a bind mount with an
    empty source makes `docker compose config` fail, and most projects have no
    local target at all (they back up over ssh, or not at all). So the mount is
    only added here when OFFSITE_LOCAL_DIR is set.

    The path inside the container is the same as on the host. That is
    deliberate: OFFSITE_REPO lives in the settings and is used by the container
    as well as read by humans -- two different spellings for the same target
    would be a source of mistakes during a restore, i.e. at exactly the moment
    when nobody has time to puzzle it out.
    """
    service = yml.get("services", {}).get("offsite")
    if not service:
        return
    local_dir = (settings.get("OFFSITE_LOCAL_DIR") or "").strip()
    if not local_dir:
        return
    service.setdefault("volumes", []).append(f"{local_dir}:{local_dir}")
