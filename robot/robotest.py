# pylint: disable=import-outside-toplevel
import click
import sys
import uuid
import selenium
import base64
from copy import deepcopy
import shutil
import os
import arrow
import subprocess
import json
from pathlib import Path
import threading
import logging
import threading
from tabulate import tabulate
from robot import rebot, run
from dotenv import load_dotenv


FORMAT = "[%(levelname)s] %(name) -12s %(asctime)s %(message)s"
logging.basicConfig(format=FORMAT)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger("")  # root handler

Browsers = {
    "chrome": {
        "driver": "Chrome",
        "alias": "chrome",
    },
    "firefox": {
        "driver": "Firefox",
        "alias": "firefox",
    },
}

import socket
import time


def wait_for_port(host, port, timeout=300, interval=2):
    """Wait until a specific port on a host is available."""
    start_time = time.time()

    while time.time() - start_time < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex((host, port)) == 0:
                print(f"✅ Port {port} on {host} is now available!")
                return True
        print(f"⏳ Waiting for port {port} on {host}...")
        time.sleep(interval)

    print(
        f"❌ Timeout: Port {port} on {host} did not become available in {timeout} seconds."
    )
    return False


def safe_filename(name):
    for c in ":_- \\/!?#$%&*":
        name = name.replace(c, "_")
    return name


def safe_avg(values):
    if not values:
        return 0
    values = list((x or 0) for x in values)
    S = float(sum(values))
    return S / float(len(values))


def _run_test(
    test_file,
    output_dir,
    browser,
    parallel=1,
    tags=None,
    **run_parameters,
):
    assert browser in Browsers, f"Invalid browser {browser} - not in {Browsers.keys()}"
    browser = Browsers[browser]

    results = [
        {
            "ok": None,
            "duration": None,
        }
        for _ in range(parallel)
    ]
    threads = []

    def run_robot(index):
        effective_variables = {}
        effective_variables["TEST_RUN_INDEX"] = index

        started = arrow.utcnow()
        effective_output_dir = output_dir / str(index)
        effective_output_dir.mkdir(parents=True, exist_ok=True)
        effective_test_file = test_file

        vars_command = []
        for k, v in effective_variables.items():
            vars_command.append("--variable")
            if ":" in k:
                raise Exception(f"invalid token in {k}")
            vars_command.append(f"{k}:{v}")

        def _get_cmd(dryrun):
            cmd = (
                [
                    "/usr/local/bin/robot",
                    "-X",  # exit on failure
                ]
                + vars_command
                + [
                    "--outputdir",
                    effective_output_dir,
                ]
            )
            if dryrun:
                cmd += ["--dryrun"]
            if tags:
                for tag in tags.split(","):
                    tag = tag.strip()
                    cmd += ["--include", tag]
            cmd += [effective_test_file]
            return cmd

        cmd = _get_cmd(dryrun=False)

        try:
            CUSTOMS_DIR = os.environ["CUSTOMS_DIR"]
            subprocess.run(cmd, check=True, encoding="utf8", cwd=CUSTOMS_DIR)
        except subprocess.CalledProcessError:
            success = False
        else:
            success = True

        results[index]["ok"] = success
        results[index]["duration"] = (arrow.utcnow() - started).total_seconds()

    if parallel == 1:
        run_robot(0)
    else:
        logger.info("Preparing threads")
        for i in range(parallel):
            t = threading.Thread(target=run_robot, args=((i,)))
            t.daemon = True
            threads.append(t)
    [x.start() for x in threads]  # pylint: disable=W0106
    [x.join() for x in threads]  # pylint: disable=W0106

    success_rate = (
        not results and 0 or len([x for x in results if x["ok"]]) / len(results) * 100
    )

    durations = list(map(lambda x: x["duration"], results))
    min_duration = durations and min(durations) or 0
    max_duration = durations and max(durations) or 0
    avg_duration = safe_avg(durations)

    any_failed = False
    for result in results:
        if not result["ok"]:
            any_failed = True

    return {
        "all_ok": not any_failed,
        "details": results,
        "count": len(list(filter(lambda x: not x is None, results))),
        "succes_rate": success_rate,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "avg_duration": avg_duration,
    }


def _run_tests(params, test_files, output_dir):
    # init vars
    test_results = []

    # iterate robot files and run tests
    for test_file in test_files:
        output_sub_dir = output_dir / f"{test_file.stem}_p{params['parallel']}"

        # build robot command: pass all params from data as
        # parameters to the command call
        logger.info(
            ("Running test %s " "using output dir %s"), test_file.name, output_sub_dir
        )
        output_sub_dir.mkdir(parents=True, exist_ok=True)

        try:
            run_test_result = _run_test(
                test_file=test_file, output_dir=output_sub_dir, **params
            )

        except Exception as ex:  # pylint: disable=broad-except
            logger.exception(ex)
            run_test_result = {
                "all_ok": False,
            }

        run_test_result["name"] = test_file.stem
        test_results.append(run_test_result)
        logger.info(
            ("Test finished in %s " "seconds."), run_test_result.get("duration")
        )
        collect_all_reports(test_file, output_sub_dir)

    return test_results


def collect_all_reports(test_file, parent_dir):
    """
    Directory contains directories which are numbers that indicate the amount of
    workers.
    """

    files = list(
        map(
            Path,
            subprocess.check_output(
                ["find", parent_dir, "-type", "f", "-name", "output.xml"],
                encoding="utf8",
            )
            .strip()
            .splitlines(),
        )
    )
    name = test_file.name.replace(".robot", "")
    with open(parent_dir / "output.txt", "w") as stdout:
        os.chdir(parent_dir)
        rebot(*files, name=name, log=None, stdout=stdout)
        report_html = Path("/opt/robot/report.html")
        if report_html.exists():
            shutil.move("/opt/robot/report.html", parent_dir)


def run_tests(params, test_files, token, results_file, debug):
    """
    Call this with json request with following data:
    - params: dict passed to robottest.sh
    - archive: robot tests in zip file format
    Expects tar archive of tests files to be executed.


    """
    # setup workspace folders
    logger.info(f"Starting test with params:\n{json.dumps(params, indent=4)}")
    output_dir = Path(os.environ["OUTPUT_DIR"])
    token_dir = output_dir / token
    _clean_dir(token_dir)
    src_dir = Path("/opt/src")
    params["TOKEN"] = token

    if os.getenv("ROBO_PARAMS_FILE"):
        path_robot_params = Path(os.getenv("ROBO_PARAMS_FILE"))
        path_robot_params.write_text(json.dumps(params))

    test_results = []
    test_results += _run_tests(
        params,
        map(lambda file: src_dir / file, test_files),
        token_dir,
    )

    results_file = output_dir / (results_file or "results.json")
    results_file.write_text(json.dumps(test_results))
    logger.info(f"Created output file at {results_file}")


def smoketestselenium():
    # Robot Framework code as a string
    robot_code = """
*** Settings ***
Library    BuiltIn
Library    SeleniumLibrary
Library    /opt/src/addons_robot/robot_utils/library/browser.py

*** Test Cases ***
Smoke Test Robot
    Log    Hello, World!
    ${driver}=  Get Driver For Browser  download_path=${CURDIR}${/}..${/}tests/download    headless=${TRUE}  try_reuse_session=${FALSE}
    Go To       https://www.heise.de
    Call Method    ${driver}    quit
    """
    if os.getenv("ROBO_SMOKETEST") == "0":
        return True

    # Create a temporary file
    temp_file = Path(f"{uuid.uuid4()}.robot")
    try:
        temp_file.write_text(robot_code)
        old_width, old_height = os.environ.get("BROWSER_WIDTH"), os.environ.get(
            "BROWSER_HEIGHT"
        )
        os.environ["BROWSER_WIDTH"] = "800"
        os.environ["BROWSER_HEIGHT"] = "600"
        result = run(temp_file)
        # returns exit code 0 is good
        if result:
            raise Exception("Smoke test not passed.")
        logger.info("Smoke test passed.")

    finally:
        temp_file.unlink()
        os.environ["BROWSER_WIDTH"] = old_width
        os.environ["BROWSER_HEIGHT"] = old_height
    return True


def _clean_dir(path):
    for file in path.glob("*"):
        if file.is_dir():
            shutil.rmtree(file)
        else:
            file.unlink()


def restart_selenium_driver():
    logger.info("Restarting seleniumdriver container")
    SELENIUM_SERVICE_NAME = os.environ["SELENIUM_SERVICE_NAME"]
    subprocess.run(
        ["odoo", "-p", os.environ["project_name"], "kill", SELENIUM_SERVICE_NAME, "--brutal"]
    )
    subprocess.run(
        ["odoo", "-p", os.environ["project_name"], "restart", SELENIUM_SERVICE_NAME]
    )
    logger.info("Restarted seleniumdriver container")
    wait_for_port(SELENIUM_SERVICE_NAME, 4444)


def load_environment():
    project_name = os.environ["project_name"]
    settings_file = os.environ["SETTINGS_FILE"]
    load_dotenv(settings_file)


if __name__ == "__main__":
    load_environment()
    archive = Path("/tmp/archive")
    archive = base64.b64decode(archive.read_bytes())
    params = json.loads(archive)
    del archive

    SELENIUM_SERVICE_NAME = params.pop('SELENIUM_SERVICE_NAME')
    os.environ["SELENIUM_SERVICE_NAME"] = SELENIUM_SERVICE_NAME
    os.environ['ROBO_WEBDRIVER_HOST'] = f"{SELENIUM_SERVICE_NAME}:4444"
    os.environ["ROBOT_REMOTE_DEBUGGING"] = "1" if params.get("debug") else "0"
    if params["params"].get("headless"):
        os.environ["MOZ_HEADLESS"] = "1"
        restart_selenium_driver()

    if not smoketestselenium():
        print("\n\n\nSmoketest failed.\n\n")
        sys.exit(-1)
    run_tests(**params)
    logger.info("Finished calling robotest.py")
