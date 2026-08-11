"""
Zodoo Registry: Cache build images in a central Docker registry.

Settings:
    ZODOO_REGISTRY_URL=registry.zebroo.de
    ZODOO_REGISTRY_USERNAME=<your user>
    ZODOO_REGISTRY_PASSWORD=<your password>
    ZODOO_REGISTRY_SUGGESTED=0   # opt out of the registry entirely

Reading needs no account: registry.zebroo.de serves the prebuilt CPython
image (zodoo/python) anonymously, so a fresh machine pulls it instead of
spending a quarter of an hour compiling one. Everything else stays behind
basic auth, and that includes /v2/_catalog, whose repository names are
customer names.

There are no default credentials for pushing — every user has their own
account. `odoo build` offers to request one at the point where a push is
actually about to happen, and writes it to ~/.odoo/settings.
"""

import functools
import getpass
import hashlib
import json
import os
import platform
import re
import secrets
import socket
import string
import subprocess
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

import click
import yaml

from pathlib import Path

IMAGES_DIR = Path.home() / ".odoo" / "images"


def _validate_registry_url(url):
    """Reject a ZODOO_REGISTRY_URL that carries a URL scheme.

    The value is used verbatim to build Docker image references
    (``<url>/zodoo/python:...``). A leading ``http://`` / ``https://``
    would produce an invalid tag and fail the build with a cryptic
    "invalid reference format". Fail early with a clear message instead.
    Returns the trimmed (scheme-free) value.
    """
    url = (url or "").strip()
    if url.startswith(("https://", "http://")):
        raise click.ClickException(
            "ZODOO_REGISTRY_URL must not contain a URL scheme "
            f"(http:// or https://): got {url!r}. "
            "Use a bare host[:port][/path], "
            "e.g. ZODOO_REGISTRY_URL=registry.zebroo.de"
        )
    return url


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


def get_registry_url(config):
    """The registry to read from — never prompts, never writes settings.

    Pulling does not need an account, so the read paths must not drag the
    user through the account wizard. ZODOO_REGISTRY_URL has a default
    (zodoo/src/zodoo/defaults), which is what makes a fresh machine find the
    prebuilt CPython image without any setup at all.

    Returns "" when the registry was switched off via
    ZODOO_REGISTRY_SUGGESTED=0, so that opt-out keeps working.
    """
    try:
        if _read_user_setting(config, "ZODOO_REGISTRY_SUGGESTED") == "0":
            return ""
    except (AttributeError, KeyError, TypeError, OSError):
        # No user settings file at all (containers, CI): not an opt-out.
        pass
    url = _validate_registry_url(
        _read_user_setting_safe(config, "ZODOO_REGISTRY_URL")
        or getattr(config, "ZODOO_REGISTRY_URL", None)
        or ""
    )
    return url.rstrip("/")


def _read_user_setting_safe(config, key):
    try:
        return _read_user_setting(config, key)
    except (AttributeError, KeyError, TypeError, OSError):
        return ""


# Account names that say nothing about *which* machine is asking. They are
# service accounts, so the same name turns up on every second host and the
# first one to register takes it for everybody.
_GENERIC_USERNAMES = {
    "admin",
    "administrator",
    "debian",
    "deploy",
    "docker",
    "ec2-user",
    "odoo",
    "root",
    "ubuntu",
    "user",
}

# Leading hostname labels that describe the role, not the site.
_ROLE_LABELS = {
    "app",
    "erp",
    "host",
    "odoo",
    "server",
    "srv",
    "vm",
    "www",
}

# Second-level labels that are part of a public suffix rather than a name.
_SUFFIX_LABELS = {"ac", "co", "com", "gov", "net", "org"}


def _site_from_fqdn(fqdn):
    """Derive a site name from a host's FQDN: odoo.3dm.de -> "3dm".

    Not public-suffix aware beyond a handful of common second levels; this
    only produces a *default* for a prompt the user can overwrite.
    Returns "" when nothing sensible is left.
    """
    labels = [x for x in (fqdn or "").strip(".").lower().split(".") if x]
    while labels and labels[0] in _ROLE_LABELS:
        labels.pop(0)
    # Need at least name + TLD, otherwise we would hand back the TLD.
    if len(labels) < 2:
        return ""
    if labels[0] in _SUFFIX_LABELS:
        return ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", labels[0]):
        return ""
    return labels[0]


def _default_registry_username():
    """Suggest a username that is unlikely to be taken already.

    getpass.getuser() is frequently the service account the daemon runs as
    ("odoo", "root"), which identifies nobody — "odoo" is registered on
    registry.zebroo.de long since, so the request comes back 409 and the
    user has to invent something anyway. Where the account name is generic,
    fall back to the site the host is named after.
    """
    user = getpass.getuser()
    if user not in _GENERIC_USERNAMES:
        return user
    try:
        fqdn = socket.getfqdn()
    except OSError:
        fqdn = ""
    return _site_from_fqdn(fqdn) or user


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


def verify_credentials(registry_url, username, password, timeout=10):
    """Ask the registry whether these credentials are actually accepted.

    ``docker login`` cannot answer that any more. It reports success as soon
    as the ping endpoint (``/v2/``) does not challenge it, and ``/v2/`` is
    served anonymously so that credential-less hosts can pull -- so a typo in
    the password produces "Login Succeeded" and fails much later, at push
    time, with a 401 that points nowhere.

    ``/v2/_catalog`` is still behind basic auth (its repository names are
    customer names), which makes it the endpoint that tells the truth.

    Returns True (accepted), False (rejected), or None when the registry
    could not be reached at all -- an unreachable registry is not a wrong
    password and must not be reported as one.
    """
    import base64

    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    for scheme in ("https", "http"):
        req = urllib.request.Request(
            f"{scheme}://{registry_url}/v2/_catalog",
            headers={"Authorization": f"Basic {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout):
                return True
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False
            # 404/500/… say nothing about the credentials.
            return None
        except urllib.error.URLError:
            continue
        except Exception:
            return None
    return None


def _warn_about_rejected_credentials(url, username, password):
    """Tell the user now, not at the next push."""
    accepted = verify_credentials(url, username, password)
    if accepted is False:
        click.secho(
            f"\nThe registry rejected the credentials for '{username}'.\n"
            "Pulling keeps working (that needs no account), but pushing "
            "will fail. Check ZODOO_REGISTRY_USERNAME / "
            "ZODOO_REGISTRY_PASSWORD in ~/.odoo/settings.",
            fg="red",
        )
    elif accepted is None:
        click.secho(
            f"Could not reach {url} to check the credentials — "
            "continuing anyway.",
            fg="yellow",
        )
    return accepted


def _get_push_credentials(config):
    """Credentials for *writing* to the registry, asking for them if needed.

    Only the push paths call this, and those run after a build has already
    produced an image. Reading goes through :func:`registry_url` and never
    lands here: a machine that only consumes images is never asked anything.
    """
    suggested = _read_user_setting(config, "ZODOO_REGISTRY_SUGGESTED")

    if suggested == "0":
        return None

    if not suggested:
        # Non-interactive contexts (CI, scripted invocations) cannot
        # answer the prompt; aborting would hard-fail the build for
        # everyone running zodoo via cron, in containers, or in CI
        # bake tests. Treat as "registry not configured" without
        # persisting so a real user still gets prompted later.
        if not sys.stdin.isatty():
            return None
        click.secho(
            "\n========================================\n"
            "Zodoo Registry: share this build\n"
            "========================================\n"
            "\n"
            "This image could be pushed to the zodoo registry so that the\n"
            "rest of the team does not have to build it again. Pulling\n"
            "already works without an account; pushing needs one.\n"
            "\n"
            "Docs: https://docs.zebroo.de/docs/reduce-build-time-and-resources-with-zodoo-registry\n"
            "========================================",
            fg="yellow",
        )
        try:
            use_registry = click.confirm(
                "Set up an account to push built images?", default=True
            )
        except (click.Abort, KeyboardInterrupt):
            click.secho(
                "\nAborted. Cannot continue without a decision.", fg="red"
            )
            sys.exit(1)
        if not use_registry:
            _write_user_setting(config, "ZODOO_REGISTRY_SUGGESTED", "0")
            click.secho(
                "No push account. Pulling keeps working; "
                "will not ask again.",
                fg="yellow",
            )
            return None

        url = _validate_registry_url(
            click.prompt(
                "ZODOO_REGISTRY_URL",
                default=get_registry_url(config) or "registry.zebroo.de",
            )
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
            default_user = _default_registry_username()
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
                # Not "admin" as the default: that account does not exist on
                # registry.zebroo.de, accepting the default would only produce
                # a 401 later.
                username = click.prompt(
                    "ZODOO_REGISTRY_USERNAME",
                    default=_default_registry_username(),
                )
                password = click.prompt(
                    "ZODOO_REGISTRY_PASSWORD", hide_input=True
                )
            except (click.Abort, KeyboardInterrupt):
                click.secho("\nAborted. Registry setup incomplete.", fg="red")
                sys.exit(1)

        _warn_about_rejected_credentials(url, username, password)

        _write_user_setting(config, "ZODOO_REGISTRY_URL", url)
        _write_user_setting(config, "ZODOO_REGISTRY_USERNAME", username)
        _write_user_setting(config, "ZODOO_REGISTRY_PASSWORD", password)
        _write_user_setting(config, "ZODOO_REGISTRY_SUGGESTED", "1")

        return {
            "url": url.rstrip("/"),
            "username": username,
            "password": password,
        }

    url = _validate_registry_url(
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
            url = _validate_registry_url(
                click.prompt("ZODOO_REGISTRY_URL", default=url)
            )
            username = click.prompt(
                "ZODOO_REGISTRY_USERNAME", default=username
            )
            password = click.prompt("ZODOO_REGISTRY_PASSWORD", hide_input=True)
        except (click.Abort, KeyboardInterrupt):
            click.secho("\nAborted. Registry setup incomplete.", fg="red")
            sys.exit(1)
        _warn_about_rejected_credentials(url, username, password)
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


# ---------------------------------------------------------------------------
# Per-service image tag computation
# ---------------------------------------------------------------------------

_EXCLUDE_DIRS = {".git", "__pycache__", "zodoo_src", ".mypy_cache"}
_EXCLUDE_FILES = {"buildsettings.env", ".gitignore"}

# Services whose build context points to a different image directory.
_BUILD_CONTEXT_ALIASES = {
    "cronjobshell": "cronjobs",
    "odoo_base": "odoo",
}


def _get_directory_content_hash(path):
    """Compute a deterministic blake2b hash of all files in *path*.

    File paths are sorted for reproducibility.  Directories and files
    matching the module-level exclude sets are skipped.
    """
    path = Path(path)
    if not path.is_dir():
        return None

    h = hashlib.blake2b()
    files = []
    for root, dirs, filenames in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in _EXCLUDE_DIRS)
        for fname in sorted(filenames):
            if fname in _EXCLUDE_FILES or fname.endswith(".pyc"):
                continue
            files.append(os.path.join(root, fname))

    for filepath in sorted(files):
        rel = os.path.relpath(filepath, path)
        h.update(rel.encode())
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)

    return h.hexdigest()


@functools.lru_cache(maxsize=1)
def _get_zodoo_src_hash():
    """Hash the zodoo CLI source (zodoo/src/).

    Cached because multiple images may include zodoo.
    """
    src_dir = IMAGES_DIR / "zodoo" / "src"
    return _get_directory_content_hash(src_dir)


def _get_snippets_used(image_dir):
    """Detect snippet names referenced in Dockerfiles under *image_dir*."""
    snippets = set()
    for df in Path(image_dir).glob("Dockerfile*"):
        content = df.read_text()
        snippets.update(re.findall(r"#___SNIPPET_(\w+)___", content))
    return snippets


def _get_snippet_hashes(snippet_names):
    """Hash the content of the named common_snippets."""
    h = hashlib.blake2b()
    snippets_dir = IMAGES_DIR / "common_snippets"
    for name in sorted(snippet_names):
        snippet_file = snippets_dir / name.lower()
        if snippet_file.exists():
            h.update(name.encode())
            h.update(snippet_file.read_bytes())
            # Recurse: a snippet may reference other snippets.
            nested = set(
                re.findall(r"#___SNIPPET_(\w+)___", snippet_file.read_text())
            )
            for nested_name in sorted(nested):
                nested_file = snippets_dir / nested_name.lower()
                if nested_file.exists():
                    h.update(nested_name.encode())
                    h.update(nested_file.read_bytes())
    return h.hexdigest()


def _load_registry_tag_config(image_dir):
    """Load ``registry_tag.yml`` from *image_dir*, or return ``None``."""
    tag_file = Path(image_dir) / "registry_tag.yml"
    if not tag_file.exists():
        return None
    return yaml.safe_load(tag_file.read_text()) or {}


def _resolve_image_dir(service_name):
    """Map a compose service name to its canonical image directory."""
    canonical = _BUILD_CONTEXT_ALIASES.get(service_name, service_name)
    image_dir = IMAGES_DIR / canonical
    if image_dir.is_dir():
        return image_dir
    return None


def _resolve_extra_path(raw_path, config):
    """Resolve ``${varname}`` placeholders in *raw_path* using *config*."""

    def _sub(m):
        attr = m.group(1)
        return str(getattr(config, attr, "") or "")

    resolved = re.sub(r"\$\{(\w+)\}", _sub, raw_path)
    return IMAGES_DIR / resolved


def get_zodoo_image_tag_for_service(config, service_name):
    """Compute a per-service deterministic image tag.

    If the image directory contains a ``registry_tag.yml`` the tag is
    built from only the settings, directory content, snippets and
    (optionally) zodoo source that actually influence the build.

    Images without ``registry_tag.yml`` fall back to the global
    :func:`get_zodoo_image_tag`.
    """
    image_dir = _resolve_image_dir(service_name)
    if not image_dir:
        return get_zodoo_image_tag(config)

    tag_config = _load_registry_tag_config(image_dir)
    if tag_config is None:
        return get_zodoo_image_tag(config)

    # 1. Relevant setting values
    setting_values = []
    for s in tag_config.get("settings", []):
        val = str(getattr(config, s, "") or "")
        setting_values.append(f"{s}={val}")

    # 2. Image directory content hash
    dir_hash = _get_directory_content_hash(image_dir) or ""

    # 3. Snippet hashes
    snippets_used = _get_snippets_used(image_dir)
    snippet_hash = _get_snippet_hashes(snippets_used) if snippets_used else ""

    # 4. Extra paths (e.g. odoo version-specific Dockerfile)
    extra_parts = []
    for raw in tag_config.get("extra_paths", []):
        p = _resolve_extra_path(raw, config)
        if p.is_file():
            with open(p, "rb") as f:
                extra_parts.append(hashlib.blake2b(f.read()).hexdigest())
        elif p.is_dir():
            h = _get_directory_content_hash(p)
            if h:
                extra_parts.append(h)
    extra_hash = "|".join(extra_parts)

    # 5. Zodoo source hash
    #    zodoo_paths: list of specific files (relative to IMAGES_DIR) to hash
    #                 instead of the entire zodoo/src/ tree.
    #    includes_zodoo: if true (or auto-detected from SNIPPET_ZODOO),
    #                    hash the full zodoo/src/ tree.
    zodoo_parts = []
    for zp in tag_config.get("zodoo_paths", []):
        p = IMAGES_DIR / zp
        if p.is_file():
            with open(p, "rb") as f:
                zodoo_parts.append(hashlib.blake2b(f.read()).hexdigest())
        elif p.is_dir():
            h = _get_directory_content_hash(p)
            if h:
                zodoo_parts.append(h)
    if not zodoo_parts:
        includes_zodoo = tag_config.get("includes_zodoo")
        if includes_zodoo is None:
            includes_zodoo = "ZODOO" in snippets_used
        # In standard mode the zodoo source is bind-mounted at runtime, so
        # its content is irrelevant for the image. Only the dependency list
        # (zodoo's requirements.txt) ends up baked, and that's covered by
        # the snippet hash via SNIPPET_ZODOO. Only the bakery path
        # (ZODOO_EMBED=1) actually copies the source into the image.
        zodoo_embedded = str(
            getattr(config, "ZODOO_EMBED", "") or ""
        ).strip() in ("1", "true", "True")
        if includes_zodoo and zodoo_embedded:
            full = _get_zodoo_src_hash() or ""
            if full:
                zodoo_parts.append(full)
    zodoo_hash = "|".join(zodoo_parts)

    # 6. Requirements hash (only for images that declare it, e.g. odoo)
    req_hash = ""
    if tag_config.get("include_requirements_hash"):
        req_hash = _get_requirements_hash(config) or ""

    # 7. Project files (relative to WORKING_DIR, e.g. requirements.txt.all)
    project_parts = []
    working_dir = getattr(config, "WORKING_DIR", None)
    if working_dir:
        for rel in tag_config.get("project_files", []):
            p = Path(working_dir) / rel
            if p.is_file():
                with open(p, "rb") as f:
                    project_parts.append(hashlib.blake2b(f.read()).hexdigest())
        for pattern in tag_config.get("project_globs", []):
            for p in sorted(Path(working_dir).glob(pattern)):
                if p.is_file():
                    with open(p, "rb") as f:
                        project_parts.append(
                            hashlib.blake2b(f.read()).hexdigest()
                        )
    project_hash = "|".join(project_parts)

    # Generation bump — increment in registry_tag.yml to force a re-pull
    generation = str(tag_config.get("generation", 0))

    # 8. Combine everything
    combined_input = "|".join(
        setting_values
        + [
            dir_hash,
            snippet_hash,
            extra_hash,
            zodoo_hash,
            req_hash,
            project_hash,
            generation,
        ]
    )
    combined_hash = hashlib.sha256(combined_input.encode()).hexdigest()[:8]

    # 9. Human-readable prefix
    prefix_parts = []
    for p in tag_config.get("tag_prefix", []):
        val = getattr(config, p, None)
        if val is not None and str(val):
            prefix_parts.append(str(val))

    if prefix_parts:
        return f"{'-'.join(prefix_parts)}-{combined_hash}"
    return combined_hash


def _registry_image_name(registry_url, service_name, tag):
    return f"{registry_url}/zodoo-{service_name}:{tag}"


def _local_image_name(config, service_name):
    return f"{config.project_name}-{service_name}"


def zodoo_registry_login(config):
    """Hand docker whatever credentials the settings already hold.

    Deliberately does not ask for an account: the pull paths call this, and
    pulling the anonymously served images works without one. A machine that
    never pushes stays unregistered and unbothered.
    """
    login_with_settings_credentials(config)


def _docker_login_write_auth(reg):
    """Write auth directly into ~/.docker/config.json.

    On macOS the osxkeychain credential helper fails with
    "User interaction is not allowed" when running via SSH.
    Bypasses credential helpers by writing auths directly and
    setting credHelpers to override credsStore for this registry.
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

    # When credsStore is set (e.g. osxkeychain), Docker ignores the auths
    # section. Setting credHelpers for this specific registry to empty string
    # forces Docker to use the auths section instead of credsStore.
    if docker_cfg.get("credsStore"):
        if "credHelpers" not in docker_cfg:
            docker_cfg["credHelpers"] = {}
        docker_cfg["credHelpers"][reg["url"]] = ""

    with open(docker_cfg_path, "w") as f:
        json.dump(docker_cfg, f, indent=2)

    # Deliberately not "Logged in": nothing was verified against the registry
    # here, the credentials were only handed to docker.
    click.secho(f"Stored registry credentials for {reg['url']}", fg="green")


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
        # Not "Logged in": since /v2/ is served anonymously the registry no
        # longer challenges the ping, so `docker login` reports success for
        # any password. verify_credentials() is what actually checks.
        click.secho(
            f"Stored registry credentials for {reg['url']}", fg="green"
        )
    except subprocess.CalledProcessError as e:
        click.secho(f"Registry login failed: {e.output}", fg="red")
        raise


def registry_credentials_from_settings(config, registry_url=None):
    """Read url/username/password from the settings — never prompts.

    Counterpart to :func:`_get_push_credentials`, which may ask questions and
    write settings. Callers that run in the middle of a build (e.g. the
    prebuilt-python pre-flight hook) must not prompt, so they use this.
    Returns None when url, username or password is missing.
    """

    def _setting(key):
        # No user settings file (containers, CI) — fall back to the config.
        try:
            value = _read_user_setting(config, key)
        except (AttributeError, KeyError, TypeError, OSError):
            value = ""
        return value or getattr(config, key, None) or ""

    url = _validate_registry_url(
        registry_url or _setting("ZODOO_REGISTRY_URL")
    )
    username = _setting("ZODOO_REGISTRY_USERNAME")
    password = _setting("ZODOO_REGISTRY_PASSWORD")
    if not url or not username or not password:
        return None
    return {
        "url": url.rstrip("/"),
        "username": username,
        "password": password,
    }


def login_with_settings_credentials(config, registry_url=None):
    """`docker login` using the credentials from the settings.

    zodoo knows ZODOO_REGISTRY_USERNAME/PASSWORD but docker does not: a host
    that was never logged in answers every registry query with a 401, which
    looks exactly like "image not in registry" and triggers a full rebuild.
    Returns True when a login was performed.
    """
    reg = registry_credentials_from_settings(config, registry_url)
    if not reg:
        return False
    if platform.system() == "Darwin":
        _docker_login_write_auth(reg)
    else:
        _docker_login_subprocess(reg)
    return True


# A registry that answers "I don't have this" is a cache miss and rebuilding
# is the right answer. Anything else (401/403, DNS, TLS, refused connection)
# means we simply could not ask — those must not be mistaken for a miss.
_MANIFEST_UNREACHABLE_MARKERS = (
    "unauthorized",
    "authentication required",
    # Ambiguous on purpose: some registries (Docker Hub, Harbor) answer
    # "denied" for a repository that does not exist, others only for missing
    # rights. Counting it as unreachable costs at most a rebuild we would
    # have done anyway; the other way round we would push into a registry we
    # have no rights on.
    "denied",
    "no basic auth credentials",
    "forbidden",
    "connection refused",
    "no such host",
    "timeout",
    "timed out",
    "network is unreachable",
    "temporary failure in name resolution",
    "certificate",
    "tls handshake",
    "server gave http response to https client",
    "cannot connect to the docker daemon",
)

_MANIFEST_MISSING_MARKERS = (
    "manifest unknown",
    "manifest_unknown",
    "no such manifest",
    "not found",
    "name unknown",
)


def classify_manifest_error(output):
    """Return "missing" or "unreachable" for a failed `manifest inspect`.

    Defaults to "unreachable" for unknown messages — treating an unclear
    failure as a cache miss is the expensive mistake (a needless rebuild).
    """
    low = (output or "").lower()
    if any(marker in low for marker in _MANIFEST_UNREACHABLE_MARKERS):
        return "unreachable"
    if any(marker in low for marker in _MANIFEST_MISSING_MARKERS):
        return "missing"
    return "unreachable"


def inspect_registry_manifest(image):
    """Query the registry for `image`.

    Returns ("ok"|"missing"|"unreachable", output).
    """
    try:
        subprocess.check_output(
            ["docker", "manifest", "inspect", image],
            stderr=subprocess.STDOUT,
        )
        return "ok", ""
    except subprocess.CalledProcessError as ex:
        output = ex.output or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return classify_manifest_error(output), output.strip()
    except OSError as ex:
        return "unreachable", str(ex)


def local_image_exists(image, arch=None):
    """True if `image` is in the local docker store, `arch` matching.

    A `FROM` in a Dockerfile resolves against the local store as well, so an
    image present locally needs neither a pull nor a rebuild. The tag alone is
    no proof of the architecture though — the same tag can have been pulled or
    built under a different platform, and a wrong-arch base image would poison
    the whole build. So compare what docker reports.
    """
    try:
        out = subprocess.check_output(
            ["docker", "image", "inspect", "-f", "{{.Architecture}}", image],
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return False
    if arch and out and out != arch:
        click.secho(
            f"Local {image} is {out}, but this build needs {arch} — "
            "ignoring the local copy.",
            fg="yellow",
        )
        return False
    return True


# _manifest_exists runs per service and per tag variant, partly from threads —
# one warning per registry is enough to explain a build full of cache misses.
_warned_unreachable_registries = set()


def _manifest_exists(image):
    """Check if a single image reference exists in the registry."""
    status, output = inspect_registry_manifest(image)
    if status == "ok":
        return True
    if status == "unreachable":
        registry = image.split("/", 1)[0]
        if registry not in _warned_unreachable_registries:
            _warned_unreachable_registries.add(registry)
            click.secho(
                f"Could not ask the registry about {image} "
                "(treating it as a miss — this costs a rebuild):\n"
                f"  {output.splitlines()[-1] if output else 'unknown error'}",
                fg="yellow",
            )
    return False


def _manifest_arch_matches(image):
    """Check if the manifest architecture matches the current host."""
    import json

    current_arch = _get_arch()
    try:
        out = subprocess.check_output(
            ["docker", "manifest", "inspect", "--verbose", image],
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        data = json.loads(out)
        if isinstance(data, list):
            # Multi-arch: at least one entry must match
            return any(
                d.get("Descriptor", {}).get("platform", {}).get("architecture")
                == current_arch
                for d in data
            )
        # Single-arch
        img_arch = (
            data.get("Descriptor", {}).get("platform", {}).get("architecture")
        )
        return img_arch == current_arch if img_arch else True
    except (subprocess.CalledProcessError, json.JSONDecodeError, Exception):
        return True  # can't determine, allow fallback


def _resolve_registry_image(registry_url, service_name, tag):
    """Find the best matching registry image for the current architecture.

    Tries '{tag}-{arch}' first, then falls back to '{tag}' only if
    that image actually matches the current architecture.
    Returns the full image reference or None.
    """
    arch_specific = _arch_tag(tag)
    if arch_specific:
        image = _registry_image_name(registry_url, service_name, arch_specific)
        if _manifest_exists(image):
            return image
    # Fall back to base tag only if its architecture matches
    image = _registry_image_name(registry_url, service_name, tag)
    if _manifest_exists(image):
        if _manifest_arch_matches(image):
            return image
        click.secho(
            f"Skipping {image}: wrong architecture (need {_get_arch()})",
            fg="yellow",
        )
    return None


def zodoo_image_exists(config, service_name, tag):
    """Check if image exists in registry via docker manifest inspect."""
    url = get_registry_url(config)
    if not url:
        return False
    return _resolve_registry_image(url, service_name, tag) is not None


def zodoo_pull_and_tag(config, service_name, tag):
    """Pull image from registry and tag it as local compose image."""
    url = get_registry_url(config)
    if not url:
        return False
    registry_image = _resolve_registry_image(url, service_name, tag)
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
    reg = _get_push_credentials(config)
    if not reg:
        return
    local_image = _local_image_name(config, service_name)
    registry_image = _registry_image_name(reg["url"], service_name, tag)

    click.secho(f"Tagging {local_image} -> {registry_image}", fg="cyan")
    subprocess.check_call(["docker", "tag", local_image, registry_image])

    click.secho(f"Pushing {registry_image}...", fg="cyan")
    returncode, output = _docker_push_streaming(registry_image)
    if returncode != 0:
        if "unauthorized" in output.lower():
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
        raise subprocess.CalledProcessError(
            returncode, ["docker", "push", registry_image], output=output
        )
    click.secho(f"Pushed {registry_image}", fg="green")
    return True


def _docker_push_streaming(image):
    """Run `docker push <image>` streaming output to stdout in real time.

    Docker's native push output (per-layer progress bars) is shown live
    instead of being buffered until completion. The output is also captured
    so callers can inspect it (e.g. to detect 'unauthorized' errors).

    Returns (returncode, captured_output).
    """
    proc = subprocess.Popen(
        ["docker", "push", image],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines = []
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        output_lines.append(line)
    proc.wait()
    return proc.returncode, "".join(output_lines)


def _other_arch():
    """Return the cross-build target architecture."""
    if _is_arm():
        return "amd64", "linux/amd64"
    return "arm64", "linux/arm64"


def _build_and_push_other_arch(config, service_name, tag):
    """Build for the other architecture via buildx and push (runs as detached process)."""
    arch_name, platform_str = _other_arch()

    reg = _get_push_credentials(config)
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
        f"Background: building {service_name} for {platform_str} (detached)...",
        fg="yellow",
    )
    log_file = (
        Path.home()
        / ".odoo"
        / "log"
        / f"cross_build_{service_name}_{arch_name}.log"
    )
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "w") as fh:
        subprocess.Popen(
            cmd,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    click.secho(
        f"Background: {service_name} for {platform_str} running detached (log: {log_file})",
        fg="yellow",
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
        reg = _get_push_credentials(config)
        if reg:
            local_image = _local_image_name(config, service_name)
            arch_image = _registry_image_name(
                reg["url"], service_name, arch_specific
            )
            subprocess.check_call(["docker", "tag", local_image, arch_image])
            returncode, output = _docker_push_streaming(arch_image)
            if returncode != 0:
                if "unauthorized" in output.lower():
                    click.secho(
                        f"Push of {arch_image} failed — unauthorized. "
                        "Check your ZODOO_REGISTRY_* settings, "
                        "contact your zodoo administrator, or use your own registry.\n"
                        "Docs: https://docs.zebroo.de/docs/reduce-build-time-and-resources-with-zodoo-registry",
                        fg="red",
                    )
                    return None
                raise subprocess.CalledProcessError(
                    returncode, ["docker", "push", arch_image], output=output
                )
            click.secho(f"Pushed {arch_image}", fg="green")

    if suppress_other_platform:
        click.secho(
            f"Skipping cross-platform build for {service_name} (--suppress-other-platform-build).",
            fg="yellow",
        )
        return None

    if _can_cross_build():
        _build_and_push_other_arch(config, service_name, tag)
        return None

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
                _build_and_push_other_arch(config, service_name, tag)
                return None
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
    (and thus don't need building).  Each service gets its own
    content-based tag via :func:`get_zodoo_image_tag_for_service`.
    """
    # SRC_EXTRA=0 means customer source must be baked into the odoo image
    # (see lib_composer.append_odoo_src). Pulling the shared cache image
    # would replace the to-be-built image with one that has NO source, so
    # the local build becomes a no-op and /opt/src/MANIFEST never lands in
    # the image — regpush then aborts on the MANIFEST check. Symmetric to
    # the SRC_EXTRA=0 guard in push_to_zodoo_registry.
    if not config.SRC_EXTRA:
        click.secho(
            "Skipping zodoo registry pull: SRC_EXTRA=0 — customer source must "
            "be baked locally, cached image would skip the bake.",
            fg="yellow",
        )
        return []

    url = get_registry_url(config)
    if not url:
        return []

    zodoo_registry_login(config)

    def _check_and_pull(service_name):
        tag = get_zodoo_image_tag_for_service(config, service_name)
        if not tag:
            click.secho(
                f"Cannot compute tag for {service_name} "
                "(missing requirements.hash?). Run 'odoo reload' first.",
                fg="yellow",
            )
            return None
        registry_image = _resolve_registry_image(url, service_name, tag)
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


def enqueue_registry_uploads(config, machines, suppress_other_platform=False):
    """Queue the post-build registry pushes and return immediately.

    Does the cheap, time-sensitive work synchronously:
      - Validates SRC_EXTRA / images-dirty / registry config gates.
      - For each service, computes the tag and **retags the local image**
        under the final registry name(s) so that a subsequent build does
        not clobber the artifact still waiting to be pushed.
      - Triggers cross-architecture builds (already detached today).

    Defers the slow ``docker push`` to a background worker, kicked off
    detached. ``odoo run-crontab`` re-processes any unfinished jobs as a
    safety net.
    """
    from .lib_jobqueue import enqueue, spawn_worker

    if not config.SRC_EXTRA:
        click.secho(
            "Skipping zodoo registry push: SRC_EXTRA=0 — customer source is "
            "baked into the image and must not be uploaded to the shared "
            "zodoo registry.",
            fg="yellow",
        )
        return

    reg = _get_push_credentials(config)
    if not reg:
        return

    queued = 0
    for service_name in machines:
        tag = get_zodoo_image_tag_for_service(config, service_name)
        if not tag:
            click.secho(
                f"Cannot compute tag for {service_name}, skipping push.",
                fg="yellow",
            )
            continue

        local_image = _local_image_name(config, service_name)
        registry_image = _registry_image_name(reg["url"], service_name, tag)
        arch_image = _registry_image_name(
            reg["url"], service_name, _arch_tag(tag)
        )

        # Retag NOW so a later build can't replace the local image before
        # the worker pushes it. The registry-named tag protects the bytes.
        try:
            subprocess.check_call(
                ["docker", "tag", local_image, registry_image]
            )
            subprocess.check_call(["docker", "tag", local_image, arch_image])
        except subprocess.CalledProcessError as e:
            click.secho(
                f"Could not retag {local_image} for {service_name}: {e}; "
                "skipping queue entry.",
                fg="red",
            )
            continue

        enqueue(
            config,
            "registry_upload",
            {
                "service": service_name,
                "tag": tag,
                "images": [registry_image, arch_image],
            },
        )
        queued += 1

    # Cross-arch builds need fresh source on disk, so trigger them now
    # (they are already started detached by _build_and_push_other_arch).
    if not suppress_other_platform and _can_cross_build():
        for service_name in machines:
            tag = get_zodoo_image_tag_for_service(config, service_name)
            if tag:
                _build_and_push_other_arch(config, service_name, tag)

    if queued:
        spawn_worker(config)


def process_registry_upload_job(config, payload):
    """Worker handler for ``registry_upload`` jobs."""
    zodoo_registry_login(config)
    images = payload.get("images") or []
    for image in images:
        click.secho(f"Pushing {image}...", fg="cyan")
        returncode, output = _docker_push_streaming(image)
        if returncode != 0:
            raise subprocess.CalledProcessError(
                returncode, ["docker", "push", image], output=output
            )
        click.secho(f"Pushed {image}", fg="green")


# ---------------------------------------------------------------------------
# Base-image (odoo_base_<v>_<hash>_<arch>) registry support.
# Base images live under a dedicated registry path
# (`{url}/zodoo-odoo-base:<v>-<hash>-<arch>`) so they can be pulled by any
# project of that Odoo version. Pulls happen synchronously from
# ``ensure_base_image()``; pushes are enqueued on the same job queue
# already used for project images.
# ---------------------------------------------------------------------------


def _base_registry_image_name(registry_url, odoo_version_int, base_hash, arch):
    return (
        f"{registry_url}/zodoo-odoo-base:"
        f"{odoo_version_int}-{base_hash}-{arch}"
    )


def try_pull_base_image(config, base_inputs):
    """Attempt to pull a pre-built base image from the zodoo registry.

    Returns True on success (image is now present locally under its
    canonical ``odoo_base_<v>_<hash>_<arch>`` tag), False otherwise.
    Silently no-ops when the registry is not configured.
    """
    url = get_registry_url(config)
    if not url:
        return False
    from .lib_base_image import _arch

    arch = _arch()
    try:
        v = int(float(base_inputs["odoo_version"]))
    except (TypeError, ValueError):
        v = base_inputs["odoo_version"]
    registry_image = _base_registry_image_name(
        url, v, base_inputs["base_hash"], arch
    )
    local_tag = base_inputs["tag"]

    if not _manifest_exists(registry_image):
        click.secho(
            f"Base image not in zodoo registry: {registry_image}",
            fg="yellow",
        )
        return False

    click.secho(f"Pulling base image {registry_image}...", fg="cyan")
    zodoo_registry_login(config)
    try:
        subprocess.check_call(["docker", "pull", registry_image])
        subprocess.check_call(["docker", "tag", registry_image, local_tag])
        click.secho(f"Tagged base image {local_tag} from registry", fg="green")
        return True
    except subprocess.CalledProcessError:
        click.secho(f"Failed to pull {registry_image}", fg="red")
        return False


def enqueue_base_image_upload(config, base_inputs):
    """Queue an async docker push of the base image to the zodoo registry.

    Same job-queue mechanism as :func:`enqueue_registry_uploads`: the
    local tag is duplicated under the registry image name immediately
    (so a subsequent build can't replace the bytes), then the slow
    ``docker push`` runs in a detached worker.
    """
    from .lib_jobqueue import enqueue, spawn_worker
    from .lib_base_image import _arch

    reg = _get_push_credentials(config)
    if not reg:
        return

    arch = _arch()
    try:
        v = int(float(base_inputs["odoo_version"]))
    except (TypeError, ValueError):
        v = base_inputs["odoo_version"]
    registry_image = _base_registry_image_name(
        reg["url"], v, base_inputs["base_hash"], arch
    )
    local_tag = base_inputs["tag"]
    try:
        subprocess.check_call(["docker", "tag", local_tag, registry_image])
    except subprocess.CalledProcessError as e:
        click.secho(
            f"Could not retag base image {local_tag} → {registry_image}: "
            f"{e}; skipping push.",
            fg="red",
        )
        return

    enqueue(
        config,
        "base_image_upload",
        {
            "tag": local_tag,
            "registry_image": registry_image,
            "odoo_version": v,
            "base_hash": base_inputs["base_hash"],
            "arch": arch,
        },
    )
    spawn_worker(config)
    click.secho(f"Queued base image upload: {registry_image}", fg="cyan")


def process_base_image_upload_job(config, payload):
    """Worker handler for ``base_image_upload`` jobs."""
    zodoo_registry_login(config)
    image = payload.get("registry_image")
    if not image:
        return
    click.secho(f"Pushing base image {image}...", fg="cyan")
    returncode, output = _docker_push_streaming(image)
    if returncode != 0:
        raise subprocess.CalledProcessError(
            returncode, ["docker", "push", image], output=output
        )
    click.secho(f"Pushed {image}", fg="green")


def push_to_zodoo_registry(config, machines, suppress_other_platform=False):
    """Push all build-services to registry after build.

    Each service gets its own content-based tag via
    :func:`get_zodoo_image_tag_for_service`.
    """
    # SRC_EXTRA=0 means the customer source is baked into the image
    # (see lib_composer.append_odoo_src). Pushing such an image to the
    # shared zodoo registry would publish the customer's code, so skip.
    if not config.SRC_EXTRA:
        click.secho(
            "Skipping zodoo registry push: SRC_EXTRA=0 — customer source is "
            "baked into the image and must not be uploaded to the shared "
            "zodoo registry.",
            fg="yellow",
        )
        return

    reg = _get_push_credentials(config)
    if not reg:
        return

    zodoo_registry_login(config)

    for service_name in machines:
        tag = get_zodoo_image_tag_for_service(config, service_name)
        if not tag:
            click.secho(
                f"Cannot compute tag for {service_name}, skipping push.",
                fg="yellow",
            )
            continue
        zodoo_push_with_background_arch(
            config,
            service_name,
            tag,
            suppress_other_platform=suppress_other_platform,
        )
