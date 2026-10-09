"""Ownership checks for the per-role odoo pidfiles (/tmp/odoo.<role>.pid).

Kept free of zodoo imports so it can be unit-tested outside the container.

/tmp is not a tmpfs, so a pidfile survives a container restart and then
names whatever process got that pid in the new container. PIDs are handed
out almost in the same order on every start, so that is often a sibling
role's sh/sudo/odoo-bin. Signalling it orphaned the sibling's odoo-bin (its
wrapper returned rc=0 while the server kept the port) and the sibling's
respawns then failed with "Address already in use" forever.
"""

from pathlib import Path

PROC = Path("/proc")


def read_pid(pidfile):
    try:
        return int(Path(pidfile).read_text().strip())
    except (OSError, ValueError):
        return None


def pid_is_role_odoo(pid, pidfile, proc=PROC):
    """True if `pid` is a process started with exactly `--pidfile=<pidfile>`.

    That argument is unique per role, so a recycled pid that now belongs to
    another role (or to anything else) is not mistaken for ours.
    """
    if not (proc / "self").exists():
        # No procfs to check against: keep the old, unchecked behaviour.
        return True
    try:
        cmdline = (proc / str(pid) / "cmdline").read_bytes()
    except OSError:
        return False
    return f"--pidfile={pidfile}".encode() in cmdline.split(b"\0")


def owned_pid(pidfile, proc=PROC):
    """The pid in `pidfile` if it is still our odoo-bin, else None."""
    pid = read_pid(pidfile)
    if pid is None or not pid_is_role_odoo(pid, pidfile, proc=proc):
        return None
    return pid


def remove_unless_alive(pidfile, proc=PROC):
    """Drop the pidfile unless its odoo-bin is still running.

    The wrapper can return while odoo-bin keeps running (its sh got
    signalled). The pidfile must stay then, so the next kill_odoo() of the
    role still finds the server and stops it.
    """
    if owned_pid(pidfile, proc=proc) is not None:
        return False
    try:
        Path(pidfile).unlink()
    except FileNotFoundError:
        pass
    return True
