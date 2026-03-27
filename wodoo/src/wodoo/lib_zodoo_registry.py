"""
Zodoo Registry: Cache build images in a central Docker registry.

Settings:
    ZODOO_REGISTRY_URL=registry.zebroo.de
    ZODOO_REGISTRY_USERNAME=admin
    ZODOO_REGISTRY_PASSWORD=zebroo
"""

import getpass
import json
import platform
import secrets
import string
import subprocess
import sys
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

import click
import yaml


def _read_user_setting(config, key):
    """Read a setting directly from ~/.odoo/settings without requiring reload."""
    from .myconfigparser import MyConfigParser

    user_settings = MyConfigParser(config.files["user_settings"])
    return user_settings.get(key, "")


def _write_user_setting(config, key, value):
    """Write a setting directly to ~/.odoo/settings without requiring reload."""
    from .myconfigparser import MyConfigParser

    user_settings = MyConfigParser(config.files["user_settings"])
    user_settings[key] = value
    user_settings.write()


def _generate_password(length=20):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _request_registry_user(registry_url, username, password):
    """Request a new user account via the registry admin API."""
    data = json.dumps({"username": username, "password": password}).encode()
    for scheme in ("https", "http"):
        url = f"{scheme}://{registry_url}/admin/api/request-user"
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            raw = e.read() if e.fp else b""
            try:
                body = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                body = {"error": raw.decode(errors="replace")}
            return body, e.code
        except urllib.error.URLError:
            continue
        except Exception as e:
            return {"error": str(e)}, 0
    return {"error": f"could not connect to {registry_url}"}, 0


def _get_registry_config(config):
    suggested = _read_user_setting(config, "ZODOO_REGISTRY_SUGGESTED")

    if suggested == "0":
        return None

    if not suggested:
        click.secho(
            "\n========================================\n"
            "Zodoo Registry Setup\n"
            "========================================\n"
            "\n"
            "The zodoo registry caches built Docker images centrally so\n"
            "that team members don't have to rebuild locally.\n"
            "\n"
            "IMPORTANT: When you enable the registry, you MUST also\n"
            "update the CI/CD pipeline configuration to push images\n"
            "to the registry after successful builds.\n"
            "========================================",
            fg="yellow",
        )
        try:
            use_registry = click.confirm(
                "Do you want to use the zodoo registry?", default=True
            )
        except (click.Abort, KeyboardInterrupt):
            click.secho(
                "\nAborted. Cannot continue without a decision.", fg="red"
            )
            sys.exit(1)
        if not use_registry:
            _write_user_setting(config, "ZODOO_REGISTRY_SUGGESTED", "0")
            click.secho("Registry disabled. Will not ask again.", fg="yellow")
            return None

        url = click.prompt(
            "ZODOO_REGISTRY_URL", default="registry.zebroo.de"
        )

        try:
            request_account = click.confirm(
                "No credentials yet. Request a new account automatically?",
                default=True,
            )
        except (click.Abort, KeyboardInterrupt):
            click.secho("\nAborted.", fg="red")
            sys.exit(1)

        if request_account:
            default_user = getpass.getuser()
            try:
                username = click.prompt("Choose a username", default=default_user)
                password = _generate_password()
            except (click.Abort, KeyboardInterrupt):
                click.secho("\nAborted.", fg="red")
                sys.exit(1)

            body, status = _request_registry_user(url, username, password)

            if status == 201:
                click.secho(
                    f"\nAccount '{username}' created (read-only).",
                    fg="green",
                )
                click.secho(
                    f"\n  Ask an admin to grant push rights at:"
                    f"\n  https://{url}/admin\n",
                    fg="yellow",
                    bold=True,
                )
            elif status == 409:
                click.secho(
                    f"User '{username}' already exists. "
                    "Please enter your existing credentials.",
                    fg="yellow",
                )
                try:
                    username = click.prompt("ZODOO_REGISTRY_USERNAME", default=username)
                    password = click.prompt("ZODOO_REGISTRY_PASSWORD", hide_input=True)
                except (click.Abort, KeyboardInterrupt):
                    click.secho("\nAborted.", fg="red")
                    sys.exit(1)
            else:
                click.secho(
                    f"Could not request account: {body.get('error', 'unknown error')}\n"
                    "Falling back to manual credentials.",
                    fg="red",
                )
                try:
                    username = click.prompt("ZODOO_REGISTRY_USERNAME", default="")
                    password = click.prompt("ZODOO_REGISTRY_PASSWORD", hide_input=True)
                except (click.Abort, KeyboardInterrupt):
                    click.secho("\nAborted.", fg="red")
                    sys.exit(1)
        else:
            try:
                username = click.prompt("ZODOO_REGISTRY_USERNAME", default="admin")
                password = click.prompt("ZODOO_REGISTRY_PASSWORD", hide_input=True)
            except (click.Abort, KeyboardInterrupt):
                click.secho("\nAborted. Registry setup incomplete.", fg="red")
                sys.exit(1)

        _write_user_setting(config, "ZODOO_REGISTRY_URL", url)
        _write_user_setting(config, "ZODOO_REGISTRY_USERNAME", username)
        _write_user_setting(config, "ZODOO_REGISTRY_PASSWORD", password)
        _write_user_setting(config, "ZODOO_REGISTRY_SUGGESTED", "1")

        return {
            "url": url.rstrip("/"),
            "username": username,
            "password": password,
        }

    url = (
        _read_user_setting(config, "ZODOO_REGISTRY_URL")
        or getattr(config, "ZODOO_REGISTRY_URL", None)
        or ""
    )
    if not url:
        return None
    username = (
        _read_user_setting(config, "ZODOO_REGISTRY_USERNAME")
        or getattr(config, "ZODOO_REGISTRY_USERNAME", None)
        or ""
    )
    password = (
        _read_user_setting(config, "ZODOO_REGISTRY_PASSWORD")
        or getattr(config, "ZODOO_REGISTRY_PASSWORD", None)
        or ""
    )

    if not username or not password:
        click.secho(
            "Registry credentials incomplete. Please re-enter:", fg="yellow"
        )
        try:
            url = click.prompt("ZODOO_REGISTRY_URL", default=url)
            username = click.prompt(
                "ZODOO_REGISTRY_USERNAME", default=username
            )
            password = click.prompt("ZODOO_REGISTRY_PASSWORD", hide_input=True)
        except (click.Abort, KeyboardInterrupt):
            click.secho("\nAborted. Registry setup incomplete.", fg="red")
            sys.exit(1)
        _write_user_setting(config, "ZODOO_REGISTRY_URL", url)
        _write_user_setting(config, "ZODOO_REGISTRY_USERNAME", username)
        _write_user_setting(config, "ZODOO_REGISTRY_PASSWORD", password)

    return {
        "url": url.rstrip("/"),
        "username": username,
        "password": password,
    }


def _get_requirements_hash(config):
    hash_file = config.WORKING_DIR / "requirements.hash"
    if not hash_file.exists():
        return None
    return hash_file.read_text().strip()


def get_zodoo_image_tag(config):
    """Compute deterministic image tag from build inputs.

    Format: {odoo_version}-{python_version}-{requirements_hash_short}
    Example: 18-3.12.11-a4f8c2d1
    """
    odoo_version = config.odoo_version
    python_version = getattr(config, "ODOO_PYTHON_VERSION", None) or ""
    req_hash = _get_requirements_hash(config)
    if not all([odoo_version, python_version, req_hash]):
        return None
    return f"{odoo_version}-{python_version}-{req_hash[:8]}"


def _registry_image_name(registry_url, service_name, tag):
    return f"{registry_url}/zodoo-{service_name}:{tag}"


def _local_image_name(config, service_name):
    return f"{config.project_name}-{service_name}"


def zodoo_registry_login(config):
    reg = _get_registry_config(config)
    if not reg or not reg["username"]:
        return
    try:
        subprocess.check_output(
            [
                "docker",
                "login",
                reg["url"],
                "-u",
                reg["username"],
                "-p",
                reg["password"],
            ],
            encoding="utf-8",
            stderr=subprocess.STDOUT,
        )
        click.secho(f"Logged in to {reg['url']}", fg="green")
    except subprocess.CalledProcessError as e:
        click.secho(f"Registry login failed: {e.output}", fg="red")
        raise


def zodoo_image_exists(config, service_name, tag):
    """Check if image exists in registry via docker manifest inspect."""
    reg = _get_registry_config(config)
    if not reg:
        return False
    image = _registry_image_name(reg["url"], service_name, tag)
    try:
        subprocess.check_output(
            ["docker", "manifest", "inspect", image],
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        return True
    except subprocess.CalledProcessError:
        return False


def zodoo_pull_and_tag(config, service_name, tag):
    """Pull image from registry and tag it as local compose image."""
    reg = _get_registry_config(config)
    if not reg:
        return False
    registry_image = _registry_image_name(reg["url"], service_name, tag)
    local_image = _local_image_name(config, service_name)

    click.secho(f"Pulling {registry_image}...", fg="cyan")
    try:
        subprocess.check_call(["docker", "pull", registry_image])
    except subprocess.CalledProcessError:
        click.secho(f"Failed to pull {registry_image}", fg="red")
        return False

    subprocess.check_call(["docker", "tag", registry_image, local_image])
    click.secho(f"Tagged {local_image} from registry", fg="green")
    return True


def zodoo_tag_and_push(config, service_name, tag):
    """Tag local image and push to registry."""
    reg = _get_registry_config(config)
    if not reg:
        return
    local_image = _local_image_name(config, service_name)
    registry_image = _registry_image_name(reg["url"], service_name, tag)

    click.secho(f"Tagging {local_image} -> {registry_image}", fg="cyan")
    subprocess.check_call(["docker", "tag", local_image, registry_image])

    click.secho(f"Pushing {registry_image}...", fg="cyan")
    subprocess.check_call(["docker", "push", registry_image])
    click.secho(f"Pushed {registry_image}", fg="green")


def _build_and_push_other_arch(config, service_name, tag):
    """Build for amd64 via buildx and push (runs in background on Mac)."""
    reg = _get_registry_config(config)
    if not reg:
        return
    registry_image = _registry_image_name(reg["url"], service_name, tag)

    compose = yaml.safe_load(config.files["docker_compose"].read_text())
    service = compose["services"].get(service_name, {})
    build_conf = service.get("build", {})
    if not build_conf:
        return

    context = build_conf.get("context", ".")
    dockerfile = build_conf.get("dockerfile", "Dockerfile")

    build_args = []
    for k, v in build_conf.get("args", {}).items():
        build_args += ["--build-arg", f"{k}={v}"]

    cmd = (
        [
            "docker",
            "buildx",
            "build",
            "--platform",
            "linux/amd64",
            "--push",
            "-t",
            f"{registry_image}-amd64",
            "-f",
            dockerfile,
        ]
        + build_args
        + [context]
    )

    click.secho(
        f"Background: building {service_name} for linux/amd64...", fg="yellow"
    )
    try:
        subprocess.check_call(cmd, stdout=sys.stderr, stderr=sys.stderr)
        click.secho(
            f"Background: pushed {service_name} for linux/amd64", fg="green"
        )
    except subprocess.CalledProcessError:
        click.secho(
            f"Background: failed to build {service_name} for linux/amd64",
            fg="red",
        )


def _is_arm():
    return platform.machine() in ("arm64", "aarch64")


def zodoo_push_with_background_arch(config, service_name, tag):
    """Push local image, and if on ARM, also build+push amd64 in background."""
    zodoo_tag_and_push(config, service_name, tag)

    if _is_arm():
        thread = threading.Thread(
            target=_build_and_push_other_arch,
            args=(config, service_name, tag),
            daemon=True,
        )
        thread.start()
        click.secho(
            f"Background build for amd64 started for {service_name}",
            fg="yellow",
        )
        return thread
    return None


def get_build_services(config):
    """Return list of service names that have a build: directive."""
    compose = yaml.safe_load(config.files["docker_compose"].read_text())
    return [
        name for name, svc in compose["services"].items() if svc.get("build")
    ]


def try_pull_from_zodoo_registry(config, machines):
    """Try to pull all build-services from registry.

    Returns list of services that were successfully pulled
    (and thus don't need building).
    """
    reg = _get_registry_config(config)
    if not reg:
        return []

    tag = get_zodoo_image_tag(config)
    if not tag:
        click.secho(
            "Cannot compute zodoo image tag (missing requirements.hash?). "
            "Run 'odoo reload' first.",
            fg="yellow",
        )
        return []

    zodoo_registry_login(config)

    def _check_and_pull(service_name):
        if zodoo_image_exists(config, service_name, tag):
            click.secho(
                f"Image for {service_name} found in zodoo registry ({tag})",
                fg="green",
            )
            if zodoo_pull_and_tag(config, service_name, tag):
                return service_name
        else:
            click.secho(
                f"Image for {service_name} not in zodoo registry ({tag})",
                fg="yellow",
            )
        return None

    pulled = []
    with ThreadPoolExecutor(max_workers=len(machines) or 1) as pool:
        futures = {pool.submit(_check_and_pull, svc): svc for svc in machines}
        for future in as_completed(futures):
            result = future.result()
            if result:
                pulled.append(result)
    return pulled


def push_to_zodoo_registry(config, machines):
    """Push all build-services to registry after build."""
    reg = _get_registry_config(config)
    if not reg:
        return

    tag = get_zodoo_image_tag(config)
    if not tag:
        return

    zodoo_registry_login(config)

    background_threads = []
    for service_name in machines:
        thread = zodoo_push_with_background_arch(config, service_name, tag)
        if thread:
            background_threads.append((service_name, thread))

    if background_threads:
        click.secho(
            "Waiting for background amd64 builds to complete...", fg="yellow"
        )
        for service_name, thread in background_threads:
            thread.join()
            click.secho(
                f"Background amd64 build for {service_name} finished",
                fg="green",
            )
