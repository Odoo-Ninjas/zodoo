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
