import time
import sys
from packaging.requirements import Requirement
from packaging.markers import Marker
from packaging.specifiers import SpecifierSet
import hashlib
from copy import deepcopy
from datetime import datetime
import shutil
import re
import base64
import click
import inspect
import os
import subprocess
from pathlib import Path

dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))

MINIMAL_MODULES = []  # to include its dependencies

my_cache = {}


def _is_git_dir(path):
    # import pudb;pudb.set_trace()
    # settings = subprocess.check_output(["git", "config", "--global", "-l"], encoding="utf8")
    # if "safe.directory=*" not in settings:
    #     subprocess.check_call(["git", "config", "--global", "--add", "safe.directory", "*"])
    try:
        env = deepcopy(os.environ)
        env.update(
            {
                "LC_ALL": "C",
            }
        )
        subprocess.check_call(["git", "rev-parse"], env=env, cwd=path)
        return True
    except subprocess.CalledProcessError as ex:
        return False


def _get_sha(config):
    if "sha" not in my_cache:
        path = config.WORKING_DIR
        if not _is_git_dir(path):
            # can be at released versions
            sha_file = path / ".sha"
            if sha_file.exists():
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sha = sha_file.read_text().strip()
            else:
                sha = None
        else:
            sha = subprocess.check_output(
                ["git", "log", "-n1", "--pretty=format:%H"],
                cwd=str(path),
                encoding="utf8",
            ).strip()
        my_cache["sha"] = sha
    return my_cache["sha"]


def _setup_remote_debugging(config, yml):
    if config.devmode:
        key = "odoo"
    else:
        key = "odoo_debug"
    yml["services"][key].setdefault("ports", [])
    if config.ODOO_PYTHON_DEBUG_PORT and config.ODOO_PYTHON_DEBUG_PORT != "0":
        yml["services"][key]["ports"].append(
            f"0.0.0.0:{config.ODOO_PYTHON_DEBUG_PORT}:5678"
        )


def after_compose(config, settings, yml, globals):
    # store also in clear text the requirements

    _eval_symlinks_in_root(config, settings, yml, globals)

    yml["services"].pop("odoo_base")

    # download python3.x version
    python_tgz = (
        config.dirs["images"]
        / "odoo"
        / "python"
        / f"Python-{settings['ODOO_PYTHON_VERSION']}.tgz"
    )
    if not python_tgz.exists():
        v = settings["ODOO_PYTHON_VERSION"]
        url = f"https://www.python.org/ftp/python/{v}/Python-{v}.tgz"
        click.secho(f"Downloading {url}")
        with globals["tools"].download_file(url) as filepath:
            shutil.copy(filepath, python_tgz)

    PYTHON_VERSION = tuple([int(x) for x in config.ODOO_PYTHON_VERSION.split(".")])

    # Add remote debugging possibility in devmode
    _setup_remote_debugging(config, yml)

    _determine_requirements(config, yml, PYTHON_VERSION, settings, globals)

    _determine_odoo_configuration(config, yml, PYTHON_VERSION, settings, globals)

    _apply_fluentd_logging(config, yml, settings, globals)


def store_sha_of_external_deps(config, deps):
    v = ""
    for k in sorted(deps.keys()):
        v += str(deps[k])
    # get md5 hash of string
    v = hashlib.md5(v.encode("utf-8")).hexdigest()

    req_file = config.WORKING_DIR / "requirements.hash"
    req_file.write_text(v)


def _filter_pip(packages, config):
    def _map(x):
        if x.strip().startswith("#"):
            return None
        if os.uname().machine == "aarch64":
            if float(config.ODOO_VERSION) in [14.0, 15.0, 16.0]:
                # if "gevent" in x:
                #     click.secho(
                #         "HACK: to provide correct gevent: return gevent==22.10.2",
                #         fg="red",
                #     )
                #     time.sleep(0.7)
                #     return "gevent==22.10.2"
                if "greenlet" in x:
                    click.secho(
                        "HACK: removing version info from greenlet on M1 chip",
                        fg="red",
                    )
                    time.sleep(0.7)
                    return "greenlet"
        return x

    packages = list(sorted(set(filter(bool, map(_map, packages)))))

    return packages


def _remove_requirements_from_requirements(the_list, remove_this):
    result = []
    for line in the_list:
        req2 = Requirement(line).name
        for remove in remove_this:
            req = Requirement(remove).name
            if req == req2:
                break
        else:
            result.append(line)

    return result


def _determine_requirements(config, yml, PYTHON_VERSION, settings, globals):
    from wodoo.odoo_config import customs_dir

    if float(config.ODOO_VERSION) < 13.0:
        return

    get_services = globals["tools"].get_services

    odoo_machines = get_services(config, "odoo_base", yml=yml)

    external_dependencies = _get_dependencies(config, globals, PYTHON_VERSION)
    external_dependencies_justaddons = _get_dependencies(
        config,
        globals,
        PYTHON_VERSION,
        exclude=("odoo", "enterprise"),
    )
    # add static requirements:
    static_reqs = customs_dir() / "requirements.static"
    if static_reqs.exists():
        static_reqs = static_reqs.read_text().splitlines()
        # remove static requirements from collected deps:
        external_dependencies["pip"] = _remove_requirements_from_requirements(
            external_dependencies["pip"], static_reqs
        )
        external_dependencies["pip"] += static_reqs
        external_dependencies_justaddons["pip"] += static_reqs

    store_sha_of_external_deps(config, external_dependencies)

    sha = _get_sha(config) if settings["SHA_IN_DOCKER"] == "1" else "n/a"
    click.secho(f"Identified SHA '{sha}'", fg="yellow")
    for odoo_machine in odoo_machines:
        service = yml["services"][odoo_machine]
        py_deps = external_dependencies["pip"]
        if "build" not in service:
            continue
        service["build"].setdefault("args", [])
        service["build"]["args"]["ODOO_REQUIREMENTS"] = base64.encodebytes(
            "\n".join(py_deps).encode("utf-8")
        ).decode("utf-8")
        service["build"]["args"]["ODOO_REQUIREMENTS_CLEARTEXT"] = (
            ";".join(py_deps).encode("utf-8")
        ).decode("utf-8")
        service["build"]["args"]["ODOO_DEB_REQUIREMENTS_CLEARTEXT"] = "\n".join(
            sorted(external_dependencies["deb"])
        )
        service["build"]["args"]["ODOO_DEB_REQUIREMENTS"] = base64.encodebytes(
            "\n".join(sorted(external_dependencies["deb"])).encode("utf-8")
        ).decode("utf-8")
        service["build"]["args"]["ODOO_FRAMEWORK_REQUIREMENTS"] = (
            _filter_framework_requirements(
                base64.encodebytes(
                    (config.dirs["odoo_home"] / "requirements.txt").read_bytes()
                ).decode("utf-8")
            )
        )
        service["build"]["args"]["CUSTOMS_SHA"] = sha
        service["build"]["args"]["ODOO_PYTHON_VERSION"] = settings[
            "ODOO_PYTHON_VERSION"
        ]

    config.files["native_collected_requirements_from_modules"].parent.mkdir(
        exist_ok=True, parents=True
    )
    config.files["native_collected_requirements_from_modules"].write_text(
        "\n".join(external_dependencies["pip"])
    )

    _hack_patch_requirements(external_dependencies["pip"])

    # put the collected requirements into project root
    req_file_all = config.WORKING_DIR / "requirements.txt.all"
    req_file_all.write_text("\n".join(external_dependencies["pip"]))

    req_file = config.WORKING_DIR / "requirements.txt"
    req_file.write_text("\n".join(external_dependencies_justaddons["pip"]))

    # put hash of requirements in root


def _hack_patch_requirements(external_dependencies):
    # html package changed
    external_dependencies.append("lxml-html-clean")


def _dir_dirty(globals):
    from wodoo.odoo_config import customs_dir

    tools = globals["tools"]
    return not tools.is_git_clean(customs_dir(), ignore_files=["requirements.txt"])


def all_submodules_checked_out():
    from gimera import gimera

    try:
        gimera._check_all_submodules_initialized()
    except:
        return False
    else:
        return True


def cache_dir(tools):
    path = Path(os.path.expanduser("~/.cache/wodoo_image_odoo"))
    path.mkdir(exist_ok=True, parents=True)
    tools.__try_to_set_owner(tools.whoami(), path)
    return path


def _get_dependencies(config, globals, PYTHON_VERSION, exclude=None):
    # fetch dependencies from odoo lib requirements
    # requirements from odoo framework
    tools = globals["tools"]

    Modules = globals["Modules"]
    Module = globals["Module"]

    def not_excluded(module):
        module = Module.get_by_name(module)
        for X in exclude or []:
            if str(module.path).startswith(X):
                return False
        return True

    # fetch the external python dependencies
    modules = Modules.get_all_used_modules(include_uninstall=True)
    modules = list(sorted(set(modules) | set(MINIMAL_MODULES or [])))
    if exclude:
        modules = [x for x in modules if not_excluded(x)]
    external_dependencies = Modules.get_all_external_dependencies(
        modules, PYTHON_VERSION
    )
    if external_dependencies:
        for key in sorted(external_dependencies):
            if not external_dependencies[key]:
                continue
            click.secho(
                "\nDetected external dependencies {}: {}".format(
                    key, ", ".join(map(str, external_dependencies[key]))
                ),
                fg="green",
            )

    tools = globals["tools"]

    external_dependencies.setdefault("pip", [])
    external_dependencies.setdefault("deb", [])

    if not exclude:
        append_odoo_requirements(config, external_dependencies, tools)
        external_dependencies["pip"] = Modules.resolve_pydeps(
            external_dependencies["pip"], PYTHON_VERSION
        )

    arr2 = []
    for libpy in external_dependencies["pip"]:
        # PATCH python renamed dateutils to
        if "dateutil" in libpy and PYTHON_VERSION >= (3, 8, 0):
            if not re.findall("python.dateutil.*", libpy):
                libpy = libpy.replace("dateutil", "python-dateutil")
        arr2.append(libpy)
    external_dependencies["pip"] = list(sorted(arr2))

    external_dependencies["pip"] = list(
        sorted(
            filter(
                lambda x: x not in ["ldap"],
                list(sorted(external_dependencies["pip"])),
            )
        )
    )
    external_dependencies["pip"] = _filter_pip(external_dependencies["pip"], config)
    return external_dependencies


def _eval_symlinks_in_root(config, settings, yml, globals):
    from wodoo.odoo_config import customs_dir, MANIFEST

    odoo_version = float(config.ODOO_VERSION)

    for file in customs_dir().glob("*"):
        if not file.is_symlink():
            continue

        rootdir = customs_dir()
        abspath = file.resolve().absolute()

        get_services = globals["tools"].get_services
        odoo_machines = get_services(config, "odoo_base", yml=yml)
        for machine in odoo_machines:
            machine = yml["services"][machine]
            machine.setdefault("volumes", {})
            p2 = Path("/opt/src") / str(file.relative_to(rootdir))
            machine["volumes"].append(f"{abspath}:{p2}")


def append_odoo_requirements(config, external_dependencies, tools):
    from wodoo.odoo_config import customs_dir, MANIFEST
    manifest = MANIFEST()
    odoo_dir = manifest.get("odoo_dir", "odoo")
    requirements_odoo = config.WORKING_DIR / odoo_dir / "requirements.txt"
    if not requirements_odoo.exists():
        return

    for libpy in requirements_odoo.read_text().splitlines():
        libpy = libpy.strip()
        libpy = libpy.split("#")[0].strip()
        if not libpy:
            continue

        if ";" in libpy:
            req = Requirement(libpy)
            package_name = req.name
            version_specifier = req.specifier
            marker = req.marker  # This is a Marker object
            PYTHON_VERSION = ".".join(config.ODOO_PYTHON_VERSION.split(".")[:2])
            if marker is None or marker.evaluate({"python_version": PYTHON_VERSION}):
                libpy = libpy.split(";")[0].strip()
                pass
            else:
                continue

        external_dependencies["pip"].append(libpy)


def _determine_odoo_configuration(config, yml, PYTHON_VERSION, settings, globals):
    files = []
    if "odoo_config_file_additions" not in config.files:
        return
    files += [config.files["odoo_config_file_additions"]]
    files += [config.files["odoo_config_file_additions.project"]]

    config = ""
    for file in files:
        if not file.exists():
            continue
        config += Path(file).read_text() + "\n"

    if "[options]" not in config:
        config = "[options]\n" + config

    # odoo_config_file_additions

    get_services = globals["tools"].get_services

    odoo_machines = get_services(config, "odoo_base", yml=yml)
    for odoo_machine in odoo_machines:
        service = yml["services"][odoo_machine]
        service["environment"]["ADDITIONAL_ODOO_CONFIG"] = config


def _apply_fluentd_logging(config, yml, settings, globals):
    if not config.run_logcollector:
        return

    get_services = globals["tools"].get_services
    odoo_machines = get_services(config, "odoo_base", yml=yml)
    for odoo_machine in odoo_machines:
        service = yml["services"][odoo_machine]
        tag = service["logging"]["options"]["tag"]
        tag = tag.replace("__SERVICE__", odoo_machine)
        service["logging"]["options"]["tag"] = tag


def _filter_framework_requirements(reqs):
    # Prob: lxml splitted away html clean
    # As lxml is always coming with odoo we dont touch the version here
    def _f(line):
        if "lxml" in line:
            return False
        return True

    return "\n".join(filter(_f, reqs.splitlines()))
