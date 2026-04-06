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

from pathlib import Path

IMAGES_DIR = Path.home() / ".odoo" / "images"


def _get_images_git_sha():
    """Return the current git commit SHA of ~/.odoo/images."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=IMAGES_DIR,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _is_images_dirty():
    """Check if ~/.odoo/images has uncommitted changes."""
    try:
        result = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=IMAGES_DIR,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
        ).strip()
        return bool(result)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


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
            url,
            data=data,
            headers={"Content-Type": "application/json"},
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
            "Docs: https://docs.zebroo.de/docs/reduce-build-time-and-resources-with-zodoo-registry\n"
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

        url = click.prompt("ZODOO_REGISTRY_URL", default="registry.zebroo.de")

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
                username = click.prompt(
                    "Choose a username", default=default_user
                )
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
                    username = click.prompt(
                        "ZODOO_REGISTRY_USERNAME", default=username
                    )
                    password = click.prompt(
                        "ZODOO_REGISTRY_PASSWORD", hide_input=True
                    )
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
                    username = click.prompt(
                        "ZODOO_REGISTRY_USERNAME", default=""
                    )
                    password = click.prompt(
                        "ZODOO_REGISTRY_PASSWORD", hide_input=True
                    )
                except (click.Abort, KeyboardInterrupt):
                    click.secho("\nAborted.", fg="red")
                    sys.exit(1)
        else:
            try:
                username = click.prompt(
                    "ZODOO_REGISTRY_USERNAME", default="admin"
                )
                password = click.prompt(
                    "ZODOO_REGISTRY_PASSWORD", hide_input=True
                )
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

    Format: {odoo_version}-{python_version}-{combined_hash_short}
    Example: 18-3.12.11-a4f8c2d1

    The hash combines the requirements hash and the ~/.odoo/images git SHA
    so that changes to the images repo also invalidate cached images.
    """
    import hashlib

    odoo_version = config.odoo_version
    python_version = getattr(config, "ODOO_PYTHON_VERSION", None) or ""
    req_hash = _get_requirements_hash(config)
    images_sha = _get_images_git_sha()
    if not all([odoo_version, python_version, req_hash, images_sha]):
        return None
    combined = hashlib.sha256(f"{req_hash}{images_sha}".encode()).hexdigest()
    return f"{odoo_version}-{python_version}-{combined[:8]}"


def _registry_image_name(registry_url, service_name, tag):
    return f"{registry_url}/zodoo-{service_name}:{tag}"


def _local_image_name(config, service_name):
    return f"{config.project_name}-{service_name}"


def zodoo_registry_login(config):
    reg = _get_registry_config(config)
    if not reg or not reg["username"]:
        return

    if platform.system() == "Darwin":
        _docker_login_write_auth(reg)
    else:
        _docker_login_subprocess(reg)


def _docker_login_write_auth(reg):
    """Write auth directly into ~/.docker/config.json.

    On macOS the osxkeychain credential helper fails with
    "User interaction is not allowed" when running via SSH.
    Bypasses credential helpers entirely.
    """
    import os
    import base64

    docker_dir = os.path.expanduser("~/.docker")
    os.makedirs(docker_dir, exist_ok=True)
    docker_cfg_path = os.path.join(docker_dir, "config.json")
    try:
        with open(docker_cfg_path) as f:
            docker_cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        docker_cfg = {}

    if "auths" not in docker_cfg:
        docker_cfg["auths"] = {}

    token = base64.b64encode(
        f"{reg['username']}:{reg['password']}".encode()
    ).decode()
    docker_cfg["auths"][reg["url"]] = {"auth": token}

    with open(docker_cfg_path, "w") as f:
        json.dump(docker_cfg, f, indent=2)

    click.secho(f"Logged in to {reg['url']}", fg="green")


def _docker_login_subprocess(reg):
    """Login via docker login command (works on Linux)."""
    try:
        subprocess.check_output(
            [
                "docker",
                "login",
                reg["url"],
                "-u",
                reg["username"],
                "--password-stdin",
            ],
            input=reg["password"],
            encoding="utf-8",
            stderr=subprocess.STDOUT,
        )
        click.secho(f"Logged in to {reg['url']}", fg="green")
    except subprocess.CalledProcessError as e:
        click.secho(f"Registry login failed: {e.output}", fg="red")
        raise


def _manifest_exists(image):
    """Check if a single image reference exists in the registry."""
    try:
        subprocess.check_output(
            ["docker", "manifest", "inspect", image],
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _resolve_registry_image(registry_url, service_name, tag):
    """Find the best matching registry image for the current architecture.

    Tries '{tag}-{arch}' first, then falls back to '{tag}'.
    Returns the full image reference or None.
    """
    arch_specific = _arch_tag(tag)
    if arch_specific:
        image = _registry_image_name(registry_url, service_name, arch_specific)
        if _manifest_exists(image):
            return image
    # Fall back to base tag
    image = _registry_image_name(registry_url, service_name, tag)
    if _manifest_exists(image):
        return image
    return None


def zodoo_image_exists(config, service_name, tag):
    """Check if image exists in registry via docker manifest inspect."""
    reg = _get_registry_config(config)
    if not reg:
        return False
    return _resolve_registry_image(reg["url"], service_name, tag) is not None


def zodoo_pull_and_tag(config, service_name, tag):
    """Pull image from registry and tag it as local compose image."""
    reg = _get_registry_config(config)
    if not reg:
        return False
    registry_image = _resolve_registry_image(reg["url"], service_name, tag)
    if not registry_image:
        return False
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
    try:
        subprocess.check_output(
            ["docker", "push", registry_image],
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
    except subprocess.CalledProcessError as e:
        if "unauthorized" in (e.output or "").lower():
            click.secho(
                "\n========================================\n"
                "Push to zodoo registry failed: unauthorized\n"
                "========================================\n"
                "\n"
                "Your credentials for the zodoo registry are missing or invalid.\n"
                "\n"
                "To fix this either:\n"
                "  - Ask your zodoo administrator for valid credentials\n"
                "  - Or use your own Docker registry by setting ZODOO_REGISTRY_URL\n"
                "\n"
                "Add these settings to ~/.odoo/settings (or system-wide /etc/odoo/settings):\n"
                "\n"
                "  ZODOO_REGISTRY_URL=registry.example.com\n"
                "  ZODOO_REGISTRY_USERNAME=youruser\n"
                "  ZODOO_REGISTRY_PASSWORD=yourpassword\n"
                "\n"
                "Docs: https://docs.zebroo.de/docs/reduce-build-time-and-resources-with-zodoo-registry\n"
                "========================================\n",
                fg="red",
            )
            return False
        raise
    click.secho(f"Pushed {registry_image}", fg="green")
    return True


def _other_arch():
    """Return the cross-build target architecture."""
    if _is_arm():
        return "amd64", "linux/amd64"
    return "arm64", "linux/arm64"


def _build_and_push_other_arch(config, service_name, tag):
    """Build for the other architecture via buildx and push (runs in background)."""
    arch_name, platform_str = _other_arch()

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
            platform_str,
            "--push",
            "-t",
            f"{registry_image}-{arch_name}",
            "-f",
            dockerfile,
        ]
        + build_args
        + [context]
    )

    click.secho(
        f"Background: building {service_name} for {platform_str}...",
        fg="yellow",
    )
    try:
        subprocess.check_output(
            cmd, stderr=subprocess.STDOUT, encoding="utf-8"
        )
        click.secho(
            f"Background: pushed {service_name} for {platform_str}", fg="green"
        )
    except subprocess.CalledProcessError as e:
        if "unauthorized" in (e.output or "").lower():
            click.secho(
                f"Background: push for {service_name} ({platform_str}) "
                "failed — unauthorized. Check your ZODOO_REGISTRY_* settings, "
                "contact your zodoo administrator, or use your own registry.\n"
                "Docs: https://docs.zebroo.de/docs/reduce-build-time-and-resources-with-zodoo-registry",
                fg="red",
            )
        else:
            click.secho(
                f"Background: failed to build {service_name} for {platform_str}",
                fg="red",
            )


def _is_arm():
    return platform.machine() in ("arm64", "aarch64")


def _get_arch():
    """Return normalized architecture: 'amd64' or 'arm64'."""
    mapping = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    return mapping.get(platform.machine(), "amd64")


def _can_cross_build():
    """Check if buildx can build for the other architecture."""
    _, target_platform = _other_arch()
    try:
        out = subprocess.check_output(
            ["docker", "buildx", "inspect", "--bootstrap"],
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        return target_platform.split("/")[1] in out
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _arch_tag(tag):
    """Return architecture-specific tag, e.g. '18-3.12-abc-amd64'."""
    arch = _get_arch()
    return f"{tag}-{arch}"


def zodoo_push_with_background_arch(
    config, service_name, tag, suppress_other_platform=False
):
    """Push local image, and if on ARM, also build+push amd64 in background."""
    if zodoo_tag_and_push(config, service_name, tag) is False:
        return None

    # Also push with architecture-specific tag so other machines
    # with the same arch can pull the correct image.
    arch_specific = _arch_tag(tag)
    if arch_specific:
        reg = _get_registry_config(config)
        if reg:
            local_image = _local_image_name(config, service_name)
            arch_image = _registry_image_name(
                reg["url"], service_name, arch_specific
            )
            subprocess.check_call(["docker", "tag", local_image, arch_image])
            try:
                subprocess.check_output(
                    ["docker", "push", arch_image],
                    stderr=subprocess.STDOUT,
                    encoding="utf-8",
                )
            except subprocess.CalledProcessError as e:
                if "unauthorized" in (e.output or "").lower():
                    click.secho(
                        f"Push of {arch_image} failed — unauthorized. "
                        "Check your ZODOO_REGISTRY_* settings, "
                        "contact your zodoo administrator, or use your own registry.\n"
                        "Docs: https://docs.zebroo.de/docs/reduce-build-time-and-resources-with-zodoo-registry",
                        fg="red",
                    )
                    return None
                raise
            click.secho(f"Pushed {arch_image}", fg="green")

    if suppress_other_platform:
        click.secho(
            f"Skipping cross-platform build for {service_name} (--suppress-other-platform-build).",
            fg="yellow",
        )
        return None

    if _can_cross_build():
        arch_name, platform_str = _other_arch()
        thread = threading.Thread(
            target=_build_and_push_other_arch,
            args=(config, service_name, tag),
            daemon=True,
        )
        thread.start()
        click.secho(
            f"Background build for {platform_str} started for {service_name}",
            fg="yellow",
        )
        return thread

    _, platform_str = _other_arch()
    qemu_cmd = "docker run --rm --privileged multiarch/qemu-user-static --reset -p yes"

    if _read_user_setting(config, "QEMU_INSTALL_SUGGESTED") == "0":
        click.secho(
            f"Skipping cross-build for {platform_str}: QEMU not available.\n"
            f"To enable, run:  {qemu_cmd}",
            fg="yellow",
        )
        return None

    if sys.stdin.isatty():
        click.secho(
            f"Cross-build for {platform_str} not possible: QEMU not available.",
            fg="yellow",
        )
        if click.confirm(f"Install QEMU now? ({qemu_cmd})"):
            try:
                subprocess.check_call(qemu_cmd.split())
                click.secho(
                    "QEMU installed. Starting cross-build...", fg="green"
                )
                return _build_and_push_other_arch(config, service_name, tag)
            except subprocess.CalledProcessError:
                click.secho("Failed to install QEMU.", fg="red")
        else:
            _write_user_setting(config, "QEMU_INSTALL_SUGGESTED", "0")
            click.secho(
                "QEMU installation declined. Will not ask again.\n"
                f"To enable later, set QEMU_INSTALL_SUGGESTED=1 in ~/.odoo/settings",
                fg="yellow",
            )
    else:
        click.secho(
            f"Skipping cross-build for {platform_str}: QEMU not available.\n"
            f"To enable, run:  {qemu_cmd}",
            fg="yellow",
        )
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
    if _is_images_dirty():
        click.secho(
            "Skipping zodoo registry pull: ~/.odoo/images has uncommitted changes.",
            fg="yellow",
        )
        return []

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
        registry_image = _resolve_registry_image(reg["url"], service_name, tag)
        if registry_image:
            click.secho(
                f"Image for {service_name} found in zodoo registry ({registry_image})",
                fg="green",
            )
            local_image = _local_image_name(config, service_name)
            try:
                subprocess.check_call(["docker", "pull", registry_image])
                subprocess.check_call(
                    ["docker", "tag", registry_image, local_image]
                )
                click.secho(f"Tagged {local_image} from registry", fg="green")
                return service_name
            except subprocess.CalledProcessError:
                click.secho(f"Failed to pull {registry_image}", fg="red")
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


def push_to_zodoo_registry(config, machines, suppress_other_platform=False):
    """Push all build-services to registry after build."""
    if _is_images_dirty():
        click.secho(
            "Skipping zodoo registry push: ~/.odoo/images has uncommitted changes.",
            fg="yellow",
        )
        return

    reg = _get_registry_config(config)
    if not reg:
        return

    tag = get_zodoo_image_tag(config)
    if not tag:
        return

    zodoo_registry_login(config)

    background_threads = []
    for service_name in machines:
        thread = zodoo_push_with_background_arch(
            config,
            service_name,
            tag,
            suppress_other_platform=suppress_other_platform,
        )
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
