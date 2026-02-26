def after_settings(settings, config):
    customs_dir = config.WORKING_DIR
    settings["HOST_SRC_PATH"] = customs_dir
