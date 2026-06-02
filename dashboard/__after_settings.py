import secrets
import string


def generate_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def after_settings(settings, config):
    # Mirror logsio_web: auto-generate the dashboard gate password on real
    # instances, but leave it empty in DEVMODE (gate then stays open).
    if not settings.get("DASHBOARD_PASSWORD") and settings["DEVMODE"] != "1":
        settings["DASHBOARD_PASSWORD"] = generate_password(12)
