from .tools import create_network

import arrow
import click
from .cli import cli, pass_config
from .lib_clickhelpers import AliasedGroup
import subprocess
from .tools import abort
import inquirer

APT_CACHER_CONTAINER_NAME = "squid-deb-proxy"
APT_VOLNAME = APT_CACHER_CONTAINER_NAME + "-data"
PROXPI_CONTAINER_NAME = "proxpi-cacher"
PROXPI_VOLNAME = PROXPI_CONTAINER_NAME + "-data"


@cli.group(cls=AliasedGroup)
@pass_config
def cache(config):
    pass


def _image_timestamp_stamp(image_name):
    out = subprocess.check_output(
        ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"],
        text=True,
        encoding="utf-8",
    )
    for image in out.splitlines():
        if not image:
            continue
        if image == f"{image_name}:latest":
            break
    else:
        return arrow.get("1980-04-04").datetime
    out = subprocess.check_output(
        [
            "docker",
            "image",
            "inspect",
            f"{image_name}:latest",
            "--format",
            "'{{.Created}}'",
        ],
        text=True,
        encoding="utf-8",
    )
    out = out.strip()
    return arrow.get(out).datetime


def start_container(
    config,
    container_name,
    image_name,
    build_path,
    network,
    port_mapping,
    startup=True,
    volmappings=None,
):
    """
    Start a Docker container with the specified parameters.

    :param stored_settings: put some settings inside the docker container to avoid build arguments for
        APT_PROXY_IP and PIP_PROXY_IP which scheduled permanent rebuild otherwise
    """

    def _get_container_id():
        # Check if container is already running
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={container_name}"],
            capture_output=True,
            text=True,
        )

        if result.stdout.strip():
            return result.stdout.splitlines()[0].split(" ")[0]
        return None

    create_network(network)
    image_was_updated = False

    if build_path:
        try:
            image_timestamp = _image_timestamp_stamp(image_name)
        except:
            image_timestamp = arrow.get("1980-04-04")
        cmd = ["docker", "build", "--load", "-t", image_name, "."]
        try:
            subprocess.run(cmd, check=True, cwd=build_path)
        except subprocess.CalledProcessError:
            subprocess.run(cmd + ["--no-cache"], check=True, cwd=build_path)
        image_timestamp2 = _image_timestamp_stamp(image_name)

        if image_timestamp != image_timestamp2:
            image_was_updated = True
            click.secho(
                f"Settings are updated so container will be restarted: {container_name}",
                fg="green",
            )
            click.secho("New Settings:", fg="green")
            click.secho(
                "============================================", fg="yellow"
            )

    if not startup:
        # important that config files are written above
        return

    def find_container(container_name, all=True):
        cmd = ["docker", "ps", "-q", "-f", f"name={container_name}"]
        if all:
            cmd += ["-a"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if result:
            return result
        return None

    def _start_container(image_name, container_name):
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "--network",
            network,
            "-p",
            port_mapping,
        ]
        for named_vol, dir in (volmappings or {}).items():
            cmd += ["-v", f"{named_vol}:{dir}"]

        cmd += [
            image_name,
        ]
        click.secho(f"Starting container '{container_name}'...", fg="blue")
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            abort(str(e))
        click.secho(
            f"Container '{container_name}' started on port {port_mapping}.",
            fg="green",
        )

    def rm(id):
        id = find_container(container_name, all=True)
        if id:
            cmd = ["docker", "rm", "-f", id]
            subprocess.run(cmd, check=True)

    if image_was_updated:
        rm(container_name)

    running_container = find_container(container_name, all=False)
    if not running_container and not config.NO_START_APT_PROXY:
        click.secho(
            f"Did not find running container {container_name}.", fg="yellow"
        )
        rm(container_name)
        _start_container(image_name, container_name)

    return _get_container_id()


def create_named_volume(volume_name):
    result = subprocess.run(
        ["docker", "volume", "ls", "-q", "-f", f"name={volume_name}"],
        capture_output=True,
        text=True,
        check=True,
    )

    if not result.stdout.strip():
        subprocess.run(["docker", "volume", "create", volume_name], check=True)


# HACKY: the settings are put in the APT CONTAINER, because it is build; the proxpi container
# is just an image
def start_squid_proxy(config, empty_setup=False):
    image_name = "squid-deb-cacher-wodoo"
    create_named_volume(APT_VOLNAME)
    settings = {
        "APT_PROXY_IP": config.APT_PROXY_IP,
        "APT_OPTIONS": config.APT_OPTIONS,
    }
    if empty_setup:
        settings["APT_PROXY_IP"] = ""
    start_container(
        config,
        APT_CACHER_CONTAINER_NAME,
        image_name,
        config.dirs["images"] / "apt_cacher",
        network="aptcache-net",
        port_mapping=config.APT_PROXY_IP + ":8000",
        volmappings={APT_VOLNAME: "/data"},
        # always true otherwise building fails, if image is garbage collected
        # startup=config.APT_PROXY_IP and config.APT_PROXY_IP != "ignore",
        startup=True,
    )
    return settings


def start_proxpi(config, empty_setup=False):
    image_name = "epicwink/proxpi"
    create_named_volume(PROXPI_VOLNAME)
    settings = {
        "PIP_PROXY_IP": config.PIP_PROXY_IP,
        "PIP_OPTIONS": config.PIP_OPTIONS,
        "PIP_OPTIONS_NO_BUILDISOLATION": config.PIP_OPTIONS_NO_BUILDISOLATION,
    }
    if empty_setup:
        settings["PIP_PROXY_IP"] = ""
    start_container(
        config,
        PROXPI_CONTAINER_NAME,
        image_name,
        None,
        network="proxpi-net",
        volmappings={PROXPI_VOLNAME: "/tmp"},
        port_mapping=config.PIP_PROXY_IP + ":5000",
        startup=config.PIP_PROXY_IP and config.PIP_PROXY_IP != "ignore",
    )
    return settings


@cache.command()
@pass_config
@click.pass_context
def apt_attach(ctx, config):
    subprocess.run(
        ["docker", "exec", "-it", APT_CACHER_CONTAINER_NAME, "bash"],
        check=False,
    )


@cache.command()
@pass_config
@click.pass_context
def proxpi_attach(ctx, config):
    subprocess.run(
        ["docker", "exec", "-it", PROXPI_CONTAINER_NAME, "bash"], check=False
    )


@cache.command()
@pass_config
@click.pass_context
def apt_restart(ctx, config):
    subprocess.run(
        ["docker", "restart", APT_CACHER_CONTAINER_NAME], check=True
    )


@cache.command()
@pass_config
@click.pass_context
def pypi_restart(ctx, config):
    subprocess.run(["docker", "restart", PROXPI_CONTAINER_NAME], check=True)


@cache.command()
@pass_config
@click.pass_context
def apt_reset(ctx, config):
    click.secho("Removing squid deb proxy with volumes.")
    subprocess.run(
        ["docker", "rm", "-f", APT_CACHER_CONTAINER_NAME], check=True
    )
    subprocess.run(["docker", "volume", "rm", APT_VOLNAME], check=True)


@cache.command()
@pass_config
@click.pass_context
def pypi_reset(ctx, config):
    click.secho("Removing proxpi with volumes.")
    subprocess.run(["docker", "rm", "-f", PROXPI_CONTAINER_NAME], check=True)
    subprocess.run(["docker", "volume", "rm", PROXPI_VOLNAME], check=True)


@cache.command()
@pass_config
@click.pass_context
def setup(ctx, config):
    from .tools import get_local_ips, choose_ip, is_interactive
    from .cli import Commands

    ips = list(sorted(get_local_ips()))
    ip = choose_ip(ips)
    if not is_interactive():
        abort("Please define system wide APT_PROXY_IP")

    questions = [
        inquirer.Text(
            "apt_port",
            message="Enter APT proxy port",
            default="3142",
            validate=lambda _, x: x.isdigit()
            and 1 <= int(x) <= 65535
            or "Must be a valid port number",
        ),
        inquirer.Text(
            "pypi_port",
            message="Enter PyPI proxy port",
            default="3143",
            validate=lambda _, x: x.isdigit()
            and 1 <= int(x) <= 65535
            or "Must be a valid port number",
        ),
    ]

    answers = inquirer.prompt(questions)

    apt_proxy = f"{ip}:{answers['apt_port']}"
    pypi_proxy = f"{ip}:{answers['pypi_port']}"
    Commands.invoke(
        ctx, "setting", name="APT_PROXY_IP", value=apt_proxy, no_reload=True
    )
    Commands.invoke(
        ctx, "setting", name="PIP_PROXY_IP", value=pypi_proxy, no_reload=False
    )
