import subprocess
from copy import deepcopy
import random
import time
import sys
import uuid
import arrow
import json
import base64
import os
import click

from .odoo_config import current_version
from .tools import __dcrun
from .tools import __dc  # NOQA
from .cli import cli, pass_config, Commands
from .lib_clickhelpers import AliasedGroup
from .tools import __empty_dir
from .tools import abort
from .tools import __assure_gitignore
from .tools import _get_available_robottests
from .tools import _yamldump
from .tools import atomic_write
from pathlib import Path

ROBOT_UTILS_GIT = "marcwimmer/odoo-robot_utils"
SELDRIVER_PREFIX = "seleniumdriver_"


@cli.group(cls=AliasedGroup)
@pass_config
def robot(config):
    pass


@robot.command()
@pass_config
@click.pass_context
def setup(ctx, config):
    from .odoo_config import MANIFEST, customs_dir
    import yaml

    content = yaml.safe_load((customs_dir() / "gimera.yml").read_text())
    for branch in content["repos"]:
        if ROBOT_UTILS_GIT in branch["url"]:
            break
    else:
        content["repos"].append(
            {
                "branch": "main",
                "path": "addons_robot",
                "type": "integrated",
                "url": f"git@github.com:{ROBOT_UTILS_GIT}",
            }
        )
        (customs_dir() / "gimera.yml").write_text(yaml.dump(content))

    manifest = MANIFEST()
    if "robot_utils" not in manifest["install"]:
        manifest["install"].append("robot_utils")

    if "addons_robot" not in manifest["addons_paths"]:
        paths = manifest["addons_paths"]
        paths.append("addons_robot")
        manifest["addons_paths"] = paths

    from gimera.gimera import apply as gimera

    _setup_robot_env(config, ctx)

    os.environ["GIMERA_NO_PRECOMMIT"] = "1"
    ctx.invoke(gimera, recursive=True, update=True, missing=True)
    if os.getenv("SILENT_ROBOT_SETUP") != "1":
        click.secho(
            "Create now your first robo test with 'odoo robot new smoketest",
            fg="green",
        )


def _setup_robot_env(config, ctx):
    # e.g. for robotcode extension used in vscdoe
    path = Path(os.path.expanduser("~/.robotenv"))
    reqfile = config.dirs["images"] / "robot" / "requirements.txt"

    if path.exists():
        return
    click.secho(
        "Setting up virtual environment for robotframework", fg="yellow"
    )
    subprocess.run(["python3", "-m", "venv", path], check=True)

    click.secho("Installing requirements for robotframework", fg="yellow")
    click.secho(reqfile.read_text(), fg="yellow")
    subprocess.run(
        [str(path / "bin" / "pip"), "install", "-r", reqfile], check=True
    )


@robot.command(name="new")
@click.argument("name", required=True)
@click.option("-I", "--no-install-pip", is_flag=True)
@pass_config
@click.pass_context
def do_new(ctx, config, name, no_install_pip):
    from .odoo_config import customs_dir

    os.environ["SILENT_ROBOT_SETUP"] = "1"
    if not no_install_pip:
        ctx.invoke(setup)

    testdir = customs_dir() / "tests"
    testdir.mkdir(exist_ok=True)

    content_file = (
        customs_dir()
        / "addons_robot"
        / "robot_utils"
        / "tests"
        / "test_template.robot"
    )
    if not content_file.exists():
        raise Exception(f"File not found: {content_file}")
    content = content_file.read_text()
    testfile = testdir / f"{name}.robot"
    if testfile.exists():
        abort(f"{testfile} already exists.")
    testfile.write_text(content)
    reltestfile = testfile.relative_to(customs_dir())
    click.secho(f"\n\nRun the test with: robot run {reltestfile}", fg="green")


@robot.command()
@click.argument(
    "file", required=False, shell_complete=_get_available_robottests
)
@click.option("-u", "--user", default="admin")
@click.option("-a", "--all", is_flag=True)
@click.option("-n", "--test_name", is_flag=False)
@click.option(
    "-p",
    "--param",
    multiple=True,
    help="e.g. --param key1=value1 --param key2=value2",
)
@click.option("--parallel", default=1, help="Parallel runs of robots.")
@click.option(
    "--keep-token-dir",
    is_flag=True,
    help="If set, then the intermediate run directory is kept. Helps to separate test runs of same robot file safely.",
)
@click.option(
    "-t",
    "--tags",
    is_flag=False,
    help=(
        "Tags can be comined with AND OR or just comma separated; "
        "may include wilcards and some regex expressions"
    ),
)
@click.option(
    "-j",
    "--output-json",
    is_flag=True,
    help=(
        "If set, then a json is printed to console, with detailed informations"
    ),
)
@click.option(
    "--results-file", help="concrete filename where the results.json is stored"
)
@click.option(
    "--timeout",
    required=False,
    default=20,
    help="Default timeout for wait until element is visible.",
)
@click.option(
    "-r",
    "--repeat",
    default=1,
    type=int,
)
@click.option(
    "-R",
    "--repeat-no-init",
    is_flag=True,
)
@click.option(
    "--min-success-required",
    default=100,
    type=int,
    help="Minimum percent success quote - provide with repeat parameter.",
)
@click.option(
    "-d",
    "--debug",
    is_flag=True,
    help="Use Visual Code to debug debugpy - connect the created profile.",
)
@click.option(
    "-M",
    "--no-install-further-modules",
    is_flag=True,
)
@click.option(
    "--test-tv",
    is_flag=True,
    help="Run browser non-headless so you can watch at /test.tv/",
)
@pass_config
@click.pass_context
def run(
    ctx,
    config,
    file,
    user,
    all,
    tags,
    test_name,
    param,
    parallel,
    output_json,
    keep_token_dir,
    results_file,
    timeout,
    repeat,
    repeat_no_init,
    min_success_required,
    no_sysexit=False,
    debug=False,
    no_install_further_modules=False,
    test_tv=False,
):
    PARAM = param
    del param
    started = arrow.utcnow()

    from .odoo_config import customs_dir
    from .module_tools import DBModules
    from .odoo_config import MANIFEST

    manifest = MANIFEST()

    # it is advised to turn on odoo cronjobs: if on restarting
    # the postgres container is shortly gone, cronjobs may fail
    # and get unhealthy and require a restart
    if (
        not config.run_cronjobs
        or not config.force_restart_unhealthy_containers
        or not config.run_robot
    ):
        Commands.invoke(
            ctx,
            "setting",
            no_reload=False,
            settings=[
                "RUN_ROBOT=1",
                "RUN_CRONJOBS=1",
                "FORCE_RESTART_UNHEALTHY_CONTAINERS=1",
            ],
        )
        Commands.invoke(ctx, "build", machines=["cronjobs"])

    if not config.devmode and not config.force:
        click.secho(
            (
                "Devmode required to run unit tests. Database will be destroyed."
            ),
            fg="red",
        )
        sys.exit(-1)

    from .robo_helpers import _select_robot_filename

    filenames = _select_robot_filename(file, run_all=all)
    del file

    if not filenames:
        return

    click.secho("\n".join(map(str, filenames)), fg="green", bold=True)

    from .robo_helpers import get_odoo_modules

    os.chdir(customs_dir())
    odoo_modules = set(
        get_odoo_modules(config.verbose, filenames, customs_dir())
    )
    modules = [("install", "robot_utils")]
    if current_version() < 15.0:
        modules.append(("install", "web_selenium"))

    install_odoo_modules, uninstall_odoo_modules = set(), set()
    for mode, mod in odoo_modules:
        if mode == "install":
            install_odoo_modules.add(mod)
        elif mode == "uninstall":
            uninstall_odoo_modules.add(mod)
        else:
            raise NotImplementedError(mode)
    del odoo_modules

    count_faileds = 0
    for i in range(int(repeat)):
        if not config.force and repeat > 1:
            if not repeat_no_init:
                click.secho(
                    "CAUTION: Repeat is set, but not force mode, so database is not recreated.",
                    fg="red",
                )

        if config.force and not no_install_further_modules:
            _prepare_fresh_robotest(ctx)

        if config.RUN_POSTGRES:
            Commands.invoke(
                ctx,
                "up",
                machines=["postgres"],
                daemon=True,
                no_recreate=True,
            )
            Commands.invoke(ctx, "wait_for_container_postgres")
        if install_odoo_modules:

            def not_installed(module):
                data = DBModules.get_meta_data(module)
                if not data:
                    abort(f"Could not get state for {module}")
                return data["state"] != "installed"

            install_modules_to_install = list(
                filter(not_installed, install_odoo_modules)
            )
            if install_modules_to_install:
                click.secho(
                    (
                        "Installing required modules for robot tests: "
                        f"{','.join(install_modules_to_install)}"
                    ),
                    fg="yellow",
                )
                Commands.invoke(
                    ctx,
                    "update",
                    module=install_modules_to_install,
                    no_dangling_check=True,
                )
                click.secho(
                    f"Installed modules {','.join(install_modules_to_install)}"
                )
        if uninstall_odoo_modules:

            def installed(module):
                data = DBModules.get_meta_data(module)
                if not data:
                    abort(f"Could not get state for {module}")
                return data["state"] == "installed"

            modules_to_uninstall = list(
                filter(installed, uninstall_odoo_modules)
            )
            if modules_to_uninstall:
                click.secho(
                    (
                        "Uninstalling required modules for robot tests: "
                        f"{','.join(modules_to_uninstall)}"
                    ),
                    fg="yellow",
                )
                Commands.invoke(
                    ctx,
                    "uninstall",
                    modules=modules_to_uninstall,
                )

        res = _run_test(
            ctx,
            config,
            user,
            test_name,
            parallel,
            timeout,
            tags,
            PARAM,
            filenames,
            results_file,
            started,
            output_json,
            keep_token_dir,
            debug=debug,
            test_tv=test_tv,
        )
        if not res:
            count_faileds += 1
        click.secho(
            f"Intermediate stat: {count_faileds} failed - {i+1 - count_faileds} succeeded - to go: {repeat -i - 1}",
            fg="yellow",
        )
    click.secho(
        f"Final stat: {count_faileds} failed of {repeat}",
        fg="green" if not count_faileds else "red",
    )
    success_quote = (repeat - count_faileds) / repeat * 100
    if success_quote < min_success_required:
        if not no_sysexit:
            sys.exit(-1)
        else:
            return False
    return True


def _run_test(
    ctx,
    config,
    user,
    test_name,
    parallel,
    timeout,
    tags,
    PARAM,
    filenames,
    results_file,
    started,
    output_json,
    keep_token_dir,
    debug=False,
    test_tv=False,
    browser=None,
):
    from .odoo_config import MANIFEST

    headless = os.getenv("IS_COBOT_CONTAINER") != "1" and not test_tv

    manifest = MANIFEST()
    if not browser:
        browser = "chrome"

    # if debug:
    #     _setup_visual_code_robot(ctx, config)

    pwd = "admin"
    click.secho(
        f"Password for all users will be set to {pwd}, so that login can happen.",
        fg="yellow",
    )
    Commands.invoke(ctx, "set-password-all-users", password=pwd)
    click.secho("Passwords set")

    def params():
        ODOO_VERSION = str(manifest["version"])
        params = {
            "url": "http://proxy",
            "user": user,
            "dbname": config.DBNAME,
            "password": pwd,
            "SELENIUM_TIMEOUT": timeout,  # selenium timeout,
            "parallel": parallel,
            "odoo_version": str(ODOO_VERSION),
            "headless": headless,
            "browser": browser,
        }
        if test_name:
            params["test_name"] = test_name
        if tags:
            params["tags"] = tags

        for param in PARAM:
            k, v = param.split("=")
            params[k] = v
            del param

        return params

    unique_robotname = f"robot_{uuid.uuid4()}"
    # copy robot and seleniumdriver template to have an instance
    selenium_service_name = _clone_seleniumdriver_template(
        ctx, config, unique_robotname
    )
    try:

        token = arrow.get().strftime("%Y-%m-%d_%H%M%S_") + str(uuid.uuid4())
        data = json.dumps(
            {
                "test_files": list(map(str, filenames)),
                "token": token,
                "results_file": results_file or "",
                "debug": debug,
                "params": params(),
                "SELENIUM_SERVICE_NAME": selenium_service_name,
            }
        )
        data = base64.b64encode(data.encode("utf-8")).decode("utf8")

        params = [
            "robot",
        ]

        from .odoo_config import customs_dir

        workingdir = customs_dir() / (
            Path(os.getcwd()).relative_to(customs_dir())
        )
        click.secho(f"Changing working dir: {workingdir}")
        os.chdir(workingdir)

        click.secho(f"Starting test: {params}")
        if os.getenv("IS_COBOT_CONTAINER") == "1":
            Path("/tmp/archive").write_text(data)
            subprocess.run(
                ["/usr/bin/python3", "/opt/robot/robotest.py"],
                env=os.environ,
            )
        else:
            try:
                Commands.invoke(
                    ctx, "up", daemon=True, machines=[selenium_service_name]
                )
                __dcrun(config, params, pass_stdin=data, interactive=True)
            finally:
                # ensure that the seleniumdriver is stopped
                Commands.invoke(ctx, "kill", machines=[selenium_service_name])
                Commands.invoke(ctx, "rm", machines=[selenium_service_name])
                click.secho(
                    f"Stopped seleniumdriver {selenium_service_name} container",
                    fg="yellow",
                )
        del data

        output_path = config.HOST_RUN_DIR / "odoo_outdir" / "robot_output"
        from .robo_helpers import _eval_robot_output

        res = _eval_robot_output(
            config,
            output_path,
            started,
            output_json,
            token,
            rm_tokendir=not keep_token_dir,
            results_file=results_file,
        )
    finally:
        _remove_service(config, selenium_service_name, unique_robotname)

    return res


def _remove_service(
    config, service_name=None, unique_appendix=None, service_prefix=None
):
    import yaml

    yml = yaml.safe_load(config.files["docker_compose"].read_text())
    popped = []

    if service_name:
        yml["services"].pop(service_name, None)
        popped.append(service_name)
    with atomic_write(config.files["docker_compose"]) as file:
        file.write_text(_yamldump(yml))

    for was_popped in popped:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={was_popped}", "-q"],
            capture_output=True,
            text=True,
        )
        container_ids = result.stdout.strip().split()
        if container_ids:
            subprocess.run(["docker", "rm", "-f"] + container_ids, check=False)

    return service_name


def _clone_seleniumdriver_template(ctx, config, appendix):
    import yaml

    yml = yaml.safe_load(config.files["docker_compose"].read_text())
    service_name = f"{SELDRIVER_PREFIX}{appendix}"
    yml["services"][service_name] = deepcopy(
        yml["services"]["seleniumdriver_template"]
    )
    yml["services"][service_name]["container_name"] = service_name
    with atomic_write(config.files["docker_compose"]) as file:
        file.write_text(_yamldump(yml))
    return service_name


def _prepare_fresh_robotest(ctx):
    click.secho("Preparing fresh robo test.", fg="yellow")
    Commands.invoke(ctx, "kill", machines=["postgres"])
    Commands.invoke(ctx, "reset-db")
    Commands.invoke(ctx, "wait_for_container_postgres", missing_ok=True)
    Commands.invoke(ctx, "update", "", tests=False, no_dangling_check=True)
    click.secho("Preparation of tests are done.", fg="yellow")


@robot.command(
    help="Runs all robots defined in section 'robotests' (filepatterns)"
)
@click.option(
    "--timeout",
    required=False,
    default=20,
    help="Default timeout for wait until element is visible.",
)
@click.option(
    "--retry",
    required=False,
    default=3,
    help="If test fails - retry.",
)
@click.option(
    "--filter",
    "filter_str",
    required=False,
    default=None,
    help="Filter test files by name containing this string.",
)
@click.option(
    "--list",
    "list_only",
    is_flag=True,
    default=False,
    help="List matching files without executing them.",
)
@pass_config
@click.pass_context
def run_all(
    ctx,
    config,
    timeout,
    retry,
    filter_str,
    list_only,
):
    from .odoo_config import customs_dir
    from .robo_helpers import _get_all_robottest_files
    from .odoo_config import customs_dir

    _remove_service(config, service_prefix=SELDRIVER_PREFIX)

    if not config.DEVMODE:
        abort("Devmode required to run robotests")
    customsdir = customs_dir()

    # if debug:
    #     _setup_visual_code_robot(ctx, config)

    files = _get_all_robottest_files()
    files = [customsdir / file for file in files]

    if filter_str:
        files = [f for f in files if filter_str in f.name]

    click.secho("Testing following files:")
    for file in files:
        click.secho(f"  {file}", fg="green")

    if list_only:
        return

    for file in files:
        click.secho(f"Running robotest {file}")

        for i in range(retry):
            click.secho(
                f"Try #{i + 1} of {retry} for {file.parent}/{file.name}"
            )
            try:
                res = ctx.invoke(
                    run,
                    file=str(file.relative_to(customsdir)),
                    timeout=timeout,
                    no_sysexit=True,
                )
                if res:
                    break
            except Exception as ex:
                retry += 1
                click.secho(
                    f"Retry at {file} because of {ex}",
                    fg="yellow",
                )
                time.sleep(random.randint(2, 8))


@robot.command()
@pass_config
@click.pass_context
def cleanup(ctx, config):
    output_path = config.HOST_RUN_DIR / "odoo_outdir" / "robot_output"
    if not output_path.exists():
        return
    __empty_dir(output_path, user_out=False)
    click.secho(f"Cleaned {output_path}")


def _setup_visual_code_robot(ctx, config):
    from .odoo_config import customs_dir

    path = customs_dir() / ".vscode" / "launch.json"
    if not path.exists():
        config = {
            "version": "0.2.0",
            "configurations": [],
        }
    else:
        config = json.loads(path.read_text())
    name = "Robot Framework Debugger (local attach)"

    # "type": "robotframework-lsp",
    target_conf = {
        "name": name,
        "type": "python",
        "request": "attach",
        "connect": {"host": "localhost", "port": 5678},
        "pathMappings": [
            {
                "localRoot": "${workspaceFolder}",
                "remoteRoot": "/home/parallels/projects/hpn",
            }
        ],
    }
    conf2 = []
    for conf in config.get("configurations", []):
        if name == conf["name"]:
            continue
        conf2.append(conf)
    conf2.insert(0, target_conf)
    config["configurations"] = conf2
    path.write_text(json.dumps(config, indent=4))


@robot.command(help="Access cobot on http://<host>/cobot")
@pass_config
@click.pass_context
def start_cobot(ctx, config):
    __dc(config, ["up", "-d", "novnc_cobot", "cobot", "proxy"])

    click.secho(f"Access cobot at: ")
    click.secho(
        f"\n{config.EXTERNAL_DOMAIN}:{config.PROXY_PORT}/cobot\n\n",
        fg="green",
        bold=True,
    )


@robot.command(help="Creates .robot-vars")
@click.option("-P", "--userpassword", required=False)
@pass_config
@click.pass_context
def make_variable_file(ctx, config, userpassword=None):
    host = os.getenv("ROBO_ODOO_HOST") or config.EXTERNAL_DOMAIN
    url = f"http://{host}:{config.PROXY_PORT}"
    from .odoo_config import customs_dir

    path = customs_dir() / ".robot-vars"
    if not path.exists():
        path.write_text("{}")
    data = json.loads(path.read_text())
    data.setdefault("TOKEN", 100)
    if userpassword:
        data["ROBO_ODOO_PASSWORD"] = userpassword
    data.setdefault("ROBO_ODOO_PASSWORD", "admin")
    data["project_name"] = config.project_name
    data["ROBO_ODOO_USER"] = "admin"
    data["ROBO_ODOO_VERSION"] = current_version()
    data["ROBO_ODOO_PORT"] = config.PROXY_PORT
    data["TEST_RUN_INDEX"] = 0
    data["TEST_DIR"] = str(customs_dir() / "robot-output")
    Path(data["TEST_DIR"]).mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=4))

    __assure_gitignore(customs_dir() / ".gitignore", ".robot-vars")


@robot.command(name="list", help="Creates .robot-vars")
@pass_config
@click.pass_context
def do_list(ctx, config):
    from .robo_helpers import _get_all_robottest_files

    files = _get_all_robottest_files()
    click.secho("!!!")
    for file in files:
        click.secho(file)
    click.secho("!!!")


Commands.register(make_variable_file, "robot:make-var-file")
Commands.register(run, "robot:run")
