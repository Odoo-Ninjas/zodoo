"""`sudo_odoo_cmd` lives in its own module so it can be unit-tested
without importing the full tools.py (which has heavy module-level
side effects like odoo_config.get_settings()).
"""

import os
import pwd


def should_wrap_for_odoo(odoo_user, sudo_cmd_env, current_euid):
    """Pure logic extracted so tests can exercise every branch.

    Wrap only when:
      - ODOO_SUDO_CMD=1, and
      - we're NOT already the odoo user.

    The odoo user is not in /etc/sudoers; wrapping while already
    running as odoo fails with "odoo is not in the sudoers file".
    """
    if sudo_cmd_env != "1":
        return False
    try:
        current_user = pwd.getpwuid(current_euid).pw_name
    except KeyError:
        # Unknown uid — safer to wrap (e.g. uid 0 = root → wrap).
        return True
    return current_user != odoo_user


def sudo_odoo_cmd(cmd, odoo_user=None):
    """Prepend sudo -E -H -u <odoo_user> if needed (see should_wrap_for_odoo)."""
    if odoo_user is None:
        odoo_user = os.environ["ODOO_USER"]
    if should_wrap_for_odoo(
        odoo_user, os.getenv("ODOO_SUDO_CMD"), os.geteuid()
    ):
        return ["/usr/bin/sudo", "-E", "-H", "-u", odoo_user] + list(cmd)
    return list(cmd)
