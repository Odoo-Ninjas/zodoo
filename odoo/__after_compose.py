import time
import hashlib
from packaging.requirements import Requirement
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

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)
dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))

MINIMAL_MODULES = []  # to include its dependencies

my_cache = {}


def after_compose(config, settings, yml, globals):
    # store also in clear text the requirements
    from zodoo.odoo_config import MANIFEST

    shutil.copyfile(
        current_dir.parent / "common_snippets" / "set_docker_group.sh",
        current_dir / "set_docker_group.sh",
    )

    yml["services"].pop("odoo_base")
    manifest = MANIFEST()

    # Legacy v11/v13: revert the v14+ supervisor consolidation.
    # Why: those Debian Buster images run Python 3.7 and predate the
    # in-container supervisor; they must keep using run.py with one role
    # per container (odoo, odoo_cronjobs, odoo_queuejobs, odoo_update).
    _apply_legacy_split_containers(yml, settings)

    # odoo_debug inherits `profiles: [auto]` and `build:` from odoo_base via
    # compose.merge. We want it manual-only and pointing at the same image
    # tag as `odoo` (no separate build → truly one odoo image).
    odoo_debug = yml["services"].get("odoo_debug")
    if odoo_debug is not None:
        odoo_debug["profiles"] = ["manual"]
        odoo_debug.pop("build", None)

    # download python3.x version
    if float(settings["ODOO_VERSION"]) >= 13.0:
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
                python_tgz.parent.mkdir(exist_ok=True, parents=True)
                shutil.copy(filepath, python_tgz)

        PYTHON_VERSION = tuple(
            [int(x) for x in config.ODOO_PYTHON_VERSION.split(".")]
        )
    else:
        PYTHON_VERSION = (3, 8, 3)

    # Add remote debugging possibility in devmode
    _setup_remote_debugging(config, yml)

    _determine_requirements(config, yml, PYTHON_VERSION, settings, globals)

    _determine_odoo_configuration(
        config, yml, PYTHON_VERSION, settings, globals
    )

    _apply_fluentd_logging(config, yml, settings, globals)

    if config.RUN_PROXY:
        setup_external_odoo_eg_kubernetes(config, yml, globals)

    _eval_setting_common_filestore(config, settings, globals)


def store_sha_of_external_deps(deps, PYTHON_VERSION, file):
    v = ""
    for k in sorted(deps.keys()):
        v += str(deps[k])
    v += str(PYTHON_VERSION)
    hash = get_string_hash(v)
    file.write_text(hash)


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


def _check_fonttools_requirement(
    config, settings, all_dependencies, project_dependencies, static_reqs_path
):
    """For Odoo 19+: warn if fonttools is missing and offer to add it to requirements.static."""
    import sys

    try:
        odoo_version = float(settings.get("ODOO_VERSION", "0"))
    except (ValueError, TypeError):
        return

    if odoo_version < 19.0:
        return

    all_names = {
        _canonical_pip_name(p) for p in all_dependencies.get("pip", [])
    }
    if "fonttools" in all_names:
        return

    # Non-interactive: skip silently.
    is_interactive_mode = (
        os.getenv("ZODOO_INTERACTIVE", "1") == "1" and sys.stdin.isatty()
    )
    if not is_interactive_mode:
        return

    # Check if user previously said "no".
    from zodoo.myconfigparser import MyConfigParser

    project_settings_path = (config.files or {}).get("project_settings")
    if project_settings_path and project_settings_path.exists():
        proj_cfg = MyConfigParser(project_settings_path)
        if proj_cfg.get("ZODOO_FONTTOOLS_SKIP", "0") == "1":
            return

    click.secho(
        "\nOdoo 19: fonttools is not listed in requirements.txt but is required "
        "for correct font/PDF rendering. zodoo can add it to requirements.static.",
        fg="yellow",
    )
    add_it = click.confirm(
        "Add fonttools to requirements.static?", default=True
    )

    if add_it:
        existing = (
            static_reqs_path.read_text() if static_reqs_path.exists() else ""
        )
        if existing and not existing.endswith("\n"):
            existing += "\n"
        static_reqs_path.write_text(existing + "fonttools\n")
        all_dependencies["pip"] = _remove_requirements_from_requirements(
            all_dependencies["pip"], ["fonttools"]
        )
        all_dependencies["pip"].append("fonttools")
        project_dependencies["pip"].append("fonttools")
        click.secho("fonttools added to requirements.static.", fg="green")
    else:
        if project_settings_path:
            proj_cfg = MyConfigParser(project_settings_path)
            proj_cfg["ZODOO_FONTTOOLS_SKIP"] = "1"
            proj_cfg.write()
            click.secho(
                f"zodoo will not ask again. To re-enable: remove ZODOO_FONTTOOLS_SKIP "
                f"from {project_settings_path}",
                fg="yellow",
            )


def _determine_requirements(config, yml, PYTHON_VERSION, settings, globals):
    from zodoo.odoo_config import customs_dir, MANIFEST

    manifest = MANIFEST()

    if float(config.ODOO_VERSION) < 13.0:
        return

    get_services = globals["tools"].get_services

    odoo_machines = get_services(config, "odoo_base", yml=yml)
    odoo_dir = manifest.get("odoo_dir", "odoo")

    # Two clearly-separated dependency domains:
    #
    #   - framework_dependencies → Odoo's own upstream requirements.txt.
    #     Changes 4-8x per year (Odoo major / security releases). Baked
    #     into the per-version base image, so volatile-ARG-free at the
    #     project layer.
    #   - project_dependencies → everything the custom modules + the
    #     project's requirements.static add on top. Changes constantly
    #     (every new module / lib). Goes into the project layer as the
    #     final ARG-driven step so it does not invalidate the static
    #     zodoo-CLI install layers above it.
    all_dependencies = _get_dependencies(config, globals, PYTHON_VERSION)
    project_dependencies = _get_dependencies(
        config,
        globals,
        PYTHON_VERSION,
        exclude=(odoo_dir, "enterprise"),
    )
    framework_dependencies = _get_dependencies(
        config,
        globals,
        PYTHON_VERSION,
        include=(odoo_dir, "enterprise"),
    )

    # add static requirements (project-local pins from requirements.static):
    static_reqs_path = customs_dir() / "requirements.static"
    if static_reqs_path.exists():
        static_reqs = static_reqs_path.read_text().splitlines()
        # remove static requirements from collected deps:
        all_dependencies["pip"] = _remove_requirements_from_requirements(
            all_dependencies["pip"], static_reqs
        )
        all_dependencies["pip"] += static_reqs
        project_dependencies["pip"] += static_reqs

    _check_fonttools_requirement(
        config,
        settings,
        all_dependencies,
        project_dependencies,
        static_reqs_path,
    )

    store_sha_of_external_deps(
        all_dependencies,
        PYTHON_VERSION,
        config.WORKING_DIR / "requirements.hash",
    )
    store_sha_of_external_deps(
        framework_dependencies,
        PYTHON_VERSION,
        config.dirs["run"] / "requirements.odoo.hash",
    )

    # When a per-version base image is in use, ODOO_PROJECT_REQUIREMENTS
    # only contains the project-specific delta (Odoo's own
    # requirements.txt is already installed in the base venv). Without a
    # base, ODOO_PROJECT_REQUIREMENTS stays the legacy full set so the
    # monolithic Dockerfile keeps working.
    use_base_split = _base_split_active(config)

    framework_reqs_path = config.WORKING_DIR / odoo_dir / "requirements.txt"
    framework_reqs_text = (
        framework_reqs_path.read_text() if framework_reqs_path.exists() else ""
    )

    if use_base_split:
        project_pip_deps = _subtract_framework_requirements(
            all_dependencies["pip"],
            _filter_framework_requirements(framework_reqs_text),
            python_version=PYTHON_VERSION,
        )
    else:
        project_pip_deps = all_dependencies["pip"]

    sha = _get_sha(config) if settings["SHA_IN_DOCKER"] == "1" else "n/a"
    for odoo_machine in odoo_machines:
        service = yml["services"][odoo_machine]
        if "build" not in service:
            continue
        service["build"].setdefault("args", [])
        # ODOO_PROJECT_REQUIREMENTS = the project-specific pip delta.
        # Renamed from the historic (and misleading) ODOO_REQUIREMENTS so
        # it's clear this is NOT Odoo's framework requirements but the
        # custom-module + requirements.static delta.
        service["build"]["args"]["ODOO_PROJECT_REQUIREMENTS"] = (
            base64.encodebytes(
                "\n".join(project_pip_deps).encode("utf-8")
            ).decode("utf-8")
        )
        service["build"]["args"]["ODOO_PROJECT_REQUIREMENTS_CLEARTEXT"] = (
            ";".join(project_pip_deps).encode("utf-8")
        ).decode("utf-8")
        service["build"]["args"]["ODOO_PROJECT_DEB_REQUIREMENTS_CLEARTEXT"] = (
            "\n".join(sorted(all_dependencies["deb"]))
        )
        service["build"]["args"]["ODOO_PROJECT_DEB_REQUIREMENTS"] = (
            base64.encodebytes(
                "\n".join(sorted(all_dependencies["deb"])).encode("utf-8")
            ).decode("utf-8")
        )
        # Framework requirements are passed as a *constraint* file to the
        # project pip install so transitive deps from project packages
        # don't silently upgrade Odoo-pinned packages (requests,
        # cryptography, urllib3 …). Filtering matches the base build so
        # the project layer can install its own lxml pin from the delta.
        service["build"]["args"]["ODOO_FRAMEWORK_REQUIREMENTS"] = (
            base64.encodebytes(
                _filter_framework_requirements(framework_reqs_text).encode(
                    "utf-8"
                )
            ).decode("utf-8")
        )
        service["build"]["args"]["CUSTOMS_SHA"] = sha
        service["build"]["args"]["ODOO_PYTHON_VERSION"] = settings[
            "ODOO_PYTHON_VERSION"
        ]

    config.files["native_collected_requirements_from_modules"].parent.mkdir(
        exist_ok=True, parents=True
    )
    config.files["native_collected_requirements_from_modules"].write_text(
        "\n".join(all_dependencies["pip"])
    )

    _hack_patch_requirements(all_dependencies["pip"])

    # put the collected requirements into project root
    req_file_all = config.WORKING_DIR / "requirements.txt.all"
    req_file_all.write_text("\n".join(all_dependencies["pip"]) + "\n")

    req_file = config.WORKING_DIR / "requirements.txt"
    req_file.write_text("\n".join(project_dependencies["pip"]) + "\n")

    # put hash of requirements in root


def _hack_patch_requirements(external_dependencies):
    # html package changed
    external_dependencies.append("lxml-html-clean")


def _dir_dirty(globals):
    from zodoo.odoo_config import customs_dir

    tools = globals["tools"]
    return not tools.is_git_clean(
        customs_dir(), ignore_files=["requirements.txt"]
    )


def all_submodules_checked_out():
    from gimera import gimera

    try:
        gimera._check_all_submodules_initialized()
    except:
        return False
    else:
        return True


def cache_dir(tools):
    path = Path(os.path.expanduser("~/.cache/zodoo_image_odoo"))
    path.mkdir(exist_ok=True, parents=True)
    tools.__try_to_set_owner(tools.whoami(), path)
    return path


def _get_dependencies(
    config, globals, PYTHON_VERSION, exclude=None, include=None
):
    # fetch dependencies from odoo lib requirements
    # requirements from odoo framework
    tools = globals["tools"]

    Modules = globals["Modules"]
    Module = globals["Module"]

    def included(module):
        module = Module.get_by_name(module)
        for X in exclude or []:
            if str(module.path).startswith(X):
                return True
        return False

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
    if include:
        modules = [x for x in modules if included(x)]
    external_dependencies = Modules.get_all_external_dependencies(
        modules, PYTHON_VERSION
    )
    if external_dependencies:
        for key in sorted(external_dependencies):
            if not external_dependencies[key]:
                continue
            if config.verbose:
                click.secho(
                    "\nDetected external dependencies {}: {}".format(
                        key, ", ".join(map(str, external_dependencies[key]))
                    ),
                    fg="green",
                )

    tools = globals["tools"]

    external_dependencies.setdefault("pip", [])
    external_dependencies.setdefault("deb", [])

    for bin in external_dependencies.get("bin", []):
        external_dependencies["deb"] += [bin]

    if not exclude:
        append_odoo_requirements(config, external_dependencies, tools)
        external_dependencies["pip"] = Modules.resolve_pydeps(
            external_dependencies["pip"], PYTHON_VERSION
        )

    arr2 = []
    contains_setuptools = False
    for libpy in external_dependencies["pip"]:
        # PATCH python renamed dateutils to
        if "dateutil" in libpy and PYTHON_VERSION >= (3, 8, 0):
            if not re.findall("python.dateutil.*", libpy):
                libpy = libpy.replace("dateutil", "python-dateutil")

        # PATCH setuptools >=82 removed pkg_resources; odoo 17 requires it at least, perhaps also 19.0
        if "setuptools" in libpy:
            contains_setuptools = True

        arr2.append(libpy)
    if not contains_setuptools:
        arr2.append("setuptools<81")
    external_dependencies["pip"] = list(sorted(arr2))

    external_dependencies["pip"] = list(
        sorted(
            filter(
                lambda x: x not in ["ldap"],
                list(sorted(external_dependencies["pip"])),
            )
        )
    )
    external_dependencies["pip"] = _filter_pip(
        external_dependencies["pip"], config
    )
    return external_dependencies


def append_odoo_requirements(config, external_dependencies, tools):
    from zodoo.odoo_config import MANIFEST

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
            PYTHON_VERSION = ".".join(
                config.ODOO_PYTHON_VERSION.split(".")[:2]
            )
            if marker is None or marker.evaluate(
                {"python_version": PYTHON_VERSION}
            ):
                libpy = libpy.split(";")[0].strip()
            else:
                continue

        external_dependencies["pip"].append(libpy)


def _determine_odoo_configuration(
    config, yml, PYTHON_VERSION, settings, globals
):
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
        service["environment"]["ADDITIONAL_ODOO_CONFIG"] = "___|||___".join(
            config.splitlines()
        )


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


def _base_split_active(config):
    """True iff this project's Odoo version has a ``Dockerfile.base``.

    Imported lazily so that older zodoo CLI installs without
    ``lib_base_image`` still work for project versions that don't have a
    base recipe yet.
    """
    try:
        from zodoo.lib_base_image import base_dockerfile_path
    except ImportError:
        return False
    return base_dockerfile_path(config.odoo_version) is not None


def _zodoo_embed_active(config):
    """True iff zodoo source should be baked into the project image.

    Default is off — zodoo source is bind-mounted from the host at runtime
    (so source-only CLI updates don't require rebuilds). Set ZODOO_EMBED=1
    for self-contained k8s/AWS images (lib_bakery flips this automatically).
    """
    return str(getattr(config, "ZODOO_EMBED", "") or "").strip() in (
        "1",
        "true",
        "True",
    )


def _canonical_pip_name(spec):
    """Best-effort canonical package name for a pip requirement spec."""
    try:
        from packaging.utils import canonicalize_name

        return canonicalize_name(Requirement(spec).name)
    except Exception:
        # Strip extras + version specifier and lowercase.
        name = re.split(r"[<>=!~;\[\s]", (spec or "").strip(), 1)[0]
        return name.lower().replace("_", "-")


def _subtract_framework_requirements(
    all_pip, framework_reqs_text, python_version=None
):
    """Return ``all_pip`` minus everything Odoo's upstream
    ``requirements.txt`` actually installs for the given Python version.

    Crucially, lines with PEP-508 markers are only considered part of the
    framework set when the marker evaluates to True for ``python_version``.
    Without that filter, packages whose pins are gated to a different
    Python release (e.g. ``PyPDF==5.4.0 ; python_version >= '3.13'``)
    would be subtracted from the module-delta even when the framework
    does not install them at all, leaving the package missing from the
    final image.

    Comparison is on canonical package name only — a module that pins a
    different version of a framework-installed package keeps its pin
    (pip will reinstall it on top of the base venv).
    """
    # Normalize python_version to the "MAJOR.MINOR" string PEP-508 expects.
    py_ver_str = None
    if python_version:
        if isinstance(python_version, (tuple, list)):
            py_ver_str = ".".join(str(p) for p in python_version[:2])
        else:
            py_ver_str = ".".join(str(python_version).split(".")[:2])

    framework_names = set()
    for raw in (framework_reqs_text or "").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Strip trailing inline comment — Odoo's requirements.txt routinely
        # appends "# (Jammy)" etc. which trips up packaging.Requirement.
        parseable = re.split(r"\s+#", stripped, 1)[0].strip()
        try:
            req = Requirement(parseable)
            marker = req.marker
            if marker is not None and py_ver_str:
                if not marker.evaluate({"python_version": py_ver_str}):
                    continue
            framework_names.add(_canonical_pip_name(parseable))
        except Exception:
            framework_names.add(_canonical_pip_name(parseable))

    result = []
    for spec in all_pip:
        stripped = (spec or "").strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _canonical_pip_name(stripped) in framework_names:
            continue
        result.append(spec)
    return result


def _filter_framework_requirements(reqs):
    # Prob: lxml splitted away html clean
    # As lxml is always coming with odoo we dont touch the version here
    def _f(line):
        if "lxml" in line:
            return False
        return True

    return "\n".join(filter(_f, reqs.splitlines()))


def get_string_hash(input_string: str) -> str:
    """
    Returns the SHA-256 hash of the input string as a hexadecimal string.
    """
    hash_object = hashlib.sha256(input_string.encode("utf-8"))
    return hash_object.hexdigest()


def setup_external_odoo_eg_kubernetes(config, yml, globals):
    PROXY_ODOO_HOST = config.PROXY_ODOO_HOST or ""
    if not PROXY_ODOO_HOST:
        return
    PROXY_ODOO_HOST_CHAT = config.PROXY_ODOO_HOST_CHAT or PROXY_ODOO_HOST

    backends = globals["load_proxy_backends"](yml)

    parent = current_dir.parent / "odoo" / "proxy"
    odoo_conf = (parent / "odoo_external.conf").read_text()
    odoo_chat_conf = (parent / "odoo_chat_external.conf").read_text()

    for k, v in {
        "upstream": PROXY_ODOO_HOST,
        "upstream_chat": PROXY_ODOO_HOST or PROXY_ODOO_HOST_CHAT,
    }.items():

        def r(t):
            return t.replace(f"{{{k}}}", v)

        if not isinstance(v, bool):
            odoo_conf = r(odoo_conf)
            odoo_chat_conf = r(odoo_chat_conf)

    backends["odoo"] = {
        "nginx_conf": odoo_conf,
        "external": PROXY_ODOO_HOST,
    }
    backends["odoo_chat"] = {
        "nginx_conf": odoo_chat_conf,
        "external": PROXY_ODOO_HOST_CHAT,
    }

    globals["apply_proxy_backends"](yml, backends)


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


def is_legacy_version(settings):
    """v11/v13 keep the pre-supervisor split-container layout."""
    try:
        return float(settings["ODOO_VERSION"]) < 14.0
    except (KeyError, ValueError, TypeError):
        return False


def _apply_legacy_split_containers(yml, settings):
    if not is_legacy_version(settings):
        return

    services = yml["services"]
    odoo = services.get("odoo")
    if odoo is None:
        return

    # In non-devmode, drop the host zodoo bind-mount so legacy images
    # stay frozen at the zodoo source baked in at build time. In devmode
    # we keep the bind-mount so the local CLI source (which may include
    # py3.7 compatibility fixes not yet in upstream main) leaks into the
    # container — otherwise the image's frozen zodoo (cloned from
    # upstream main, possibly with py3.8+ syntax) will crash on import.
    if str(settings.get("DEVMODE", "0")) != "1":
        volumes = list(odoo.get("volumes") or [])
        odoo["volumes"] = [v for v in volumes if not _is_zodoo_bind_mount(v)]
        if not odoo["volumes"]:
            odoo.pop("volumes", None)

    # Drop the v14+ consolidated healthcheck inherited from odoo_base —
    # it runs healthcheck_cronjobs in the web container and uses an
    # awk-on-version test whose ${ODOO_VERSION:-0} interpolation gets
    # eaten by compose before reaching the shell. Pre-supervisor odoo
    # web had no healthcheck; restore that.
    odoo.pop("healthcheck", None)

    # Re-introduce the per-role services that the supervisor commit
    # collapsed into a single container.
    # NOTE: no healthcheck here. The consolidated healthcheck runs
    # /odoolib/healthcheck_cronjobs.py, but that script only ships in the
    # newer (supervisor-based) images. On the pre-supervisor images this
    # role split targets, the script is absent, so the check always exits
    # non-zero -> the container is permanently "unhealthy" and the
    # restart_unhealthy_containers watchdog restarts it every ~1-2 min.
    # That kills in-flight queue jobs mid-run (leaving "started" zombies)
    # and stalls the queue. Pre-supervisor cronjobs had no healthcheck;
    # restore that (matches the web container above).
    _ensure_legacy_role(
        services,
        "odoo_cronjobs",
        env={"IS_ODOO_CRONJOB": "1"},
        labels={"odoo.queuejob_container": "1"},
        restart="on-failure",
    )
    _ensure_legacy_role(
        services,
        "odoo_queuejobs",
        env={"IS_ODOO_QUEUEJOB": "1"},
        labels={"odoo.queuejob_container": "1"},
        restart="on-failure",
    )
    _ensure_legacy_role(
        services,
        "odoo_update",
        env={},
        restart="no",
        command="echo 'good bye - it is ok!'",
    )


def _is_zodoo_bind_mount(volume_entry):
    if isinstance(volume_entry, str):
        return ":/opt/zodoo" in volume_entry
    if isinstance(volume_entry, dict):
        return volume_entry.get("target") == "/opt/zodoo"
    return False


def _ensure_legacy_role(
    services,
    name,
    env,
    labels=None,
    restart="unless-stopped",
    healthcheck=None,
    command=None,
):
    if name in services:
        return

    # compose.merge is applied earlier in the pipeline (before
    # __after_compose runs), so newly added services here never inherit
    # build/image from odoo_base. Clone the already-resolved `odoo`
    # service as the base instead — same image, same volumes, same env
    # block — then layer the role-specific overrides on top.
    odoo = services.get("odoo")
    if odoo is None:
        return

    svc = deepcopy(odoo)
    svc.pop("ports", None)
    svc.pop("profiles", None)
    svc.pop("container_name", None)
    svc.pop("hostname", None)
    svc["restart"] = restart
    svc.setdefault("labels", {})
    svc["labels"].update({"compose.merge": "odoo_base"})
    if labels:
        svc["labels"].update(labels)
    svc.setdefault("environment", {})
    if isinstance(svc["environment"], list):
        svc["environment"] = dict(
            (kv.split("=", 1) + [""])[:2] for kv in svc["environment"]
        )
    # Drop role flags inherited from the consolidated odoo web service
    # before applying this role's override. Otherwise IS_ODOO_WEBSERVER=1
    # leaks into cronjobs/queuejobs/update containers and they run the
    # web codepath alongside their actual role.
    for k in list(svc["environment"].keys()):
        if k.startswith("IS_ODOO_"):
            svc["environment"].pop(k, None)
    svc["environment"].update(env)
    if healthcheck:
        svc["healthcheck"] = healthcheck
    else:
        svc.pop("healthcheck", None)
    if command is not None:
        svc["command"] = command
    else:
        svc.pop("command", None)
    services[name] = svc


def _setup_remote_debugging(config, yml):
    # In devmode, expose debugpy on the long-running `odoo` service.
    # Otherwise map it on `odoo_debug` (profile-gated, only spun up by
    # `odoo debug odoo_debug`) so the port is available the moment that
    # on-demand container starts.
    key = "odoo" if config.devmode else "odoo_debug"
    service = yml["services"].get(key)
    if service is None:
        return
    service.setdefault("ports", [])
    if config.ODOO_PYTHON_DEBUG_PORT and config.ODOO_PYTHON_DEBUG_PORT != "0":
        service["ports"].append(
            f"0.0.0.0:{config.ODOO_PYTHON_DEBUG_PORT}:5678"
        )


def _eval_setting_common_filestore(config, settings, globals):
    """
    Wenn ODOO_FILES_COMMON=1 gesetzt ist, wird ein gemeinsamer Filestore angelegt.

    Ablauf:
    - In ODOO_FILES wird ein Unterordner '_common' erstellt.
    - Alle anderen Unterverzeichnisse in ODOO_FILES werden per rsync nach '_common' kopiert.
    - Danach wird das jeweilige Verzeichnis gelöscht und durch einen Symlink auf '_common' ersetzt.

    Damit teilen sich alle Instanzen/Branches einen gemeinsamen Filestore, was Speicherplatz spart.
    Bereits vorhandene Symlinks werden übersprungen.
    """
    if settings.get("ODOO_FILES_COMMON") != "1":
        return

    rsync = globals["tools"].rsync
    files_dir = Path(settings["ODOO_FILES"]) / "filestore"
    common_dir = files_dir / "_common"
    common_dir.mkdir(exist_ok=True, parents=True)

    for entry in sorted(files_dir.iterdir()):
        if entry.name == "_common":
            continue
        if not entry.is_dir() or entry.is_symlink():
            continue

        rsync(entry, common_dir)

        # Verzeichnis entfernen und durch Symlink auf _common ersetzen
        shutil.rmtree(entry)
        entry.symlink_to("_common")
