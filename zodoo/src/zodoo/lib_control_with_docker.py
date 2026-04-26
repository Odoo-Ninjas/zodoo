import sys
import shutil
import os
import click
from .tools import __dcrun
from .tools import _askcontinue
from .tools import _is_container_running
from .tools import _get_bash_for_machine
from .tools import __cmd_interactive
from .tools import _display_machine_tips
from .tools import _wait_postgres
from .tools import __replace_in_file
from .tools import _wait_for_port
from .tools import __dcexec
from .tools import __dc
from .tools import __dc_out
from .tools import _get_host_ip
from .tools import __needs_docker
from .tools import get_docker_version
import subprocess
from .cli import Commands
import tempfile
from pathlib import Path


def _sudo_prefix():
    """Only prefix with sudo on Linux (volume paths in /var/lib/docker
    are root-owned there). On macOS the paths live inside the Docker VM
    and are not accessed directly — plus an interactive sudo prompt
    would hang non-interactive runs."""
    import platform

    return ["/usr/bin/sudo"] if platform.system() == "Linux" else []


def _run_no_stdin(cmd):
    """Run a command with stdin closed so sudo can't prompt."""
    return subprocess.check_output(cmd, stdin=subprocess.DEVNULL)


def _get_volume_hostpath(volume):
    from pathlib import Path

    cmd = _sudo_prefix() + [
        "docker",
        "volume",
        "inspect",
        "--format",
        "{{ .Mountpoint }}",
        volume,
    ]
    path = Path(_run_no_stdin(cmd).decode("utf-8").strip())
    if path.name == "_data":
        path = path.parent
    return path


def _get_volume_size(volume):
    try:
        cmd = _sudo_prefix() + ["du", "-sh", str(_get_volume_hostpath(volume))]
        size = _run_no_stdin(cmd).decode("utf-8")
        size = size.split("\t")[0]
        return size
    except Exception:
        return "n/a"


def _start_postgres_before(config):
    __dc(config, ["up", "-d", "postgres"])
    _wait_postgres(config)


def dev(ctx, config, build, kill):
    """
    starts developing in the odoo container
    """
    from .myconfigparser import MyConfigParser

    myconfig = MyConfigParser(config.files["settings"])
    if not config.devmode and not config.force:
        click.echo("Requires dev mode.")
        sys.exit(-1)
    if build:
        build(ctx, config)
    if kill:
        click.echo("Killing all docker containers")
        do_kill(ctx, config, machines=[], brutal=True)
        rm(ctx, config, machines=[])
    _start_postgres_before(config)
    __dc(config, ["up", "-d"])
    Commands.invoke(ctx, "kill", machines=["odoo"])
    ip = _get_host_ip()
    proxy_port = myconfig["PROXY_PORT"]
    roundcube_port = myconfig["ROUNDCUBE_PORT"]
    click.secho(
        f"Proxy Port: http://{ip}:{proxy_port}",
        fg="green",
        bold=True,
    )
    click.secho(
        f"Mailclient : http://{ip}:{roundcube_port}",
        fg="green",
        bold=True,
    )

    # execute script
    ScriptFile = config.files["start-dev"]
    if not ScriptFile.exists():
        click.secho(
            f"Info: you may provide a startup script here: {ScriptFile}",
            fg="yellow",
        )
    else:
        subprocess.Popen([str(ScriptFile)], stdout=subprocess.DEVNULL)

    Commands.invoke(ctx, "debug", machine="odoo")


def ps(config):
    args = ["ps", "-a"]
    __dc(config, args)


def execute(config, machine, args, user=None, interactive=True):
    args2 = []
    args2 += [machine] + list(args)
    __dcexec(config, args2, user=user, interactive=interactive)


def get_all_running_containers(config, profiles=None):
    cmd = ["ps"]
    output = __dc_out(
        config, cmd + ["--format", "table {{.Service}}"], profile=profiles
    ).strip()
    return output.splitlines()[1:]


def do_kill(ctx, config, machines=[], brutal=False, profile="auto"):
    """
    kills running machine
    safely shutdowns postgres and redis

    if not brutal it means softly
    """
    SAFE_KILL = []

    if not brutal:
        for machine in (config.safe_kill or "").split(","):
            if getattr(config, f"run_{machine}"):
                SAFE_KILL.append(machine)

    machines = list(machines)
    if not machines:
        machines = get_all_running_containers(config, profiles=profile)
    safe_stop = []
    for machine in SAFE_KILL:
        if not machines or machine in machines:
            if _is_container_running(config, machine):
                safe_stop += [machine]

    if safe_stop:
        __dc(
            config, ["stop", "-t", "20"] + safe_stop, profile=profile
        )  # persist data
    try:
        if brutal:
            __dc(config, ["kill"] + list(machines), profile=profile)
        else:
            __dc(config, ["stop", "-t", "2"] + list(machines), profile=profile)
    except subprocess.CalledProcessError as e:
        pass
        # was not possible to handle the not running error
        # chat gpt also suggests to maximally handle no such container or container not running


def force_kill(ctx, config, machine, profile="auto"):
    do_kill(ctx, config, machine=machine, brutal=True, profile=profile)


def wait_for_container_postgres(config):
    if config.USE_DOCKER:
        _wait_postgres(config)


def wait_for_port(host, port):
    port = int(port)
    _wait_for_port(host=host, port=port)


def recreate(ctx, config, machines=[]):
    machines = list(machines)
    __dc(config, ["up", "--no-start", "--force-recreate"] + machines)


def up(
    ctx,
    config,
    machines=[],
    daemon=False,
    remove_orphans=True,
    profile="all",
    force_recreate=False,
    no_recreate=None,
    allow_build=False,
):
    machines = list(machines)
    from .consts import resolve_profiles

    options = [
        # '--remove-orphans', # lost data with that; postgres volume suddenly new after rm?
        #'--compatibility' # to support reousrce limit swarm mode
    ]
    if not allow_build:
        options += ["--no-build"]
    if force_recreate:
        options += ["--force-recreate"]
    if no_recreate:
        options += ["--no-recreate"]
    if daemon:
        options += ["-d"]
    if remove_orphans:
        options += ["--remove-orphans"]
    dc_options = []
    if not machines and config.run_postgres and daemon and config.USE_DOCKER:
        _start_postgres_before(config)
    for profile in resolve_profiles(profile):
        dc_options2 = dc_options + ["--profile", profile]
        __dc(config, dc_options2 + ["up"] + options + machines)


def down(ctx, config, machines=[], volumes=False, remove_orphans=True):
    machines = list(machines)

    options = []
    # '--remove-orphans', # lost data with that; postgres volume suddenly new after rm?
    if volumes:
        options += ["--volumes"]
    if remove_orphans:
        options += ["--remove-orphans"]
    if config.devmode:
        __dc(config, ["kill"] + machines)

    __dc(config, ["down"] + options + machines)

    if volumes:
        Commands.invoke(ctx, "remove-volumes")


def stop(ctx, config, machines=[]):
    do_kill(ctx, config, machines=machines)


def rebuild(ctx, config, machines=[]):
    Commands.invoke(ctx, "compose", customs=config.customs)
    build(ctx, config, machines=machines, no_cache=True)


# Legacy compose-service names that used to be separate containers but now
# live as roles inside the single `odoo` container (see
# docker-compose.default_containers.yml and odoo/bin/supervisor.py).
# `odoo restart odoo_cronjobs` etc. must still work — we forward the call
# to the in-container supervisor instead of touching compose.
_LEGACY_ROLE_MAP = {
    "odoo_cronjobs": "cronjobs",
    "odoo_queuejobs": "queuejobs",
}


def _supervisor_restart_role(config, role):
    container = f"{config.project_name}_odoo"
    click.secho(
        f"Legacy service name → supervisor: restart {role} in {container}",
        fg="yellow",
    )
    subprocess.check_call(
        [
            "docker",
            "exec",
            container,
            "/opt/venv/bin/python",
            "/odoolib/supervisor.py",
            "restart",
            role,
        ]
    )


def restart(
    ctx,
    config,
    machines=[],
    profile="auto",
    brutal=True,
    force_recreate=False,
    no_recreate=None,
    restart_all=False,
):
    machines = list(machines)

    # Redirect legacy service names to the in-container supervisor so
    # existing robot tests that do `odoo restart odoo_cronjobs` keep working.
    legacy = [m for m in machines if m in _LEGACY_ROLE_MAP]
    machines = [m for m in machines if m not in _LEGACY_ROLE_MAP]
    for m in legacy:
        _supervisor_restart_role(config, _LEGACY_ROLE_MAP[m])
    if legacy and not machines:
        return

    # When no specific machines given and not --all, only restart odoo
    # containers (those inheriting from odoo_base). This leaves postgres,
    # proxy, redis etc. running and makes restarts much faster. Skip
    # services that live behind the `manual` profile (e.g. odoo_debug) —
    # those are only meant to be spun up on demand.
    if not machines and not restart_all:
        from .tools import get_services, _parse_yaml

        machines = get_services(config, "odoo_base")
        yml = _parse_yaml(config.files["docker_compose"].read_text())
        machines = [
            m
            for m in machines
            if "manual"
            not in (yml.get("services", {}).get(m, {}) or {}).get(
                "profiles", []
            )
        ]
        if machines:
            click.secho(
                f"Restarting only Odoo containers: {', '.join(sorted(machines))}  "
                f"(use -a/--all to restart everything)",
                fg="yellow",
            )

    # this is faster than docker restart: tested with normal project 6.75 seconds vs. 4.8 seconds
    do_kill(ctx, config, machines=machines, profile=profile, brutal=brutal)
    up(
        ctx,
        config,
        machines=machines,
        daemon=True,
        profile=profile,
        force_recreate=force_recreate,
        no_recreate=no_recreate,
    )


def rm(ctx, config, machines=[], profile="auto"):
    __needs_docker(config)
    machines = list(machines)
    __dc(config, ["rm", "-f"] + machines, profile=profile)


def attach(ctx, config, machine):
    """
    attaches to running machine
    """
    __needs_docker(config)
    _display_machine_tips(config, machine)
    bash = _get_bash_for_machine(machine)
    __cmd_interactive(config, "exec", machine, bash)


def pull(ctx, config):
    __dc(config, ["pull"])


def build(
    ctx,
    config,
    machines=[],
    pull=False,
    no_cache=False,
    push=False,
    include_source=False,
    platform=None,
):
    """
    no parameter all machines, first parameter machine name and passes other params; e.g. ./odoo build asterisk --no-cache"
    """
    options = []
    if pull:
        options += ["--pull"]
    if no_cache:
        options += ["--no-cache"]
        # if "--pull" not in options:
        #     # options += ["--pull"]
        #     pass
        # error with zodoo src image

    if config.verbose:
        os.environ["BUILDKIT_PROGRESS"] = "plain"

    if include_source:
        raise NotImplementedError("Please implement include source.")

    if not platform:
        platform = subprocess.check_output(
            ["/usr/bin/uname", "-m"], encoding="utf8"
        ).strip()
    _arch_map = {"x86_64": "amd64", "aarch64": "arm64"}
    _arch = platform.split("/")[-1]
    _arch = _arch_map.get(_arch, _arch)

    _ensure_prebuilt_python_image(config, _arch)

    __dc(
        config,
        ["build"] + options + list(machines),
        env={
            "ODOO_VERSION": config.odoo_version,
            "DOCKER_DEFAULT_PLATFORM": f"linux/{_arch}",
            "DOCKER_BUILDKIT": "1",
            "COMPOSE_BAKE": "true",
        },
    )


def _ensure_prebuilt_python_image(config, arch):
    """Auto-build the prebuilt Python image if it's missing in the registry.

    Odoo >= 19 builds derive their Python interpreter from
    ``${ZODOO_REGISTRY_URL}/zodoo/python:${ODOO_PYTHON_VERSION}-${TARGETARCH}``.
    If that image is not available in the configured registry, BuildKit
    fails with a cryptic ``not found`` error half-way through the build.

    This hook checks the registry up-front via ``docker manifest inspect``
    and, on miss, transparently runs ``images/python_prebuilt/build.sh``
    to build & push the image before continuing with the regular build.

    Silently no-ops when:
      - the prebuilt-python infrastructure is not present (older image set),
      - the project's Odoo Dockerfile does not reference the prebuilt image,
      - ``ODOO_PYTHON_VERSION`` or ``ZODOO_REGISTRY_URL`` are unset.
    """
    images_dir = Path(config.dirs["images"])
    script = images_dir / "python_prebuilt" / "build.sh"
    if not script.exists():
        return

    odoo_dockerfile = (
        images_dir
        / "odoo"
        / "config"
        / str(config.odoo_version)
        / "Dockerfile"
    )
    if (
        not odoo_dockerfile.exists()
        or "zodoo/python:" not in odoo_dockerfile.read_text()
    ):
        return

    python_version = getattr(config, "ODOO_PYTHON_VERSION", None)
    registry_url = (getattr(config, "ZODOO_REGISTRY_URL", None) or "").rstrip(
        "/"
    )
    if not python_version or not registry_url:
        return

    image = f"{registry_url}/zodoo/python:{python_version}-{arch}"
    try:
        subprocess.check_output(
            ["docker", "manifest", "inspect", image],
            stderr=subprocess.STDOUT,
        )
        return
    except subprocess.CalledProcessError:
        pass

    click.secho(
        f"Prebuilt Python image not found in registry: {image}\n"
        f"Building & pushing it now via {script} ...",
        fg="yellow",
    )
    subprocess.check_call([str(script), python_version, "--push"])
    click.secho(f"Prebuilt Python image built and pushed: {image}", fg="green")


def debug(ctx, config, machine, ports, cmd=None, set_docker_command=False):
    """
    starts /bin/bash for just that machine and connects to it; if machine is down, it is powered up; if it is up, it is restarted; as command an endless bash loop is set"
    """
    # puts endless loop into container command and then attaches to it;
    # by this, name resolution to the container still works
    if not config.devmode:
        _askcontinue(
            config,
            "Current machine {} is dropped and restartet with service ports in bash. Usually you have to type /debug.sh then.".format(
                machine
            ),
        )
    # shutdown current machine and start via run and port-mappings the replacement machine
    do_kill(ctx, config, machines=[machine])
    src_files = [config.files["debugging_template_onlyloop"]]
    tmp_cmd_file = None
    if cmd and set_docker_command:
        fd, tmp = tempfile.mkstemp(suffix=".")
        tmp_cmd_file = Path(tmp)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write("""
services:
  ${NAME}:
    command: ["/bin/bash", "-c", "___COMMAND___"]
        """.replace("___COMMAND___", " ".join(cmd)))
        except Exception:
            tmp_cmd_file.unlink(missing_ok=True)
            raise
        src_files = [tmp_cmd_file]

    if ports:
        src_files += [config.files["debugging_template_withports"]]

    cmd_prefix = []
    for i, filepath in enumerate(src_files):
        dest = config.files["debugging_composer"]
        dest = dest.parent / dest.name.replace(".yml", f".{i}.yml")
        shutil.copy(filepath, dest)
        __replace_in_file(dest, "__PORT__", str(ports or "33284"))
        __replace_in_file(dest, "${NAME}", machine)
        __replace_in_file(
            dest, "${DOCKER_COMPOSE_VERSION}", config.YAML_VERSION
        )

        # TODO make configurable in machines
        PORT = str({"odoo": 8069, "odoo_debug": 8069}.get(machine, 80))
        __replace_in_file(dest, "{machine_main_port}", PORT)

        cmd_prefix += ["-f", dest]

    if tmp_cmd_file is not None:
        tmp_cmd_file.unlink(missing_ok=True)

    __dc(config, cmd_prefix + ["up", "-d", machine])
    if not set_docker_command:
        if not isinstance(cmd, (tuple, list)):
            cmd = [cmd] if cmd else []
        if not cmd:
            attach(ctx, config, machine=machine)
        else:
            __dcexec(config, [machine] + cmd, interactive=True)
    else:
        click.secho(
            f"INFO: docker compose exec not executed as container's command was set. Starting container with up -d",
            fg="yellow",
        )


def run(ctx, config, machine, args, **kwparams):
    """
    extract volume mounts

    """
    if args and args[0] == "bash" and len(args) == 1:
        runbash(ctx, config, machine=machine)
        return
    __dcrun(config, [machine] + list(args), **kwparams)


def runbash(ctx, config, machine, args, **kwparams):
    _display_machine_tips(config, machine)
    bash = _get_bash_for_machine(machine)
    cmd = ["run", "--rm", "--entrypoint", "", machine]
    if args:
        cmd += args
    else:
        cmd += [bash]
    __cmd_interactive(config, *tuple(cmd))


def logall(config, machines, follow, lines):
    cmd = ["logs"]
    if follow:
        cmd += ["-f"]
    if lines:
        cmd += [f"--tail={lines}"]
    cmd += list(machines)
    __dc(config, cmd)


def shell(config, command="", queuejobs=False):
    if os.getenv("IS_ODOO_CONTAINER") == "1":
        cmdline = ["/odoolib/entrypoint.sh", "/odoolib/shell.py"]
        if command:
            cmdline += [command]
        res = subprocess.run(cmdline)
        return res.returncode
    cmd = [
        "run",
        "--rm",
    ]
    if get_docker_version()[0] >= 26:
        cmd += ["-it"]

    cmd += [
        "-e",
        "TERM=xterm-256color",
        "-e",
        "PYTHONUNBUFFERED=1",
        "odoo",
        "/odoolib/shell.py",
    ]
    if queuejobs:
        cmd += ["--queuejobs"]
    return __cmd_interactive(config, *(cmd + [command]))
