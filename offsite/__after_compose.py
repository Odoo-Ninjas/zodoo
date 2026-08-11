def after_compose(config, settings, yml, globals):
    """Das lokale Offsite-Ziel einhaengen, falls eines konfiguriert ist.

    Warum nicht einfach fest in der docker-compose.yml: ein Bind-Mount mit
    leerer Quelle laesst `docker compose config` scheitern, und die meisten
    Projekte haben gar kein lokales Ziel (sie sichern per ssh oder gar nicht).
    Deshalb wird der Mount hier nur dann ergaenzt, wenn OFFSITE_LOCAL_DIR
    gesetzt ist.

    Der Pfad ist im Container derselbe wie auf dem Host. Das ist Absicht:
    OFFSITE_REPO steht in den Settings und wird sowohl vom Container benutzt
    als auch von Menschen gelesen -- zwei verschiedene Schreibweisen fuer
    dasselbe Ziel waeren eine Fehlerquelle beim Wiederherstellen, also genau
    in dem Moment, in dem niemand Zeit zum Raetseln hat.
    """
    service = yml.get("services", {}).get("offsite")
    if not service:
        return
    local_dir = (settings.get("OFFSITE_LOCAL_DIR") or "").strip()
    if not local_dir:
        return
    service.setdefault("volumes", []).append(f"{local_dir}:{local_dir}")
