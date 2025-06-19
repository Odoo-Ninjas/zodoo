#!/usr/bin/env bash
import traceback
import time
import os
import sys
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
print("Watching file {}".format(DEBUGGER_WATCH))
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


class Debugger(object):
    def __init__(self, sync_common_modules, wait_for_remote, remote_debugging, loglevel):
        self.odoolib_path = Path(os.environ["ODOOLIB"])
        self.sync_common_modules = sync_common_modules
        self.first_run = True
        self.last_unit_test = None
        self.wait_for_remote = wait_for_remote
        if wait_for_remote:
            remote_debugging = True
        self.remote_debugging = remote_debugging
        self.loglevel = loglevel

    def execpy(self, cmd):
        os.chdir(self.odoolib_path)
        if not cmd[0].startswith("/"):
            cmd = ["python3"] + cmd
        proc = subprocess.run(cmd, cwd=self.odoolib_path)  # exitcode
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
        # print(f"executing: {cmd}")
        self.execpy(cmd)

    def action_update_module(self, cmd, module):
        kill_odoo()
        PARAMS_CONST = ["--log=debug"]
        if config["DEVMODE"] == "1" and config.get("NO_QWEB_DELETE", "") != "1":
            PARAMS_CONST += ["--delete-qweb"]
        if cmd == "update_module":
            PARAMS_CONST += ["--no-tests"]
        if self.execpy(
            [
                os.environ['WODOO_PYTHON'],
                "/odoolib/update_modules.py",
                module,
            ]
            + PARAMS_CONST
        ):
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
        self.execpy(
            [
                os.environ['WODOO_PYTHON'],
                "unit_test.py",
                self.last_unit_test,
            ]
            + args
        )

    def action_export_lang(self, lang, module):
        kill_odoo()
        subprocess.call(["/usr/bin/reset"])
        self.execpy([os.environ['WODOO_PYTHON'], "export_i18n.py", lang, module])
        self.trigger_restart()

    def action_import_lang(self, lang, filepath):
        kill_odoo()
        self.execpy(["/usr/bin/reset"])
        if self.execpy([os.environ['WODOO_PYTHON'], "import_i18n.py", lang, filepath]):
            self.trigger_restart()

    def trigger_restart(self):
        DEBUGGER_WATCH.write_text("debug")

    def endless_loop(self):
        t = threading.Thread(target=watch_file_and_kill)
        t.daemon = True
        t.start()

        action = None

        while True:
            try:
                if not self.first_run and not DEBUGGER_WATCH.exists():
                    time.sleep(0.2)
                    continue
                os.chdir("/opt/src")

                if not self.first_run:
                    content = DEBUGGER_WATCH.read_text()
                    DEBUGGER_WATCH.unlink()
                    action = content.split(":")

                if self.first_run or action[0] in ["debug", "quick_restart"]:
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
                    thread1 = threading.Thread(target=self.action_last_unittest)
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

                self.first_run = False

            except Exception:
                msg = traceback.format_exc()
                print(msg)
                time.sleep(1)


@click.command(name="debug")
@click.option(
    "-s",
    "--sync-common-modules",
    is_flag=True,
    help="If set, then common modules from framework are copied to addons_tools",
)
@click.option("-q", "--debug-queuejobs", is_flag=True)
@click.option("-w", "--wait-for-remote", is_flag=True)
@click.option("-r", "--remote-debugging", is_flag=True)
@click.option("-W", "--web-workers", default=2)
@click.option("-p", "--profile", is_flag=True)
@click.option("-l", "--loglevel", default="info")
def command_debug(
    sync_common_modules,
    debug_queuejobs,
    wait_for_remote,
    remote_debugging,
    web_workers,
    profile,
    loglevel,
):
    global profiling
    if debug_queuejobs:
        os.environ["TEST_QUEUE_JOB_NO_DELAY"] = "1"
    if remote_debugging:
        os.environ["PYTHONBREAKPOINT"] = "debugpy.set_trace"
    else:
        os.environ["PYTHONBREAKPOINT"] = "pudb.set_trace"
    os.environ["ODOO_WORKERS_WEB"] = str(web_workers)
    profiling = profile
    if profile:
        click.secho("Profiling enabled - set @profile at defs to see the metrics", fg="green")
    prepare_run()

    Debugger(
        sync_common_modules=sync_common_modules,
        wait_for_remote=wait_for_remote,
        remote_debugging=remote_debugging,
        loglevel=loglevel,
    ).endless_loop()


if __name__ == "__main__":
    command_debug()
