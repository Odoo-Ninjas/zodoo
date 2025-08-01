"""
configure:
HUB_URL=registry.name:port/user/project:version
"""

import yaml
from pathlib import Path
import subprocess
import sys
import os
import click
import getpass
from .tools import __dc
from .cli import cli, pass_config
from .lib_clickhelpers import AliasedGroup
from .tools import split_hub_url, abort
from .tools import update_setting


@cli.group(cls=AliasedGroup)
@pass_config
def docker_registry(config):
    pass


@docker_registry.command()
@click.argument("name", required=False)
@pass_config
def tag(config, name):
    if not name:
        name = config.DOCKER_IMAGE_TAG
    else:
        update_setting(config, "DOCKER_IMAGE_TAG", name)
    hub = split_hub_url(config)
    if not name:
        name = "n/a -- using git revision as tagname"
    click.secho(f"Hub URL: {config.HUB_URL}\n" f"tag: {name}", fg="green")


@docker_registry.command()
@pass_config
def login(config):
    hub = split_hub_url(config)
    if not hub:
        abort("No HUB Configured - cannt login.")

    def _login():
        if not hub["username"]:
            username = getpass.getpass(
                f"Enter your username for {hub['url']}: "
            )
        else:
            username = hub["username"]
        if not hub["password"]:
            password = getpass.getpass("Enter your password: ")
        else:
            password = hub["password"]
        click.secho(f"Using {hub['username']}", fg="yellow")
        res = subprocess.check_output(
            [
                "docker",
                "login",
                f"{hub['url']}",
                "-u",
                username,
                "-p",
                password,
            ],
            encoding="utf-8",
        )
        if "Login succeeded" in res:
            return True
        return False

    if _login():
        return


def _get_base_tag(config):
    request_file = config.dirs["run"] / "requirements.odoo.hash"
    if not request_file.exists():
        abort(
            "Please run wodoo requirements.odoo first to create the requirements.odoo.hash file."
        )
    base_tag = request_file.read_text().strip()


@docker_registry.command()
@pass_config
@click.option(
    "-b",
    "--baseimage",
    is_flag=True,
    help="Pushes without source code by using a tag of the requirements.odoo.hash and platform combination. With regpull those base images can be quickly pulled and used again.",
)
@click.argument("machines", nargs=-1)
@click.pass_context
def regpush(ctx, config, baseimage, machines):
    hub = split_hub_url(config)
    if hub["username"]:
        ctx.invoke(login)
    tags = list(_apply_tags(config))
    for tag in tags:
        click.secho(f"Pushing tag {tag}")
        subprocess.check_call(["docker", "push", tag])


@docker_registry.command()
@click.option(
    "-b",
    "--baseimage",
    is_flag=True,
    help="Pushes without source code by using a tag of the requirements.odoo.hash and platform combination. With regpull those base images can be quickly pulled and used again.",
)
@click.argument("machines", nargs=-1)
@pass_config
@click.pass_context
def regpull(ctx, config, baseimage, machines):
    if not config.REGISTRY:
        abort(
            "Please set REGISTRY=1 in configuration and reload. "
            "Then regpull is available"
        )
    hub = split_hub_url(config)
    if hub["username"]:
        ctx.invoke(login)

    if not machines:
        machines = list(
            yaml.safe_load(config.files["docker_compose"].read_text())[
                "services"
            ]
        )
    click.secho(f"Pulling {','.join(machines)}")
    __dc(config, ["pull"] + list(machines))


@docker_registry.command()
@pass_config
def self_sign_hub_certificate(config):
    if os.getuid() != 0:
        click.secho(
            "Please execute as root or with sudo! Docker service is restarted after that.",
            bold=True,
            fg="red",
        )
        sys.exit(-1)
    hub = split_hub_url(config)
    url_part = hub["url"].split(":")[0] + ".crt"
    cert_filename = Path("/usr/local/share/ca-certificates") / url_part
    with cert_filename.open("w") as f:
        proc = subprocess.Popen(
            [
                "openssl",
                "s_client",
                "-connect",
                hub["url"],
            ],
            stdin=subprocess.PIPE,
            stdout=f,
        )
        proc.stdin.write(b"\n")
        proc.communicate()
    print(cert_filename)
    content = cert_filename.read_text()
    BEGIN_CERT = "-----BEGIN CERTIFICATE-----"
    END_CERT = "-----END CERTIFICATE-----"
    content = (
        BEGIN_CERT
        + "\n"
        + content.split(BEGIN_CERT)[1].split(END_CERT)[0]
        + "\n"
        + END_CERT
        + "\n"
    )
    cert_filename.write_text(content)
    click.secho("Restarting docker service...", fg="green")
    subprocess.check_call(["service", "docker", "restart"])
    click.secho("Updating ca certificates...", fg="green")
    subprocess.check_call(["update-ca-certificates"])


current_sha = None


def _get_service_tagname(config, service_name):
    global current_sha
    if config.DOCKER_IMAGE_TAG:
        current_sha = config.DOCKER_IMAGE_TAG
        click.secho(
            f"DOCKER_IMAGE_TAG is set with value: {config.DOCKER_IMAGE_TAG}",
            fg="green",
        )
    else:
        click.secho(
            f"DOCKER_IMAGE_TAG is not set - falling back to a default",
            fg="yellow",
        )
    if not current_sha:
        if (Path(os.getcwd()) / ".git").exists():
            current_sha = subprocess.check_output(
                ["git", "log", "-n1", "--pretty=%H"], encoding="utf-8"
            ).strip()
            click.secho(
                f"Using SHA {current_sha} from current "
                "directory as no DOCKER_IMAGE_TAG is given.",
                fg="green",
            )
        else:
            if not config.DOCKER_IMAGE_TAG:
                abort(
                    (
                        "If you dont have a local git repository, then "
                        "please configure DOCKER_IMAGE_TAG=sha"
                    )
                )
            current_sha = config.DOCKER_IMAGE_TAG

    hub = split_hub_url(config)
    if not hub:
        abort(("No HUB_URL configured."))
    hub = "/".join(
        [
            hub["url"],
            hub["prefix"],
        ]
    )
    return f"{hub}/{service_name}:{current_sha}"


def _apply_tags(config):
    """
    Tags all containers by their name and sha of the git repository
    of the project. The production system can fetch the image by their
    sha then.
    """
    compose = yaml.safe_load(config.files["docker_compose"].read_text())
    hub = config.hub_url
    hub = hub.split("/")
    assert config.project_name

    for service, item in compose["services"].items():
        tag = _get_service_tagname(config, service)
        item["labels"]["registry_applied"] = "1"
        if item.get("image"):
            continue
        elif item.get("build"):
            # Docker changed from _ to - - if doesnt work use latest docker please
            expected_image_name = f"{config.project_name}-{service}"
        else:
            raise NotImplementedError("Only build or image is supported")
        if config.verbose:
            click.secho(
                (f"Applying {tag} on {expected_image_name}"), fg="yellow"
            )
        try:
            subprocess.check_call(["docker", "tag", expected_image_name, tag])
        except:
            click.secho(
                f"Could not tag: {expected_image_name}. Perhaps not a prob for external images.",
                fg="yellow",
            )
        click.secho(
            (f"Applied tag {tag} on {expected_image_name}"), fg="green"
        )
        yield tag


def _rewrite_compose_with_tags(config, yml):
    # set hub source for all images, that are built:
    for service_name, service in yml["services"].items():
        if config.HUB_URL:
            if "build" in service:
                service.pop("build")
                service["image"] = _get_service_tagname(config, service_name)
