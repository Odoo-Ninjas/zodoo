#!/usr/bin/env zodoo_python
from datetime import datetime
import json
import os
import sys
import click
from zodoo.module_tools import Module
from zodoo.odoo_config import current_version
from pathlib import Path
from tools import exec_odoo
from tools import prepare_run
import argparse

parser = argparse.ArgumentParser(description="Unittest.")
parser.add_argument("--log-level")
parser.add_argument("--not-interactive", action="store_true")
parser.add_argument("--remote-debug", action="store_true")
parser.add_argument("--wait-for-remote", action="store_true")
parser.add_argument("--resultsfile")
parser.add_argument("test_file")
parser.set_defaults(log_level="error")
args = parser.parse_args()
logfile = Path("/opt/src/.unittest.log")

os.environ["TEST_QUEUE_JOB_NO_DELAY"] = "1"

if not args.not_interactive:
    os.environ["PYTHONBREAKPOINT"] = "pudb.set_trace"
else:
    os.environ["PYTHONBREAKPOINT"] = "0"

prepare_run()


def _imported_test_modules(tests_dir):
    """Names of the test submodules that odoo will actually collect.

    --test-file only looks at the modules imported into the addon's ``tests``
    package (loader._get_tests_modules does inspect.getmembers(..., ismodule)).
    A test file that nobody imports in ``tests/__init__.py`` is skipped without
    a word, and the run then reports success although nothing ran.
    """
    import ast

    initfile = tests_dir / "__init__.py"
    if not initfile.exists():
        return None
    try:
        tree = ast.parse(initfile.read_text())
    except SyntaxError:
        return None
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            if node.module:
                names.add(node.module.split(".")[0])
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[-1])
    return names


runs = []
capture_output = os.getenv("CAPTURE_UNITTEST_OUTPUT") == "1"

ran_files = []
for filepath in args.test_file.split(","):
    started = datetime.now()
    cmd = [
        "--stop-after-init",
        f"--log-level={args.log_level}",
    ]
    filepath = Path(filepath.strip())
    if not str(filepath).startswith("/"):
        filepath = Path(os.environ["CUSTOMS_DIR"]) / filepath
    if not filepath.exists():
        click.secho(f"File not found: {filepath}", fg="red")
        sys.exit(-1)
    os.chdir("/opt/src")
    module = Module(filepath)
    collectable = _imported_test_modules(filepath.parent)
    if collectable is not None and filepath.stem not in collectable:
        msg = (
            f"{filepath.stem} is not imported in {filepath.parent}/__init__.py."
            " Odoo would skip this file silently and the run would look green."
            f" Add 'from . import {filepath.stem}' there."
        )
        click.secho(msg, fg="red", bold=True)
        runs.append(
            {
                "path": str(filepath.relative_to("/opt/src")),
                "duration": (datetime.now() - started).total_seconds(),
                "output": msg,
                "rc": 2,
            }
        )
        continue
    ran_files.append(filepath)
    cmd += [
        f"--test-file={filepath.resolve().absolute()}",
        # let the run say what it did: config_unittest sets a :WARN handler,
        # which hides both "running tests ..." and the result summary, so a
        # run that executed nothing looks exactly like a successful one
        "--log-handler=odoo.service.server:INFO",
        "--log-handler=odoo.tests:INFO",
        "--log-handler=odoo.tests.result:INFO",
    ]
    if current_version() <= 11.0:
        cmd += [
            "--test-report-directory=/tmp",
        ]
    rc, output = exec_odoo(
        "config_unittest",
        remote_debug="--remote-debug" in sys.argv,
        wait_for_remote="--wait-for-remote" in sys.argv,
        capture_output=capture_output,
        *cmd,
    )
    runs.append(
        {
            "path": str(filepath.relative_to("/opt/src")),
            "duration": (datetime.now() - started).total_seconds(),
            "output": output,
            "rc": rc,
        }
    )

if args.resultsfile:
    output = Path("/opt/out_dir") / args.resultsfile
    output.write_text(json.dumps(runs, indent=4))

if any(x["rc"] for x in runs):
    rc = -1

ran_files = "\n".join(map(str, ran_files))
good = r"""
     _    _ _   _            _                                      _
    / \  | | | | |_ ___  ___| |_ ___   _ __   __ _ ___ ___  ___  __| |
   / _ \ | | | | __/ _ \/ __| __/ __| | '_ \ / _` / __/ __|/ _ \/ _` |
  / ___ \| | | | ||  __/\__ \ |_\__ \ | |_) | (_| \__ \__ \  __/ (_| |
 /_/   \_\_|_|  \__\___||___/\__|___/ | .__/ \__,_|___/___/\___|\__,_|
                                      |_|
"""
if not rc:
    text = good

    click.secho(text, fg="green", bold=True)
    logfile.write_text(f"{good}\n{ran_files}")
else:
    text = []
    for entry in runs:
        text.append(
            "------------------------------------------------------------------"
        )
        text.append(
            f"File: {entry['path']} failed in {entry['duration']} seconds"
        )
        text.append(
            "------------------------------------------------------------------"
        )
        text.append(f"{entry['output']}")
        text.append("\n\n")

    logfile.write_text("\n".join(text))
sys.exit(rc)
