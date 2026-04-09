import ast
import sys
import time
import click
from pathlib import Path

import re
import os
from .cli import cli, pass_config, Commands
from .lib_clickhelpers import AliasedGroup
from .tools import execute_script
from .tools import force_input_hostname
import subprocess
from .tools import abort
from .tools import ensure_project_name
from .tools import print_prod_env
from .tools import _shell_complete_machines
from .tools import _shell_complete_services
from .tools import __rmtree


@cli.group(
    cls=AliasedGroup,
    help="Docker container management (up, down, build, exec, logs, ...).",
)
@pass_config
def docker(config):
    pass


@docker.command(help="Pull all Docker images from the registry or Docker Hub.")
@pass_config
@click.pass_context
def pull(ctx, config):
    ensure_project_name(config)
    if config.use_docker:
        from .lib_control_with_docker import pull as lib_pull

        return lib_pull(ctx, config)


@docker.command(
    help="Start containers in dev mode (combines build + up + watch)."
)
@click.option("-b", "--build", is_flag=True)
@click.option("-k", "--kill", is_flag=True)
@pass_config
@click.pass_context
def dev(ctx, config, build, kill):
    ensure_project_name(config)
    if config.use_docker:
        from .lib_control_with_docker import dev as lib_dev

        return lib_dev(ctx, config, build, kill=kill)


@docker.command(name="ps", help="List running containers for this project.")
@pass_config
def ps(config):
    ensure_project_name(config)
    if config.use_docker:
        from .lib_control_with_docker import ps as lib_ps

        return lib_ps(config)


@docker.command(
    name="exec", help="Execute a command inside a running container."
)
@click.argument(
    "machine", required=True, shell_complete=_shell_complete_machines
)
@click.argument("args", nargs=-1)
@click.option("-u", "--user")
@click.option(
    "-I", "--non-interactive", is_flag=True, help="Run in interactive mode"
)
@pass_config
def execute(config, machine, user, non_interactive, args):
    ensure_project_name(config)
    if config.use_docker:
        from .lib_control_with_docker import execute as lib_execute

        lib_execute(
            config, machine, args, user=user, interactive=not non_interactive
        )


@docker.command(
    name="kill",
    help="Send SIGKILL to containers. Use -b/--brutal to skip graceful shutdown.",
)
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_machines)
@click.option("-b", "--brutal", is_flag=True, help="dont wait")
@click.option("-p", "--profile")
@pass_config
@click.pass_context
def do_kill(ctx, config, machines, brutal, profile):
    ensure_project_name(config)
    if config.devmode:
        click.secho("Being brutal because in devmode", fg="red")
        brutal = True
    if config.use_docker:
        from .lib_control_with_docker import do_kill as lib_do_kill

        lib_do_kill(ctx, config, machines, brutal=brutal, profile=profile)


@docker.command()
@click.option("-d", "--dry-run", is_flag=True)
@pass_config
@click.pass_context
def remove_volumes(ctx, config, dry_run):
    """
    Experience: docker compose down -v lets leftovers since june/2023
    At restore everything must be cleaned up.
    """
    ensure_project_name(config)
    if not config.devmode:
        if not config.force:
            abort("Please provide force option on non dev systems")
    if not config.use_docker:
        return
    subprocess.check_call(["sync"])
    volumes = _get_project_volumes(config)
    for vol in volumes:
        click.secho(f"Removing: {vol}", fg="red")
        if not dry_run:
            rc = subprocess.run(
                ["docker", "volume", "rm", "-f", vol],
                encoding="utf8",
                capture_output=True,
            )
            if rc.returncode:
                output = rc.stderr
                for group in re.findall(r"(\[[^\]]*])", output):
                    container_id = group[1:-1]
                    subprocess.run(["docker", "kill", container_id])
                    subprocess.check_call(
                        ["docker", "rm", "-fv", container_id]
                    )
                    counter = 0
                    while counter < 5:
                        try:
                            output = subprocess.check_output(
                                ["docker", "volume", "rm", "-f", vol],
                                encoding="utf8",
                            )
                            break
                        except Exception:
                            click.secho(
                                f"Removing the volume {vol} failed - waiting and retrying.",
                                fg="red",
                            )
                            time.sleep(2)
                            counter += 1
                    else:
                        click.secho(
                            f"Volume {vol} could not be removed after retries. "
                            "Trying fix_permissions...",
                            fg="yellow",
                        )
                        from .lib_setup import _fix_permissions

                        vol_path = subprocess.run(
                            [
                                "docker",
                                "volume",
                                "inspect",
                                "--format",
                                "{{ .Mountpoint }}",
                                vol,
                            ],
                            encoding="utf8",
                            capture_output=True,
                        )
                        if (
                            vol_path.returncode == 0
                            and vol_path.stdout.strip()
                        ):
                            _fix_permissions(config, [vol_path.stdout.strip()])
                        try:
                            subprocess.check_output(
                                ["docker", "volume", "rm", "-f", vol],
                                encoding="utf8",
                            )
                            click.secho(
                                f"  Removed {vol} after fix_permissions.",
                                fg="green",
                            )
                        except Exception:
                            click.secho(
                                f"  Volume {vol} still could not be removed.",
                                fg="red",
                            )

        if dry_run:
            click.secho("Dry Run - didnt do it.")


@docker.command(
    help="Force-kill containers immediately (no graceful shutdown)."
)
@pass_config
@click.argument("machine", nargs=-1, shell_complete=_shell_complete_machines)
@click.pass_context
def force_kill(ctx, config, machine):
    if config.use_docker:
        from .lib_control_with_docker import force_kill as lib_force_kill

        lib_force_kill(ctx, config, machine)


@docker.command(
    help="Wait until the postgres container is ready to accept connections."
)
@pass_config
def wait_for_container_postgres(config):
    if config.use_docker:
        from .lib_control_with_docker import (
            wait_for_container_postgres as lib_wait_for_container_postgres,
        )

        lib_wait_for_container_postgres(config)


@docker.command()
@click.argument("host", required=True)
@click.argument("port", required=True)
@pass_config
def wait_for_port(config, host, port):
    ensure_project_name(config)
    if config.use_docker:
        from .lib_control_with_docker import wait_for_port as lib_wait_for_port

        lib_wait_for_port(host, port)


@docker.command(help="Recreate containers without rebuilding images.")
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_services)
@pass_config
@click.pass_context
def recreate(ctx, config, machines):
    ensure_project_name(config)
    if config.use_docker:
        from .lib_control_with_docker import recreate as lib_recreate

        lib_recreate(ctx, config, machines)


@docker.command(
    help="Start containers. Use -d to run in background (daemon mode)."
)
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_services)
@click.option("-d", "--daemon", is_flag=True)
@click.option("--force-recreate", is_flag=True)
@click.option("--no-recreate", is_flag=True)
@pass_config
@click.pass_context
def up(
    ctx,
    config,
    machines,
    daemon,
    force_recreate,
    no_recreate,
    allow_build=False,
):
    ensure_project_name(config)
    from .lib_setup import _status
    from .lib_control_with_docker import up as lib_up

    lib_up(
        ctx,
        config,
        machines,
        daemon,
        remove_orphans=True,
        force_recreate=force_recreate,
        no_recreate=no_recreate,
        allow_build=allow_build,
    )
    execute_script(
        config,
        config.files["after_up_script"],
        "Possible after up script here:",
    )
    if daemon:
        _status(config)


@docker.command(
    help="Stop and remove containers. Use -v to also remove volumes (destroys data!). Requires -f on production."
)
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_services)
@click.option("-v", "--volumes", is_flag=True)
@click.option("--remove-orphans", is_flag=True)
@click.option("--postgres-volume", is_flag=True)
@click.option("--cleanup-config", is_flag=True)
@click.option("--cleanup-files", is_flag=True)
@pass_config
@click.pass_context
def down(
    ctx,
    config,
    machines,
    volumes,
    remove_orphans,
    postgres_volume,
    cleanup_config,
    cleanup_files,
):
    ensure_project_name(config)
    from .lib_control_with_docker import down as lib_down
    from .lib_db_snapshots_docker_zfs import NotZFS

    if not config.devmode:
        if not config.force:
            abort("Please provide force option on production systems")

    print_prod_env(config)

    if not config.devmode and volumes:
        force_input_hostname()

    if postgres_volume or volumes:
        if postgres_volume:
            if not config.force:
                abort("Please use force when call with postgres volume")
        lib_down(ctx, config, machines, volumes=False, remove_orphans=False)
        try:
            Commands.invoke(ctx, "remove_postgres_volume")
        except NotZFS:
            pass

    lib_down(ctx, config, machines, volumes, remove_orphans)
    if cleanup_files:
        # try also to delete the run dir and filestore
        try:
            _cleanup_local_files(ctx, config)
        except Exception as ex:
            click.secho(
                f"Errors happened at cleaning local files. Ignoring. {ex}",
                fg="red",
            )
    if cleanup_config:
        _cleanup_config_files(ctx, config)


@docker.command(
    help="Stop containers without removing them (state is preserved)."
)
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_machines)
@pass_config
@click.pass_context
def stop(ctx, config, machines):
    ensure_project_name(config)
    from .lib_control_with_docker import stop as lib_stop

    lib_stop(ctx, config, machines)


@docker.command(help="Rebuild images and recreate containers.")
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_machines)
@pass_config
@click.pass_context
def rebuild(ctx, config, machines):
    ensure_project_name(config)
    from .lib_control_with_docker import rebuild as lib_rebuild

    lib_rebuild(ctx, config, machines)


@docker.command(
    help="Restart containers. In devmode uses brutal (SIGKILL) restart."
)
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_machines)
@click.option("-p", "--profile", default="auto")
@click.option(
    "-C", "--force-recreate", is_flag=True, help="Recreate containers"
)
@click.option(
    "-R", "--no-recreate", is_flag=True, help="Dont recreate containers"
)
@pass_config
@click.pass_context
def restart(ctx, config, machines, profile, force_recreate, no_recreate):
    ensure_project_name(config)
    from .lib_control_with_docker import restart as lib_restart

    brutal = config.devmode
    lib_restart(
        ctx,
        config,
        machines,
        profile=profile,
        brutal=brutal,
        force_recreate=force_recreate,
        no_recreate=no_recreate,
    )


@docker.command(help="Remove stopped containers.")
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_machines)
@click.option("-p", "--profile", default="auto")
@pass_config
@click.pass_context
def rm(ctx, config, machines, profile):
    ensure_project_name(config)
    from .lib_control_with_docker import rm as lib_rm

    lib_rm(ctx, config, machines, profile=profile)


@docker.command(help="Attach to a running container's stdin/stdout.")
@click.argument(
    "machine", required=True, shell_complete=_shell_complete_machines
)
@pass_config
@click.pass_context
def attach(ctx, config, machine):
    ensure_project_name(config)
    from .lib_control_with_docker import attach as lib_attach

    lib_attach(ctx, config, machine)


@docker.command()
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_services)
@click.option("--no-cache", is_flag=True)
@click.option("--pull", is_flag=True)
@click.option("--push", is_flag=True)
@click.option("-p", "--plain", is_flag=True)
@click.option("-s", "--include-source", is_flag=True)
@click.option(
    "--platform",
    type=click.Choice(["linux/amd64", "linux/arm64"], case_sensitive=False),
    default=None,
    help="Build for a specific platform",
)
@click.option(
    "--no-zodoo-pull",
    is_flag=True,
    help="Skip pulling from zodoo registry (force local build)",
)
@click.option(
    "--registry-only",
    is_flag=True,
    help="Only pull from zodoo registry, never build locally. Fails if image not found.",
)
@click.option(
    "--no-zodoo-push",
    is_flag=True,
    help="Skip pushing built images to zodoo registry after build",
)
@click.option(
    "--suppress-other-platform-build",
    is_flag=True,
    help="Skip cross-architecture (QEMU/buildx) build for the other platform.",
)
@pass_config
@click.pass_context
def build(
    ctx,
    config,
    machines,
    pull,
    no_cache,
    push,
    plain,
    include_source,
    platform,
    no_zodoo_pull,
    no_zodoo_push,
    registry_only,
    suppress_other_platform_build,
):
    from .lib_cached_build import start_squid_proxy, start_proxpi
    from .lib_zodoo_registry import try_pull_from_zodoo_registry
    from .lib_zodoo_registry import push_to_zodoo_registry
    from .lib_docker_registry import disable_keychain_credential_store

    from .myconfigparser import MyConfigParser

    settings = MyConfigParser(config.files["settings"])

    ensure_project_name(config)
    disable_keychain_credential_store()
    if plain:
        os.environ["BUILDKIT_PROGRESS"] = "plain"
    from .lib_control_with_docker import build as lib_build

    if not machines:
        compose = load_compose(config)
        machines = []
        for service in compose["services"]:
            if compose["services"][service].get("build"):
                machines.append(service)

    # Try pulling from zodoo registry before building
    already_pulled = []
    if not no_zodoo_pull:
        already_pulled = try_pull_from_zodoo_registry(config, machines)

    machines_to_build = [m for m in machines if m not in already_pulled]

    if machines_to_build:
        if settings.get("RUN_APT_CACHER") in ["1", ""]:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=2) as pool:
                pool.submit(start_squid_proxy, config)
                pool.submit(start_proxpi, config)
                pool.shutdown(wait=True)

        lib_build(
            ctx,
            config,
            machines_to_build,
            pull,
            no_cache,
            push,
            include_source,
            platform=platform,
        )

        # Push built images to zodoo registry
        if not no_zodoo_push:
            push_to_zodoo_registry(
                config,
                machines_to_build,
                suppress_other_platform=suppress_other_platform_build,
            )
    elif already_pulled:
        click.secho(
            "All images pulled from zodoo registry, no build needed.",
            fg="green",
        )


@docker.command(
    name="zodoo-push", help="Push locally built images to the zodoo registry."
)
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_services)
@pass_config
def zodoo_push(config, machines):
    from .lib_zodoo_registry import push_to_zodoo_registry, get_build_services

    ensure_project_name(config)
    if not machines:
        machines = get_build_services(config)
    push_to_zodoo_registry(config, machines)


@docker.command(name="zodoo-pull", help="Pull images from the zodoo registry.")
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_services)
@pass_config
def zodoo_pull(config, machines):
    from .lib_zodoo_registry import (
        try_pull_from_zodoo_registry,
        get_build_services,
    )

    ensure_project_name(config)
    if not machines:
        machines = get_build_services(config)
    pulled = try_pull_from_zodoo_registry(config, machines)
    if not pulled:
        click.secho("No images pulled from zodoo registry.", fg="yellow")


def load_compose(config):
    import yaml

    return yaml.safe_load(config.files["docker_compose"].read_text())


@docker.command(
    help=(
        "Start a container in debug mode. Inside the prompt type 'debug' + ENTER. "
        "Then open https://<host>/debugpython in your browser to route your session "
        "to the debug container. Reset with https://<host>/debugpython_off."
    )
)
@click.argument(
    "machine", required=True, shell_complete=_shell_complete_services
)
@click.option("-c", "--command", required=False, help="Like /odoolib/debug.py")
@click.option("-p", "--ports", is_flag=True, help="With Port 33284")
@click.option("--port", help="Define the debug port")
@click.option(
    "--set-docker-command", is_flag=True, help="Replaces docker command"
)
@pass_config
@click.pass_context
def debug(ctx, config, machine, ports, command, port, set_docker_command):
    ensure_project_name(config)
    from .lib_control_with_docker import debug as lib_debug

    if (command or "").startswith("["):
        command = ast.literal_eval(command)

    if port:
        try:
            port = int(port)
        except Exception:
            abort(f"Cannot convert port {port} to int.")

    lib_debug(
        ctx,
        config,
        machine,
        ports=port,
        cmd=command,
        set_docker_command=set_docker_command,
    )


@cli.command(help="Run a one-off command in a new container instance.")
@click.argument(
    "machine", required=True, shell_complete=_shell_complete_services
)
@click.argument("args", nargs=-1)
@click.option("-d", "--detached", is_flag=True)
@click.option("-n", "--name")
@pass_config
@click.pass_context
def run(ctx, config, machine, detached, name, args, **kwparams):
    ensure_project_name(config)
    from .lib_control_with_docker import run as lib_run

    lib_run(
        ctx, config, machine, args, detached=detached, name=name, **kwparams
    )


@cli.command(help="Run a bash shell in a new container instance.")
@click.argument(
    "machine", required=True, shell_complete=_shell_complete_services
)
@click.argument("args", nargs=-1)
@pass_config
@click.pass_context
def runbash(ctx, config, machine, args, **kwparams):
    ensure_project_name(config)
    from .lib_control_with_docker import runbash as lib_runbash

    lib_runbash(ctx, config, machine, args, **kwparams)


@cli.command(
    name="logs",
    help="Show container logs. Use -f to follow, -n for line count.",
)
@click.argument("machines", nargs=-1, shell_complete=_shell_complete_machines)
@click.option("-n", "--lines", "--tail", required=False, type=int, default=200)
@click.option("-f", "--follow", is_flag=True)
@pass_config
def logall(config, machines, follow, lines):
    ensure_project_name(config)
    from .lib_control_with_docker import logall as lib_logall

    lib_logall(config, machines, follow, lines)


@docker.command(
    help="Open an interactive Odoo Python shell inside the running container."
)
@click.argument("command", nargs=-1)
@click.option(
    "-q",
    "--queuejobs",
    is_flag=True,
    help=("Dont delay queuejobs / execute queuejob code"),
)
@pass_config
def shell(config, command, queuejobs):
    print_prod_env(config)

    ensure_project_name(config)
    command = "\n".join(command)
    from .lib_control_with_docker import shell as lib_shell

    rc = lib_shell(config, command, queuejobs)
    if rc:
        sys.exit(rc)


# problem with stdin: debug then display missing
# @docker.command()
# @click.argument("id", required=True)
# @click.option("-q", "--queuejobs", is_flag=True, help=(
#     "Dont delay queuejobs / execute queuejob code"))
# @pass_config
# def queuejob(config, id, queuejobs):
#     if config.use_docker:
#         from .lib_control_with_docker import shell as lib_shell
#     command = (
#         f"env['queue.job'].browse({id}).run_now()"
#     )
#     lib_shell(command, queuejobs)


def _get_project_volumes(config):
    ensure_project_name(config)
    import yaml

    compose = yaml.safe_load(config.files["docker_compose"].read_text())
    full_volume_names = []
    for volume in compose["volumes"]:
        full_volume_names.append(f"{config.project_name}_{volume}")
    system_volumes = subprocess.check_output(
        ["docker", "volume", "ls"], encoding="utf8"
    ).splitlines()[1:]
    system_volumes = [x.split(" ")[-1] for x in system_volumes]
    system_volumes = [x for x in system_volumes if "_" in x]  # named volumes
    system_volumes = [
        x for x in system_volumes if x.startswith(config.project_name + "_")
    ]

    full_volume_names = list(
        filter(lambda x: x in system_volumes, full_volume_names)
    )
    return full_volume_names


@docker.command()
@click.option("-f", "--filter")
@pass_config
def show_volumes(config, filter):
    from tabulate import tabulate
    from .lib_control_with_docker import _get_volume_size

    volumes = _get_project_volumes(config)
    if filter:
        volumes = [x for x in volumes if filter in x]
    recs = []
    for volume in volumes:
        size = _get_volume_size(volume)
        recs.append((volume, size))
    click.echo(tabulate(recs, ["Volume", "Size"]))


@docker.command()
@click.argument("name", required=False)
@pass_config
@click.pass_context
def docker_sizes(context, config, name):
    from .tools import __dc_out
    from tabulate import tabulate

    output = __dc_out(config, ["config"])
    # docker compose config | grep "image:" | awk '{print $2}'
    # docker images --format "{{.Repository}}:{{.Tag}} Size: {{.Size}}"
    import yaml

    def match(fname):
        if not name:
            return True
        return name in fname

    image_names = list(
        filter(
            match,
            map(
                lambda x: f"{config.project_name}-{x}",
                yaml.safe_load(output)["services"].keys(),
            ),
        )
    )
    sizes = {}
    image_sizes = {}
    for imagename in image_names:
        click.secho(f"Analyzing {imagename} ...", fg="yellow")
        try:
            out = subprocess.check_output(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--entrypoint",
                    "/bin/sh",
                    imagename,
                    "-c",
                    "du -sh /",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            out = out.splitlines()
            if out:
                out = out[0]
        except subprocess.CalledProcessError as ex:
            out = ex.stdout.splitlines()
            if not out:
                continue
            out = out[0].strip()
        if not out:
            continue
        out = out.split("\t")[0]
        sizes[imagename] = out

        # Get total image size (includes all layers, even dead ones)
        try:
            img_size_bytes = subprocess.check_output(
                [
                    "docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{.Size}}",
                    imagename,
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            image_sizes[imagename] = int(img_size_bytes)
        except (subprocess.CalledProcessError, ValueError):
            pass

    def _format_bytes(b):
        for unit in ["B", "K", "M", "G", "T"]:
            if b < 1024:
                return f"{b:.1f}{unit}"
            b /= 1024
        return f"{b:.1f}P"

    def _parse_human_size(s):
        """Parse sizes like '1.2G', '500M', '100K' to bytes."""
        if not s:
            return None
        s = s.strip()
        units = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
        for suffix, mult in units.items():
            if s.upper().endswith(suffix):
                try:
                    return float(s[:-1]) * mult
                except ValueError:
                    return None
        try:
            return float(s)
        except ValueError:
            return None

    recs = []

    def _get_size(imagename):
        r = sizes.get(imagename, None)
        if r is None:
            r = sizes.get(imagename.replace("-", "_"), None)
        return r

    for name in sorted(image_names, key=lambda x: x):
        if not name:
            continue
        fs_size = _get_size(name)
        img_bytes = image_sizes.get(name)
        dead = ""
        if img_bytes and fs_size:
            fs_bytes = _parse_human_size(fs_size)
            if fs_bytes and img_bytes > fs_bytes:
                dead = _format_bytes(img_bytes - fs_bytes)
        img_total = _format_bytes(img_bytes) if img_bytes else ""
        recs.append((name, fs_size, img_total, dead))

    click.echo(
        tabulate(recs, ["Image Name", "FS Size", "Image Size", "Dead Layers"])
    )


def _cleanup_local_files(ctx, config):
    paths = []
    paths.append(Path(os.environ["HOST_RUN_DIR"]))
    paths.append(config.dirs["odoo_data_dir"] / "filestore" / config.dbname)
    _cleanup_paths(ctx, config, paths)


def _cleanup_config_files(ctx, config):
    paths = []
    paths.append(config.files["project_settings"])
    _cleanup_paths(ctx, config, paths)


def _cleanup_paths(ctx, config, paths):
    for path in paths:
        if path.is_dir():
            try:
                if path.exists():
                    __rmtree(config, path)
            except Exception as ex:
                click.secho(f"Failed to remove path {path}: {ex}", fg="red")
            else:
                click.secho(f"Removed directory: {path}", fg="yellow")
        else:
            content = ""
            try:
                if path.exists():
                    content = path.read_text()
                    path.unlink()
            except Exception as ex:
                click.secho(f"Failed to remove path {path}: {ex}", fg="red")
            else:
                click.secho(f"Removed file: {path}", fg="yellow")
                if content:
                    click.secho(f"Content was:\n{content}")


Commands.register(run)
Commands.register(runbash)
Commands.register(do_kill, "kill")
Commands.register(up)
Commands.register(wait_for_container_postgres)
Commands.register(build)
Commands.register(rm)
Commands.register(recreate)
Commands.register(debug)
Commands.register(restart)
Commands.register(shell, "odoo-shell")
Commands.register(down)
Commands.register(stop)
Commands.register(remove_volumes, "remove-volumes")
