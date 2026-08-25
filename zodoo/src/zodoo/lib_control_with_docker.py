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
from .tools import abort
from .tools import __get_cmd
from .tools import _set_default_envs
from .tools import _merge_env_dict
from .tools import ensure_project_name
from .tools import root_cmd
import subprocess
from .cli import Commands
import tempfile
from pathlib import Path


def _run_no_stdin(cmd):
    """Run a command with stdin closed so sudo can't prompt."""
    return subprocess.check_output(cmd, stdin=subprocess.DEVNULL)


def _get_volume_hostpath(volume):
    from pathlib import Path

    cmd = root_cmd(
        "docker",
        "volume",
        "inspect",
        "--format",
        "{{ .Mountpoint }}",
        volume,
    )
    path = Path(_run_no_stdin(cmd).decode("utf-8").strip())
    if path.name == "_data":
        path = path.parent
    return path


def _get_volume_size(volume):
    try:
        cmd = root_cmd("du", "-sh", str(_get_volume_hostpath(volume)))
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


def _graceful_pg_shutdown(config):
    """In production, ask postgres to shut down cleanly via pg_ctl before
    docker stops the container. A `docker stop -t 20` only allows 20 s
    between SIGTERM and SIGKILL — under heavy write load (large DELETEs,
    WAL flush) the shutdown checkpoint may not finish in time and postgres
    gets killed mid-write, forcing crash recovery on the next start.
    `pg_ctl stop -m fast -w` cancels running queries, writes the
    checkpoint and waits for the postmaster to exit."""
    cmd = [
        "postgres",
        "bash",
        "-c",
        'pg_ctl stop -D "$PGDATA" -m fast -w -t 300',
    ]
    try:
        __dcexec(config, cmd, interactive=False, user="postgres")
    except Exception as e:
        # Best-effort: any failure (non-zero pg_ctl, vanished container,
        # exec error) must fall through to the subsequent docker compose
        # stop rather than aborting the whole kill, as the message promises.
        click.secho(
            f"pg_ctl graceful stop failed ({e}); "
            "falling back to docker compose stop.",
            fg="yellow",
        )


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
    # Redirect legacy service names to the in-container supervisor (v14+).
    legacy, machines = _legacy_role_match(config, machines)
    for m in legacy:
        _supervisor_action_role(config, "stop", _resolve_legacy_role(m))
    if legacy and not machines:
        return
    if not machines:
        machines = get_all_running_containers(config, profiles=profile)
    safe_stop = []
    for machine in SAFE_KILL:
        if not machines or machine in machines:
            if _is_container_running(config, machine):
                safe_stop += [machine]

    # In production, give postgres a chance to shut down cleanly via pg_ctl
    # before docker sends SIGTERM/SIGKILL. 20 s grace is not enough under
    # heavy write load and leaves the cluster in "not properly shut down"
    # state on next start.
    if not brutal and not config.devmode and "postgres" in safe_stop:
        _graceful_pg_shutdown(config)

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
    # Redirect legacy service names to the in-container supervisor (v14+).
    legacy, machines = _legacy_role_match(config, machines)
    for m in legacy:
        _supervisor_action_role(config, "start", _resolve_legacy_role(m))
    if legacy and not machines:
        return
    from .consts import resolve_profiles

    options = [
        # '--remove-orphans', # lost data with that; postgres volume suddenly new after rm?
        #'--compatibility' # to support reousrce limit swarm mode
    ]
    if not allow_build:
        options += ["--no-build"]
    else:
        # With --build, compose builds the project image whose
        # `FROM ${BASE_TAG}` references the per-version base image. That base
        # is built by `odoo build`, not by compose — so ensure it exists
        # (build or pull) first, otherwise the compose build fails resolving
        # the base tag (this is the registry-less CICD path that uses --build).
        _ensure_base_image_for_build(config, machines)
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
    for resolved_profile in resolve_profiles(profile):
        try:
            __dc(
                config,
                dc_options + ["up"] + options + machines,
                profile=resolved_profile,
            )
        except subprocess.CalledProcessError as e:
            if no_recreate:
                # up --no-recreate can fail when Docker removed the network during orphan
                # cleanup (CalledProcessError.stderr is None when using check_call, so we
                # cannot inspect the message). The partial up may have left zombie containers
                # attached to the defunct network, so we must do a full down first, then
                # up fresh. Volumes are NOT removed — any restored DB dump is safe.
                click.secho(
                    f"up --no-recreate failed, doing down + up to recover: {e}",
                    fg="yellow",
                )
                try:
                    __dc(
                        config,
                        dc_options + ["down", "--remove-orphans"],
                        profile=resolved_profile,
                    )
                except subprocess.CalledProcessError:
                    pass  # ignore down failure, proceed with up anyway
                options_without_no_recreate = [
                    o for o in options if o != "--no-recreate"
                ]
                __dc(
                    config,
                    dc_options
                    + ["up"]
                    + options_without_no_recreate
                    + machines,
                    profile=resolved_profile,
                )
            else:
                raise


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

    # Use profile="all" so that services behind the "manual" profile (e.g.
    # odoo_debug) are also removed. Without this they survive `down -v` and
    # keep a stale network reference that breaks the next `up --no-recreate`.
    __dc(config, ["down"] + options + machines, profile="all")

    # `docker compose down` does NOT remove oneoff containers (those created
    # via `docker compose run`, e.g. by `odoo shell`). Find and remove them
    # explicitly so the project is fully shut down.
    _remove_oneoff_containers(config, machines)

    if volumes:
        Commands.invoke(ctx, "remove-volumes")


def _remove_oneoff_containers(config, machines=None):
    filters = [
        "--filter",
        f"label=com.docker.compose.project={config.project_name}",
        "--filter",
        "label=com.docker.compose.oneoff=True",
    ]
    try:
        out = subprocess.check_output(
            ["docker", "ps", "-aq"] + filters, text=True
        ).strip()
    except subprocess.CalledProcessError:
        return
    ids = [x for x in out.split("\n") if x]
    if not ids:
        return
    if machines:
        kept = []
        for cid in ids:
            try:
                service = subprocess.check_output(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        '{{ index .Config.Labels "com.docker.compose.service" }}',
                        cid,
                    ],
                    text=True,
                ).strip()
            except subprocess.CalledProcessError:
                continue
            if service in machines:
                kept.append(cid)
        ids = kept
        if not ids:
            return
    subprocess.call(["docker", "rm", "-f"] + ids)


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
    # "odoo" intentionally NOT here: `odoo kill odoo` must stop the whole
    # container via docker compose, not just the web supervisor process.
    # Use `odoo kill odoo_web` to stop only the in-container web service.
    "odoo_web": "web",
    "odoo_cronjobs": "cronjobs",
    "odoo_queuejobs": "queuejobs",
}


def _has_in_container_supervisor(config):
    """v11/v13 keep the pre-supervisor split-container layout — those
    versions run debian-buster with Python 3.7 and use legacy run.py.
    For them odoo_cronjobs / odoo_queuejobs are real compose services,
    so the LEGACY_ROLE_MAP redirect to the in-container supervisor must
    be bypassed."""
    try:
        return float(config.odoo_version) >= 14.0
    except (AttributeError, ValueError, TypeError):
        return True


def _normalize_legacy_name(name):
    """Treat ``odoo_web``, ``odoo-web`` and ``odoo.web`` as the same name
    so the user can spell role redirects either with underscore (matches
    the original compose service), hyphen, or dot."""
    return name.replace("-", "_").replace(".", "_")


def _resolve_legacy_role(name):
    """Return the supervisor-role name for a CLI machine name (with
    separator tolerance), or ``None`` if the name doesn't refer to a
    legacy supervisor-redirected service."""
    return _LEGACY_ROLE_MAP.get(_normalize_legacy_name(name))


def _legacy_role_match(config, machines):
    if not _has_in_container_supervisor(config):
        return [], list(machines)
    legacy = [m for m in machines if _resolve_legacy_role(m) is not None]
    rest = [m for m in machines if _resolve_legacy_role(m) is None]
    return legacy, rest


def _start_odoo_container(config, why):
    """Bring the consolidated `odoo` compose service up.

    Used when a role start is requested while the container itself is down:
    `docker exec` cannot reach a dead container, and the legacy per-role
    service names (odoo_web, …) are not declared in generated composes any
    more, so both paths of `_supervisor_action_role` would fail. Starting the
    real service is the only thing that works — its supervisor then spawns
    every enabled role by itself.
    """
    click.secho(why, fg="yellow")
    try:
        __dc(config, ["up", "-d", "--no-recreate", "odoo"], profile="auto")
        return True
    except subprocess.CalledProcessError as e:
        click.secho(
            f"Could not start compose service odoo: {e}",
            fg="red",
        )
        return False


def _supervisor_action_role(config, action, role):
    """Returns True when the action was confirmed (or is a definitional no-op,
    e.g. stopping a role whose container isn't running), False when neither the
    supervisor nor the compose fallback could carry it out. Callers that gate
    DDL on a role being stopped must inspect the return value."""
    container = f"{config.project_name}_odoo"
    if action in ("stop", "restart") and not _is_container_running(
        config, "odoo"
    ):
        click.secho(
            f"Container {container} is not running — skipping supervisor {action} {role}",
            fg="yellow",
        )
        return True
    if action == "start" and not _is_container_running(config, "odoo"):
        return _start_odoo_container(
            config,
            f"Container {container} is not running — starting compose "
            f"service odoo instead of supervisor start {role}",
        )
    click.secho(
        f"Legacy service name → supervisor: {action} {role} in {container}",
        fg="yellow",
    )
    try:
        subprocess.check_call(
            [
                "docker",
                "exec",
                container,
                "/opt/venv/bin/python",
                "/odoolib/supervisor.py",
                action,
                role,
            ]
        )
        return True
    except subprocess.CalledProcessError as e:
        # Transition period: old containers may not ship supervisor.py yet,
        # or may not know the requested role. Fall back to compose-level ops
        # on the legacy service name so update/restart can still proceed.
        legacy_name = next(
            (k for k, v in _LEGACY_ROLE_MAP.items() if v == role),
            None,
        )
        click.secho(
            f"Supervisor {action} {role} failed in {container} ({e}). "
            f"Falling back to compose-level {action} on legacy service "
            f"{legacy_name or '<unknown>'}.",
            fg="yellow",
        )
        if not legacy_name:
            return False
    try:
        if action == "stop":
            __dc(config, ["stop", "-t", "2", legacy_name], profile="auto")
        elif action == "start":
            __dc(
                config,
                ["up", "-d", "--no-recreate", legacy_name],
                profile="auto",
            )
        elif action == "restart":
            __dc(config, ["restart", legacy_name], profile="auto")
        else:
            raise ValueError(f"unknown supervisor action {action!r}")
        return True
    except subprocess.CalledProcessError as e2:
        # Legacy service may not exist in the current compose either. Don't
        # fail update over a best-effort op — caller recreates containers.
        click.secho(
            f"Compose-level fallback {action} {legacy_name} also failed "
            f"({e2}). Continuing.",
            fg="red",
        )
        return False


def _supervisor_restart_role(config, role):
    return _supervisor_action_role(config, "restart", role)


# Roles that must be stopped before any DDL-heavy `odoo update` so that
# queue/cron workers don't sit idle-in-transaction on tables the
# pre-migrate ALTERs (lock timeout otherwise). web is included because
# user requests can also grab row locks during long migrations.
_UPDATE_BLOCKING_ROLES = ("web", "queuejobs", "cronjobs")


def _declared_compose_services(config):
    from .tools import _parse_yaml

    yml = _parse_yaml(config.files["docker_compose"].read_text())
    return set((yml.get("services", {}) or {}).keys())


def _touch_proxy_warmup_gate(config):
    """Touch the nginx-proxy warmup-gate sentinel from the host side so
    external clients see the maintenance page (instead of the bare-503
    static fallback) while `odoo update` stops the web role for several
    minutes. The sentinel is cleared automatically once the web role
    spawns again and finishes its warmup loop (signal_warmup_done in
    odoo/bin/tools.py). Never raises — projects without the bundled
    proxy simply don't have the volume mounted."""
    try:
        p = config.dirs["run"] / "proxy_exchange" / "warmup_in_progress"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    except Exception as e:
        click.secho(f"[warmup gate] could not touch {p}: {e}", fg="yellow")


def stop_update_blocking_roles(config):
    """Stop web, queuejobs and cronjobs supervisor children + their
    legacy split-container counterparts. Silently no-ops if the odoo
    container or a given role isn't running. Used by `odoo update`."""
    from .lib_standard_image import is_standard_image

    if is_standard_image(config):
        # Kein Supervisor im offiziellen Image -- und vor allem: das
        # Warmup-Gate wuerde niemand mehr zuruecksetzen (das macht sonst
        # der web-Role beim Hochlaufen). Der Proxy zeigte dann dauerhaft
        # die Wartungsseite. Also gar nicht erst setzen.
        return
    if not _has_in_container_supervisor(config):
        return
    # Gate the proxy *before* we stop web so external clients never
    # see the static-fallback 403 during an update.
    _touch_proxy_warmup_gate(config)
    unconfirmed = []
    for role in _UPDATE_BLOCKING_ROLES:
        if not _supervisor_action_role(config, "stop", role):
            unconfirmed.append(role)
    if unconfirmed:
        # Neither the supervisor nor the compose fallback could confirm the
        # stop. The update proceeds, but DDL migrations may hit lock
        # contention from workers still holding row/table locks — make this
        # loud so it isn't lost in CI logs as a single yellow line.
        click.secho(
            f"WARNING: could not confirm stop of role(s) "
            f"{', '.join(unconfirmed)} before update — DDL migrations may "
            f"block on locks held by still-running workers.",
            fg="red",
            bold=True,
        )
    # Pre-v14 layouts (and some current installs, e.g. cicd_app) also
    # run cronjobs/cronjobshell as separate compose services. Stop them
    # explicitly so their odoo workers release locks too. Skip services
    # that aren't declared (e.g. when RUN_ODOO_CRONJOBS=False) — querying
    # docker compose for an unknown service errors out.
    declared = _declared_compose_services(config)
    for svc in ("cronjobs", "cronjobshell", "queuejobs"):
        if svc not in declared:
            continue
        if _is_container_running(config, svc):
            try:
                __dc(config, ["stop", "-t", "10", svc])
            except subprocess.CalledProcessError as e:
                click.secho(
                    f"Warning: could not stop service {svc}: {e}",
                    fg="yellow",
                )


def start_update_blocking_roles(config):
    """Counterpart of stop_update_blocking_roles: brings web, queuejobs,
    cronjobs back up after an update completes."""
    from .lib_standard_image import is_standard_image

    if is_standard_image(config):
        # Gegenstueck zu stop_update_blocking_roles: dort wurde nichts
        # gestoppt, hier ist also auch nichts zu starten. Der laufende
        # odoo-Container bleibt waehrend des Updates stehen -- das Update
        # laeuft in einem eigenen `run --rm`-Container.
        return
    if not _has_in_container_supervisor(config):
        return
    if not _is_container_running(config, "odoo"):
        # The whole container is gone — nothing to talk to. This is the state
        # an `odoo update` leaves behind when it took the compose project
        # down first (cicd devmode does a brutal kill) and then took an early
        # exit ("No module update required"): all three role starts failed,
        # the compose fallback tried the long-gone odoo_web/odoo_queuejobs/
        # odoo_cronjobs services, and the instance stayed offline until
        # somebody noticed (5 h on a 3dm staging instance). Start the
        # container once and let its supervisor spawn the enabled roles —
        # per-role `docker exec` right after `up -d` would only race the
        # supervisor's control socket.
        _start_odoo_container(
            config,
            "Container is not running after update — starting compose "
            "service odoo (its supervisor spawns web/queuejobs/cronjobs)",
        )
    else:
        unconfirmed = []
        for role in _UPDATE_BLOCKING_ROLES:
            if not _supervisor_action_role(config, "start", role):
                unconfirmed.append(role)
        if unconfirmed:
            click.secho(
                f"WARNING: could not confirm start of role(s) "
                f"{', '.join(unconfirmed)} after update.",
                fg="yellow",
            )
    declared = _declared_compose_services(config)
    for svc in ("cronjobs", "cronjobshell", "queuejobs"):
        if svc not in declared:
            continue
        try:
            __dc(config, ["start", svc])
        except subprocess.CalledProcessError:
            pass


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

    # Redirect legacy service names to the in-container supervisor (v14+).
    # For v11/v13 those names are real compose services, no redirect.
    legacy, machines = _legacy_role_match(config, machines)
    for m in legacy:
        role = _resolve_legacy_role(m)
        if not _supervisor_restart_role(config, role):
            click.secho(
                f"WARNING: could not confirm restart of role {role}.",
                fg="yellow",
            )
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
    try:
        __dc(config, ["rm", "-f"] + machines, profile=profile)
    except subprocess.CalledProcessError:
        # Docker race condition: container removal already in progress — harmless
        click.secho(
            "rm: container already being removed, ignoring.", fg="yellow"
        )


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
    no_zodoo_pull=False,
    no_zodoo_push=False,
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

    _ensure_prebuilt_python_image(config, _arch, pull=pull)

    # Build the per-version base image first when one is defined for this
    # Odoo version. The project's compose Dockerfile references the
    # resolved base tag via `FROM ${BASE_TAG}` (baked in by composer).
    _ensure_base_image_for_build(
        config,
        machines,
        no_zodoo_pull=no_zodoo_pull,
        no_zodoo_push=no_zodoo_push,
    )

    # `docker buildx bake` (COMPOSE_BAKE=true) does not reliably auto-populate
    # global `ARG TARGETARCH` from DOCKER_DEFAULT_PLATFORM, so a Dockerfile
    # `FROM …/zodoo/python:${ODOO_PYTHON_VERSION}-${TARGETARCH}` resolves with
    # an empty arch suffix. Pass it explicitly.
    options = options + ["--build-arg", f"TARGETARCH={_arch}"]

    build_env = {
        "ODOO_VERSION": config.odoo_version,
        "DOCKER_DEFAULT_PLATFORM": f"linux/{_arch}",
        "DOCKER_BUILDKIT": "1",
    }
    _build_with_network_retry(config, options, machines, build_env)


_BUILD_NETWORK_ERROR_PATTERN = (
    r"api\.launchpad\.net|"
    r"ServerNotFoundError|"
    r"Temporary failure resolving|"
    r"[Cc]ould not resolve host|"
    r"[Cc]ould not connect to (?:archive|ports|security)\.ubuntu\.com|"
    r"deadsnakes"
)


def _is_buildx_available():
    try:
        subprocess.check_output(
            ["docker", "buildx", "version"], stderr=subprocess.DEVNULL
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False


def _compose_opts_to_bake_opts(options):
    """Translate ``docker compose build`` flags to ``docker buildx bake`` flags."""
    bake_opts = []
    i = 0
    while i < len(options):
        opt = options[i]
        if opt in ("--no-cache", "--pull"):
            bake_opts.append(opt)
        elif opt == "--build-arg" and i + 1 < len(options):
            bake_opts += ["--set", f"*.args.{options[i + 1]}"]
            i += 1
        i += 1
    return bake_opts


def _collect_bake_fs_reads(bake_files):
    """Return the set of paths that should be passed to bake via
    ``--allow=fs.read=…`` so it doesn't warn about reading outside the
    bake file's directory.

    Walks each compose file referenced in ``bake_files`` and collects
    every ``build.context``, ``build.dockerfile`` and bind-mount source
    that lives outside the compose file's own directory. Resolves
    symlinks and "../" segments so the values match what bake sees at
    runtime.
    """
    paths = set()
    files = []
    idx = 0
    while idx < len(bake_files):
        if bake_files[idx] == "-f" and idx + 1 < len(bake_files):
            files.append(bake_files[idx + 1])
            idx += 2
        else:
            idx += 1
    try:
        import yaml
    except ImportError:
        return paths

    def _resolve(value):
        if not value:
            return None
        try:
            return str(Path(value).expanduser().resolve())
        except (OSError, RuntimeError):
            return None

    for compose_path in files:
        try:
            with open(compose_path) as fh:
                data = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        services = data.get("services") or {}
        if not isinstance(services, dict):
            continue
        for svc in services.values():
            if not isinstance(svc, dict):
                continue
            build = svc.get("build")
            if isinstance(build, dict):
                for key in ("context", "dockerfile"):
                    resolved = _resolve(build.get(key))
                    if resolved:
                        paths.add(resolved)
            elif isinstance(build, str):
                resolved = _resolve(build)
                if resolved:
                    paths.add(resolved)
            for mount in svc.get("volumes") or []:
                if isinstance(mount, dict):
                    resolved = _resolve(mount.get("source"))
                elif isinstance(mount, str) and ":" in mount:
                    resolved = _resolve(mount.split(":", 1)[0])
                else:
                    resolved = None
                if resolved and Path(resolved).exists():
                    paths.add(resolved)
    return paths


def _build_with_network_retry(config, options, machines, env):
    """Run the build; retry once with ``--no-cache`` when the failure looks like
    a transient network/PPA glitch.

    Uses ``docker buildx bake`` when buildx is available (reads the compose
    file natively), otherwise falls back to ``docker compose build``.
    """
    import re

    pattern = re.compile(_BUILD_NETWORK_ERROR_PATTERN)
    ensure_project_name(config)
    # BUILDX_BAKE_ENTITLEMENTS_FS=0 stops bake from *failing* on filesystem
    # entitlement checks, but it still prints a "build is requesting
    # privileges for following possibly insecure capabilities" warning for
    # every context/dockerfile outside the bake file's directory. We
    # enumerate every referenced path below as `--allow=fs.read=…` so the
    # warning stays quiet; the env var is kept as a safety net in case the
    # enumeration misses a path on some compose layout.
    full_env = _merge_env_dict(
        _set_default_envs({**env, "BUILDX_BAKE_ENTITLEMENTS_FS": "0"})
    )
    use_buildx = _is_buildx_available()

    def _run(extra_options):
        from .consts import BUILD_PROFILES

        if use_buildx:
            # Only the -f paths are taken from this, so the profiles do not
            # filter anything here: `docker buildx bake` has no concept of
            # compose profiles and builds every service with a build section.
            # Verified against docker compose v2 — a profile-gated service
            # still shows up in bake's default group.
            compose_cmd = __get_cmd(config, profile=BUILD_PROFILES)
            bake_files = []
            idx = 0
            while idx < len(compose_cmd):
                if compose_cmd[idx] == "-f" and idx + 1 < len(compose_cmd):
                    bake_files += ["-f", compose_cmd[idx + 1]]
                    idx += 2
                else:
                    idx += 1
            tags_opts = [
                f"--set={m}.tags={config.project_name}-{m}" for m in machines
            ]
            allow_opts = [
                f"--allow=fs.read={p}"
                for p in sorted(_collect_bake_fs_reads(bake_files))
            ]
            # Pin the target platform for buildx bake to whatever
            # DOCKER_DEFAULT_PLATFORM was set in the project env — otherwise
            # bake defaults to the builder host's architecture, which breaks
            # cross-builds (e.g. arm64 dev box → amd64 registry images).
            platform_opts = []
            _default_platform = full_env.get("DOCKER_DEFAULT_PLATFORM")
            if _default_platform:
                platform_opts = [f"--set=*.platform={_default_platform}"]
            cmd = (
                ["docker", "buildx", "bake"]
                + allow_opts
                + ["--load"]
                + bake_files
                + _compose_opts_to_bake_opts(extra_options)
                + platform_opts
                + tags_opts
                + list(machines)
            )
        else:
            cmd = (
                # Here the profiles do filter: without BUILD_ONLY_PROFILE
                # compose would skip the tool images entirely.
                __get_cmd(config, profile=BUILD_PROFILES)
                + ["build"]
                + extra_options
                + list(machines)
            )
        captured = []

        if sys.stdout.isatty():
            import pty

            master_fd, slave_fd = pty.openpty()
            proc = subprocess.Popen(
                cmd,
                env=full_env,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
            os.close(slave_fd)
            while True:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                decoded = data.decode("utf-8", errors="replace")
                sys.stdout.write(decoded)
                sys.stdout.flush()
                captured.append(decoded)
            os.close(master_fd)
            proc.wait()
        else:
            proc = subprocess.Popen(
                cmd,
                env=full_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                decoded = raw.decode("utf-8", errors="replace")
                sys.stdout.write(decoded)
                sys.stdout.flush()
                captured.append(decoded)
            proc.wait()

        return proc.returncode, "".join(captured), cmd

    rc, log, cmd = _run(options)
    if rc == 0:
        return
    if "--no-cache" not in options and pattern.search(log):
        click.secho(
            "Build failed with a transient network error (Launchpad / DNS) — "
            "retrying once with --no-cache to refresh the apt layer ...",
            fg="yellow",
        )
        rc2, _, cmd2 = _run(options + ["--no-cache"])
        if rc2 == 0:
            return
        raise subprocess.CalledProcessError(rc2, cmd2)
    raise subprocess.CalledProcessError(rc, cmd)


def _locate_odoo_config_dockerfile(images_dir, odoo_version):
    """Return the Dockerfile path for the requested Odoo version, or None.

    The on-disk layout is inconsistent: very old versions live under
    ``odoo/config/6.0/`` (float-like names) while modern ones live under
    ``odoo/config/19/`` (int-like names). ``config.odoo_version`` is always
    a float (parsed from MANIFEST), so we try the float spelling first and
    fall back to the int spelling when the version is integral.
    """
    candidates = [str(odoo_version)]
    try:
        as_float = float(odoo_version)
        if as_float.is_integer():
            candidates.append(str(int(as_float)))
    except (TypeError, ValueError):
        pass
    for variant in candidates:
        path = images_dir / "odoo" / "config" / variant / "Dockerfile"
        if path.exists():
            return path
    return None


def _ensure_prebuilt_python_image(config, arch, pull=False):
    """Auto-build the prebuilt Python image if it's missing in the registry.

    Odoo >= 19 builds derive their Python interpreter from
    ``${ZODOO_REGISTRY_URL}/zodoo/python:${ODOO_PYTHON_VERSION}-${TARGETARCH}``.
    If that image is not available in the configured registry, BuildKit
    fails with a cryptic ``not found`` error half-way through the build.

    This hook checks the registry up-front via ``docker manifest inspect``
    and, on miss, transparently runs ``images/python_prebuilt/build.sh``
    to build & push the image before continuing with the regular build.

    When the registry cannot be asked at all (401 because docker was never
    logged in, DNS, TLS), it logs in with the credentials from the settings
    and retries; if it still cannot ask, a local copy of the image is used
    rather than rebuilding. ``pull`` mirrors ``odoo build --pull``, which
    makes BuildKit re-resolve every ``FROM`` against the registry — the local
    copy is then not usable and the shortcut is skipped.

    Silently no-ops when:
      - the prebuilt-python infrastructure is not present (older image set),
      - the project's Odoo Dockerfile does not reference the prebuilt image,
      - ``ODOO_PYTHON_VERSION`` or ``ZODOO_REGISTRY_URL`` are unset.
    """
    images_dir = Path(config.dirs["images"])
    script = images_dir / "python_prebuilt" / "build.sh"
    if not script.exists():
        return

    # Check both the legacy monolithic Dockerfile and the new
    # Dockerfile.base — either may reference the prebuilt python image.
    # For Odoo 16/17/18 the prebuilt-python reference now lives in
    # Dockerfile.base only; for 19 it sits in both. Bail out only when
    # *neither* file mentions the prebuilt image.
    from .lib_base_image import base_dockerfile_path

    referencing_files = []
    legacy_df = _locate_odoo_config_dockerfile(images_dir, config.odoo_version)
    if legacy_df is not None:
        referencing_files.append(legacy_df)
    base_df = base_dockerfile_path(config.odoo_version, images_dir=images_dir)
    if base_df is not None:
        referencing_files.append(base_df)
    if not any("zodoo/python:" in p.read_text() for p in referencing_files):
        return

    python_version = getattr(config, "ODOO_PYTHON_VERSION", None)
    # A URL scheme in the setting would produce an invalid image reference and
    # break both `docker manifest inspect` and the build with a cryptic error;
    # _validate_registry_url raises a clear message instead.
    from .lib_zodoo_registry import _validate_registry_url

    registry_url = _validate_registry_url(
        getattr(config, "ZODOO_REGISTRY_URL", None)
    ).rstrip("/")
    if not python_version or not registry_url:
        return

    image = f"{registry_url}/zodoo/python:{python_version}-{arch}"

    from .lib_zodoo_registry import (
        inspect_registry_manifest,
        local_image_exists,
    )

    # Whether this host may push is decided by the credentials it had before
    # we did anything. On macOS the login only writes ~/.docker/config.json
    # without asking the registry (the keychain helper cannot be used over
    # SSH), so credentials the registry rejects would still look like push
    # rights here — and `build.sh --push` would abort a build that used to
    # complete local-only.
    had_credentials = _has_registry_credentials(registry_url)

    status, output = inspect_registry_manifest(image)
    if status == "unreachable" and _ensure_registry_login(
        config, registry_url
    ):
        # docker did not know the credentials from our settings yet, so the
        # query came back 401 — which looks exactly like a cache miss. Now
        # that we are logged in, ask once more.
        status, output = inspect_registry_manifest(image)

    if status == "ok":
        return

    if status == "unreachable":
        click.secho(
            f"Could not ask the registry whether {image} exists:\n"
            f"  {output.splitlines()[-1] if output else 'unknown error'}\n"
            "This is not a cache miss — it is an authentication or network "
            "problem. Check ZODOO_REGISTRY_USERNAME / ZODOO_REGISTRY_PASSWORD "
            "in your settings.",
            fg="red",
        )
        # We could not ask, so we do not know that the image is missing.
        # If it is in the local store, a FROM resolves against it and there
        # is nothing to build. Not with --pull though: that makes BuildKit
        # re-resolve every FROM against the registry, so the local copy
        # would not be used.
        if not pull and local_image_exists(image, arch=arch):
            click.secho(
                f"Image is in the local docker store: {image} — using that "
                "instead of rebuilding.",
                fg="green",
            )
            return

    # The image is not in the registry (or we could not ask). Build it
    # locally so the subsequent `docker compose build` can FROM-it from the
    # local daemon. Pushing to the registry is optional — only attempt it if
    # we actually have credentials for that registry, otherwise CI
    # runners (no creds) would fail here with a 401 even though the
    # build succeeded locally. A registry we could not even talk to is not
    # worth trying to push to either.
    pushable = status == "missing" and had_credentials
    extra_args = ["--push"] if pushable else []
    reason = (
        f"not found in registry: {image}"
        if status == "missing"
        else f"could not be fetched from the registry: {image}"
    )
    click.secho(
        f"Prebuilt Python image {reason}\n"
        f"Building it now via {script}"
        + (
            " (and pushing to registry)"
            if pushable
            else " (local-only, skipping push — "
            + (
                "the registry did not answer"
                if status == "unreachable"
                else "no registry credentials configured for this host"
            )
            + ")"
        )
        + " ...",
        fg="yellow",
    )
    # Pass the registry URL via env so build.sh doesn't need to read
    # ~/.odoo/settings (CI runners may not have a user-level settings
    # file, but the project config we just resolved does have it).
    env = {**os.environ, "ZODOO_REGISTRY_URL": registry_url}
    subprocess.check_call([str(script), python_version, *extra_args], env=env)
    click.secho(
        f"Prebuilt Python image built{' and pushed' if pushable else ''}: "
        f"{image}",
        fg="green",
    )


def _ensure_base_image_for_build(
    config, machines, no_zodoo_pull=False, no_zodoo_push=False
):
    """Build/locate the per-version Odoo base image before composing.

    Only kicks in when ``odoo`` is among the machines being built (or when
    ``machines`` is empty = build everything) AND the project's Odoo
    version has a ``Dockerfile.base``. Otherwise no-op.

    Prints the hash inputs and resolved tag so users can see what's
    being reused vs. rebuilt. ``no_zodoo_pull`` / ``no_zodoo_push``
    mirror the matching flags on ``odoo build``.
    """
    if machines and "odoo" not in machines:
        return

    from .lib_base_image import compute_base_inputs, ensure_base_image

    inputs = compute_base_inputs(config)
    if inputs is None:
        return

    click.secho("─" * 72, fg="cyan")
    click.secho("Odoo base image", fg="cyan", bold=True)
    click.secho(
        f"  odoo_version:       {inputs['odoo_version']}\n"
        f"  python_version:     {inputs['python_version']}\n"
        f"  framework reqs:     "
        f"{len(inputs['framework_requirements'].splitlines())} lines\n"
        f"  Dockerfile.base:    {inputs['dockerfile_base_path']}\n"
        f"  base_hash:          {inputs['base_hash']}\n"
        f"  base_image_tag:     {inputs['tag']}",
        fg="cyan",
    )
    click.secho("─" * 72, fg="cyan")

    ensure_base_image(
        config,
        try_pull=not no_zodoo_pull,
        enqueue_push=not no_zodoo_push,
    )


def _ensure_registry_login(config, registry_url):
    """`docker login` with the credentials from our settings.

    zodoo has the credentials in its settings, but docker only knows what is
    in `~/.docker/config.json` (or its credential helper). On a host that was
    never logged in, every registry query fails with a 401 —
    indistinguishable from "image not in registry" — so cache hits turn into
    full rebuilds.

    Called only after a query already failed, so a host that is logged in
    (via credsStore or otherwise) is never touched. Returns True when a login
    was performed and the failed query is worth repeating. Best effort: a
    failing login must not break the build, the local build path still works.
    """
    from .lib_zodoo_registry import login_with_settings_credentials

    try:
        return login_with_settings_credentials(config, registry_url)
    except (subprocess.CalledProcessError, OSError) as ex:
        click.secho(
            f"Could not log in to registry {registry_url}: {ex}", fg="yellow"
        )
        return False


def _has_registry_credentials(registry_url):
    """Return True if `~/.docker/config.json` has an `auths` entry for
    `registry_url` (or `registry_url:443` — docker normalises the port).

    Used to decide whether `python_prebuilt/build.sh --push` makes sense
    on this host. Without this guard CI runners (which have no
    registry creds) would fail the auto-build hook with a cryptic 401
    even though the local-only build would have been enough for the
    subsequent `docker compose build` to consume the image from the
    local daemon.
    """
    import json

    cfg_path = Path.home() / ".docker" / "config.json"
    if not cfg_path.exists():
        return False
    try:
        cfg = json.loads(cfg_path.read_text())
    except (OSError, ValueError):
        return False
    auths = (cfg or {}).get("auths") or {}
    needle = registry_url.rstrip("/")
    candidates = {
        needle,
        f"{needle}:443",
        f"https://{needle}",
        f"http://{needle}",
    }
    return any(c in auths for c in candidates)


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


def shell(config, command="", queuejobs=False, debug=False, debug_port=None):
    import time as _time

    def _ts(label):
        click.secho(
            f"[shell-trace] {label:50s}  t={_time.monotonic():.3f}s",
            fg="yellow",
            err=True,
        )

    _ts("shell() called (host side)")
    from .lib_standard_image import abort_if_standard_image

    abort_if_standard_image(
        config,
        "odoo shell",
        hint=(
            "Ersatz: `odoo psql` fuer SQL, oder direkt im Container "
            "`docker compose exec odoo odoo shell -c /etc/odoo/odoo.conf "
            "-d <db>`."
        ),
    )
    # Only take the in-container shortcut when we are actually inside the
    # odoo container (where /odoolib exists). _is_in_container() is True for
    # ANY container - e.g. the instanceconsole - which would wrongly try to
    # exec a non-existent /odoolib/entrypoint.sh instead of spawning a shell
    # in the instance's stack via docker-compose.
    if os.path.exists("/odoolib/entrypoint.sh"):
        cmdline = ["/odoolib/entrypoint.sh", "/odoolib/shell.py"]
        if command:
            cmdline += [command]
        _ts("in-container shortcut: running entrypoint.sh")
        res = subprocess.run(cmdline)
        _ts("in-container shortcut: done")
        return res.returncode
    cmd = [
        "run",
        "--rm",
    ]
    if get_docker_version()[0] >= 26:
        cmd += ["-it"]

    if debug:
        # Publish the in-container debugpy port (5678) on its own host port
        # so VSCode can attach. Must differ from the always-published odoo
        # service debug port (PROXY/debug mapping) to avoid a bind clash.
        if not debug_port:
            abort("--debug requires --debug-port")
        cmd += ["-p", f"{debug_port}:5678", "-e", "ODOO_SHELL_DEBUG=1"]

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
    _ts("docker compose run: starting")
    rc = __cmd_interactive(config, *(cmd + [command]))
    _ts("docker compose run: returned")
    return rc
