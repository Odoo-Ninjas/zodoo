"""Local audit trail for ``odoo update`` and ``odoo restart``.

Every run appends one JSON line to ``<project>/.odoo-commands.log``. The file
lives next to ``update.log`` so it is the same file on the host and inside the
container (``/opt/src``). It is runtime data of one checkout: the gitignore
rule is ensured *before* the first write, so the file can never show up as
untracked.

What is recorded: start time, duration, command, arguments, project name,
whether it ran in a container, whether it was invoked from another command,
result, exit code and exception type. What is not recorded: environment,
settings, user or host names and exception messages (they may carry
connection strings or other data). Option values whose name looks like a
secret and credentials in URLs are masked.

Writing the log is best effort - a failure prints a warning and never changes
the outcome of the command itself.
"""

import functools
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import click

LOG_FILENAME = ".odoo-commands.log"
GITIGNORE_RULE = "/" + LOG_FILENAME
MASK = "***"

_SENSITIVE_NAME = re.compile(
    r"pass|pwd|token|secret|key|credential|auth", re.IGNORECASE
)
_URL_USERINFO = re.compile(r"(?P<scheme>[a-zA-Z][\w+.-]*://)[^/@\s]+@")

# Nesting depth of logged commands in this process, so that an update
# triggered from inside another command (ctx.invoke) is marked as nested.
_depth = 0


def sanitize_argv(argv):
    """Return a copy of ``argv`` with secret-looking values masked."""
    result = []
    mask_next = False
    for arg in argv:
        arg = str(arg)
        if mask_next:
            result.append(MASK)
            mask_next = False
            continue
        if arg.startswith("-") and "=" in arg:
            name, _value = arg.split("=", 1)
            if _SENSITIVE_NAME.search(name):
                result.append(f"{name}={MASK}")
                continue
        elif arg.startswith("-") and _SENSITIVE_NAME.search(arg):
            mask_next = True
        result.append(_URL_USERINFO.sub(rf"\g<scheme>{MASK}@", arg))
    return result


def _exit_code(exc):
    code = getattr(exc, "code", None)
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1


def _classify(exc):
    """Map an exception leaving the command to (result, exit_code, type)."""
    if exc is None:
        return "ok", 0, None
    if isinstance(exc, click.exceptions.Exit):
        code = exc.exit_code
        return ("ok" if code == 0 else "error"), code, None
    if isinstance(exc, SystemExit):
        code = _exit_code(exc)
        return ("ok" if code == 0 else "error"), code, None
    if isinstance(exc, (KeyboardInterrupt, click.exceptions.Abort)):
        return "aborted", 130, type(exc).__name__
    return "error", 1, type(exc).__name__


def _in_container():
    return Path("/.dockerenv").exists()


def _current_config():
    from .click_config import Config

    ctx = click.get_current_context(silent=True)
    return ctx.find_object(Config) if ctx else None


def _log_directory():
    from .odoo_config import customs_dir

    return customs_dir()


def write_entry(entry, directory=None, config=None):
    """Append ``entry`` to the log in ``directory`` (default: project dir)."""
    from .tools import __assure_gitignore, __try_to_set_owner

    if directory is None:
        directory = _log_directory()
    if not directory:
        return None
    directory = Path(directory)
    logfile = directory / LOG_FILENAME
    __assure_gitignore(directory / ".gitignore", GITIGNORE_RULE)
    is_new = not logfile.exists()
    with logfile.open("a", encoding="utf8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    owner_uid = getattr(config, "owner_uid", None) if config else None
    if is_new and owner_uid:
        __try_to_set_owner(int(owner_uid), logfile, abort_if_failed=False)
    return logfile


def logged_command(name):
    """Decorator for a click command callback: log every run of it."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            global _depth
            nested = _depth > 0
            started = datetime.now().astimezone()
            t0 = time.monotonic()
            exc = None
            _depth += 1
            try:
                return func(*args, **kwargs)
            except BaseException as ex:
                exc = ex
                raise
            finally:
                _depth -= 1
                result, exit_code, error_type = _classify(exc)
                entry = {
                    "ts": started.isoformat(timespec="seconds"),
                    "command": name,
                    "argv": sanitize_argv(sys.argv[1:]),
                    "project": None,
                    "in_container": _in_container(),
                    "nested": nested,
                    "result": result,
                    "exit_code": exit_code,
                    "error_type": error_type,
                    "duration_s": round(time.monotonic() - t0, 1),
                }
                try:
                    config = _current_config()
                    entry["project"] = getattr(config, "project_name", None)
                    write_entry(entry, config=config)
                except Exception as ex:  # never break the command itself
                    click.secho(
                        f"WARNING: could not write {LOG_FILENAME}: "
                        f"{type(ex).__name__}",
                        fg="yellow",
                        err=True,
                    )

        wrapper.logged_command = name
        return wrapper

    return decorator
