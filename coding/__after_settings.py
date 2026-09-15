import secrets
import string


def generate_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def after_settings(settings, config):
    # Same rule as the dashboard and the log view: a real instance gets a
    # password of its own, DEVMODE stays open. The editor is a shell on this
    # machine -- an instance that reaches the internet must not serve it
    # without asking.
    if not settings.get("CODING_PASSWORD") and settings["DEVMODE"] != "1":
        settings["CODING_PASSWORD"] = generate_password(12)
