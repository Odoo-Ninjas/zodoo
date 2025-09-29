import string
import secrets


def generate_password(length=12):
    # Characters: letters, digits, and punctuation
    alphabet = string.ascii_letters + string.digits
    # Use secrets.choice for cryptographically strong randomness
    return "".join(secrets.choice(alphabet) for _ in range(length))


def after_settings(settings, config):
    if not settings["CONSOLE_PASSWORD"] and settings["DEVMODE"] != "1":
        settings["CONSOLE_PASSWORD"] = generate_password(12)
