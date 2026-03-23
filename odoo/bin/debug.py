#!/usr/bin/env bash
import traceback
import time
import os
import threading
import subprocess
import click
from pathlib import Path
import tools
from tools import prepare_run
from tools import sane_tty
from tools import get_config_file  # NOQA
from wodoo.odoo_config import current_version  # NOQA
from wodoo.odoo_config import get_settings  # NOQA
from wodoo.module_tools import update_view_in_db  # NOQA
from wodoo.module_tools import Modules  # NOQA
from tools import kill_odoo

config = get_settings()
DEBUGGER_WATCH = Path(os.environ["DEBUGGER_WATCH"])
# print("Watching file {}".format(DEBUGGER_WATCH))
customs_dir = Path(os.environ["CUSTOMS_DIR"])
profiling = False

import os
import platform


def clear_terminal():
    command = "cls" if platform.system() == "Windows" else "clear"
    os.system(command)


def watch_file_and_kill():
    while True:
        time.sleep(0.2)

        # force odoo profiler to output profiling info
        if profiling:
            pidfile = Path(tools.pidfile)
            if pidfile.exists():
                os.system(f"watch -n0.1 pkill -3 -f python3")


class Debugger:
    def __init__(
        self,
        sync_common_modules,
        wait_for_remote,
        remote_debugging,
        loglevel,
        enable_queuejobs,
        one_action,
    ):
        self.odoolib_path = Path(os.environ["ODOOLIB"])
        self.sync_common_modules = sync_common_modules
        self.first_run = True
        self.enable_queuejobs = enable_queuejobs
        self.last_unit_test = None
        self.wait_for_remote = wait_for_remote
        if wait_for_remote:
            remote_debugging = True
        self.remote_debugging = remote_debugging
        self.loglevel = loglevel
        self.one_action = one_action

    def execpy(self, cmd):
        os.chdir(self.odoolib_path)
        if not cmd[0].startswith("/"):
            cmd = ["python3"] + cmd
        env2 = os.environ.copy()
        env2["ODOO_DEBUGGING"] = "1"
        # Don't set GEVENT_SUPPORT=True - it breaks breakpoints.
        # Instead suppress the pydevd warning message that spams the log.
        env2["GEVENT_SUPPORT_NOT_SET_MSG"] = ""
        proc = subprocess.run(cmd, cwd=self.odoolib_path, env=env2)  # exitcode
        res = proc.returncode == 0
        sane_tty()
        return res

    def action_debug(self):
        self.first_run = False

        if os.getenv("ODOO_PYTHON_DEBUG_PORT", ""):
            print(
                "PTHON REMOTE DEBUGGER PORT: {}".format(
                    os.environ["ODOO_PYTHON_DEBUG_PORT"]
                )
            )
        print(f"Using tracing: {os.getenv('PYTHONBREAKPOINT')}")
        print(
            f"remote debugg: {self.remote_debugging}, waiting for debugger: {self.wait_for_remote}"
        )

        cmd = [os.environ["WODOO_PYTHON"], "run_debug.py"]
        if self.remote_debugging:
            cmd += ["--remote-debug"]
        if self.wait_for_remote:
            cmd += ["--wait-for-remote"]
        if self.enable_queuejobs:
            cmd += ["--enable-queuejobs"]
        # print(f"executing: {cmd}")
        self.execpy(cmd)

    def action_update_module(self, cmd, module):
        kill_odoo()
        click.secho("UPDATE STARTED - please wait ...", fg="green")
        PARAMS_CONST = [f"--log={self.loglevel.lower()}"]
        if (
            config["DEVMODE"] == "1"
            and config.get("NO_QWEB_DELETE", "") != "1"
        ):
            PARAMS_CONST += ["--delete-qweb"]
        if cmd == "update_module":
            PARAMS_CONST += ["--no-tests"]
        res = self.execpy(
            [
                os.environ["WODOO_PYTHON"],
                "/odoolib/update_modules.py",
                module,
            ]
            + PARAMS_CONST
        )
        if res:
            if res:
                click.secho("Odoo update Success", fg="green")
            else:
                click.secho("Odoo update failed", fg="red")
            self.trigger_restart()

    def action_last_unittest(self):
        if not self.last_unit_test:
            self.trigger_restart()
        self.action_unittest(self.last_unit_test)

    def action_unittest(self, filepath):
        kill_odoo()
        subprocess.call(["/usr/bin/reset"])
        self.last_unit_test = str(customs_dir / filepath)
        print(f"Running unit testt: {self.last_unit_test}")
        args = []
        # if self.loglevel:
        #     args += ["--log-level", self.loglevel]
        if self.wait_for_remote:
            args += ["--wait-for-remote"]
            print(
                f"Please connect your external debugger to: {os.environ['ODOO_PYTHON_DEBUG_PORT']}"
            )
        res = self.execpy(
            [
                os.environ["WODOO_PYTHON"],
                "unit_test.py",
                self.last_unit_test,
            ]
            + args
        )
        if res:
            click.secho(
                "UNITTEST: PASSED (exit code 0)", fg="green", bold=True
            )
        else:
            click.secho(
                "UNITTEST: FAILED (exit code != 0)", fg="red", bold=True
            )

    def action_export_lang(self, lang, module):
        kill_odoo()
        subprocess.call(["/usr/bin/reset"])
        self.execpy(
            [os.environ["WODOO_PYTHON"], "export_i18n.py", lang, module]
        )
        self.trigger_restart()

    def action_import_lang(self, lang, filepath):
        kill_odoo()
        self.execpy(["/usr/bin/reset"])
        if self.execpy(
            [os.environ["WODOO_PYTHON"], "import_i18n.py", lang, filepath]
        ):
            self.trigger_restart()

    def trigger_restart(self):
        DEBUGGER_WATCH.write_text("debug")

    def endless_loop(self):
        t = threading.Thread(target=watch_file_and_kill)
        t.daemon = True
        t.start()

        action = None
        if self.one_action:
            self.first_run = False
            action = self.one_action.split(":")
            print(f"One time action is: {action}")

        while True:
            try:
                if (
                    not self.first_run
                    and not DEBUGGER_WATCH.exists()
                    and action is None
                ):
                    time.sleep(0.2)
                    continue
                os.chdir("/opt/src")

                if (
                    not self.first_run
                    and DEBUGGER_WATCH.exists()
                    and not self.one_action
                ):
                    content = DEBUGGER_WATCH.read_text()
                    DEBUGGER_WATCH.unlink()
                    action = content.split(":")

                if self.first_run or (
                    action and action[0] in ["debug", "quick_restart"]
                ):
                    kill_odoo()
                    thread1 = threading.Thread(target=self.action_debug)
                    thread1.daemon = True
                    thread1.start()

                if not action:
                    pass
                elif action[0] in ["restart"]:
                    kill_odoo()
                    self.execpy(["/usr/bin/reset"])
                    self.trigger_restart()

                elif action[0] == "update_view_in_db":
                    filepath = Path(action[1])
                    lineno = int(action[2])
                    update_view_in_db(filepath, lineno)

                elif action[0] in ["update_module", "update_module_full"]:
                    kill_odoo()
                    thread1 = threading.Thread(
                        target=self.action_update_module,
                        kwargs=dict(cmd=action[0], module=action[1]),
                    )
                    thread1.daemon = True
                    thread1.start()

                elif action[0] in ["last_unit_test"]:
                    kill_odoo()
                    thread1 = threading.Thread(
                        target=self.action_last_unittest
                    )
                    thread1.daemon = True
                    thread1.start()

                elif action[0] in ["unit_test"]:
                    kill_odoo()
                    thread1 = threading.Thread(
                        target=self.action_unittest,
                        kwargs=dict(
                            filepath=action[1],
                        ),
                    )
                    thread1.daemon = True
                    thread1.start()

                elif action[0] == "export_i18n":
                    kill_odoo()
                    thread1 = threading.Thread(
                        target=self.action_export_lang,
                        kwargs=dict(lang=action[1], module=action[2]),
                    )
                    thread1.daemon = True
                    thread1.start()

                elif action[0] == "import_i18n":
                    kill_odoo()
                    thread1 = threading.Thread(
                        target=self.action_import_lang,
                        kwargs=dict(
                            lang=action[1],
                            filepath=action[2],
                        ),
                    )
                    thread1.daemon = True
                    thread1.start()

                action = None
                self.first_run = False

            except Exception:
                if self.one_action:
                    raise
                msg = traceback.format_exc()
                print(msg)
                time.sleep(1)
        print("exited debugging endless loop")


@click.command(name="debug")
@click.option(
    "-s",
    "--sync-common-modules",
    is_flag=True,
    help="If set, then common modules from framework are copied to addons_tools",
)
@click.option("-q", "--debug-queuejobs", is_flag=True)
@click.option("-qe", "--enable-queuejobs", is_flag=True)
@click.option("-w", "--wait-for-remote", is_flag=True)
@click.option("-r", "--remote-debugging", is_flag=True)
@click.option("-W", "--web-workers", default=0)
@click.option("-p", "--profile", is_flag=True)
@click.option("-l", "--loglevel", default="info")
@click.option("--one-action")
def command_debug(
    sync_common_modules,
    debug_queuejobs,
    wait_for_remote,
    remote_debugging,
    web_workers,
    profile,
    loglevel,
    enable_queuejobs,
    one_action,
):
    global profiling
    if debug_queuejobs:
        os.environ["TEST_QUEUE_JOB_NO_DELAY"] = "1"
    if remote_debugging:
        os.environ["PYTHONBREAKPOINT"] = "debugpy.set_trace"
    else:
        os.environ["PYTHONBREAKPOINT"] = "pudb.set_trace"

    if enable_queuejobs:
        os.environ["ENABLE_QUEUEJOBS"] = "1"
    os.environ["ODOO_WORKERS_WEB"] = str(web_workers)
    profiling = profile
    if profile:
        click.secho(
            "Profiling enabled - set @profile at defs to see the metrics",
            fg="green",
        )
    prepare_run()

    os.environ["WODOO_LOGLEVEL"] = loglevel

    Debugger(
        sync_common_modules=sync_common_modules,
        wait_for_remote=wait_for_remote,
        remote_debugging=remote_debugging,
        loglevel=loglevel,
        enable_queuejobs=enable_queuejobs,
        one_action=one_action,
    ).endless_loop()


if __name__ == "__main__":
    command_debug()
