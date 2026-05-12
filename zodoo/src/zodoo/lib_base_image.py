"""
Per-version Odoo base image: hash, tag, and (eventually) build/pull.

Splits the historically monolithic Odoo image into two layers:

* **Base** (`odoo_base_<v>_<hash>_<arch>`): Python + Debian deps + Odoo's
  upstream ``requirements.txt``. Shared across all projects of the same
  Odoo version. No cleanup, no zodoo install, no customs source.
* **Project** (`<project>-odoo`): ``FROM odoo_base_...`` + module-specific
  pip/deb deps + zodoo + customs + cleanup.

This module is the source of truth for the base hash. Inputs:

* ``ODOO_VERSION``
* ``ODOO_PYTHON_VERSION``
* Content of ``odoo/requirements.txt`` (from the Odoo submodule in the
  current project)
* Content of ``odoo/config/<v>/Dockerfile.base`` (post-snippet-substitution
  the layout would diverge per project; we hash the raw template instead
  so the base remains shareable across projects)
* Content of every ``common_snippets/<name>`` referenced from
  ``Dockerfile.base`` (so editing a snippet invalidates the base)

The hash is intentionally **not** dependent on ``~/.odoo/images``'s git SHA
(unlike :func:`zodoo.lib_zodoo_registry.get_zodoo_image_tag`). That way the
base survives commits that only touch the project-side Dockerfile or the
CLI, which is the common case.
"""

import base64
import hashlib
import os
import platform
import re
import subprocess
from pathlib import Path

import click

IMAGES_DIR = Path.home() / ".odoo" / "images"
COMMON_SNIPPETS_DIR = IMAGES_DIR / "common_snippets"
ODOO_CONFIG_DIR = IMAGES_DIR / "odoo" / "config"


def _arch():
    """Return the docker-style architecture tag (amd64 / arm64)."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return machine


def _resolve_version_dir(odoo_version):
    """Locate ``odoo/config/<v>/`` accepting both float and int spellings."""
    candidates = [str(odoo_version)]
    try:
        as_float = float(odoo_version)
        if as_float.is_integer():
            candidates.append(str(int(as_float)))
    except (TypeError, ValueError):
        pass
    for variant in candidates:
        path = ODOO_CONFIG_DIR / variant
        if path.is_dir():
            return path
    return None


def base_dockerfile_path(odoo_version):
    """Return path to ``Dockerfile.base`` for the given version, or None."""
    version_dir = _resolve_version_dir(odoo_version)
    if version_dir is None:
        return None
    candidate = version_dir / "Dockerfile.base"
    return candidate if candidate.exists() else None


def _referenced_snippets(dockerfile_text):
    """Return ordered set of snippet names referenced by the Dockerfile."""
    seen = []
    for name in re.findall(r"#___SNIPPET_(\w+)___", dockerfile_text):
        lowered = name.lower()
        if lowered not in seen:
            seen.append(lowered)
    # Snippets may reference further snippets — walk transitively.
    pending = list(seen)
    while pending:
        current = pending.pop(0)
        snippet_path = COMMON_SNIPPETS_DIR / current
        if not snippet_path.exists():
            continue
        for nested in re.findall(
            r"#___SNIPPET_(\w+)___", snippet_path.read_text()
        ):
            lowered = nested.lower()
            if lowered not in seen:
                seen.append(lowered)
                pending.append(lowered)
    return seen


def _odoo_framework_requirements_text(config):
    """Return the content of Odoo's upstream ``requirements.txt``.

    Resolves via ``config.dirs["odoo_home"]`` (set by zodoo's compose
    layer) and falls back to scanning the project's working dir for an
    ``odoo`` submodule.
    """
    odoo_home = None
    try:
        odoo_home = Path(config.dirs["odoo_home"])
    except (KeyError, TypeError):
        pass
    if odoo_home and (odoo_home / "requirements.txt").exists():
        return (odoo_home / "requirements.txt").read_text()

    working = getattr(config, "WORKING_DIR", None)
    if working:
        candidate = Path(working) / "odoo" / "requirements.txt"
        if candidate.exists():
            return candidate.read_text()
    return ""


def compute_base_hash(
    odoo_version,
    python_version,
    framework_requirements_text,
    dockerfile_base_text,
):
    """Deterministic short hash that identifies a base image.

    Hash order is fixed and labelled so future additions to the input set
    don't silently shift existing hashes (each new input is appended with
    its own label).
    """
    h = hashlib.sha256()

    def feed(label, value):
        h.update(label.encode())
        h.update(b"=")
        h.update(value.encode() if isinstance(value, str) else value)
        h.update(b"\n---\n")

    feed("odoo_version", str(odoo_version))
    feed("python_version", str(python_version or ""))
    feed("framework_requirements", framework_requirements_text or "")
    feed("dockerfile_base", dockerfile_base_text or "")

    for snippet_name in _referenced_snippets(dockerfile_base_text or ""):
        snippet_path = COMMON_SNIPPETS_DIR / snippet_name
        content = snippet_path.read_text() if snippet_path.exists() else ""
        feed(f"snippet:{snippet_name}", content)

    return h.hexdigest()[:12]


def base_image_tag(odoo_version, base_hash, arch=None):
    """Local docker tag for the base image.

    Format: ``odoo_base_<ODOO_VERSION_INT>_<hash>_<arch>``

    Including ``arch`` in the tag mirrors the existing prebuilt-python
    convention (``zodoo/python:<v>-<arch>``) and lets a host pull the
    correct variant from the registry without needing buildx manifests.
    """
    try:
        v = int(float(odoo_version))
    except (TypeError, ValueError):
        v = odoo_version
    return f"odoo_base_{v}_{base_hash}_{arch or _arch()}"


def image_exists_locally(tag):
    """Return True iff ``docker image inspect <tag>`` succeeds."""
    try:
        subprocess.check_output(
            ["docker", "image", "inspect", tag],
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def render_base_dockerfile(dockerfile_base_text):
    """Inline all ``#___SNIPPET_X___`` markers in the base Dockerfile.

    Mirrors :func:`zodoo.lib_composer._replace_docker_snippets` but does
    not depend on a project config — the base Dockerfile and its
    snippets are project-agnostic, so the substitution is purely
    file-driven.

    Raises :class:`RecursionError` if a snippet references itself or a
    cycle is detected (same guard as the composer).
    """
    plain_snippets = {}
    for snippet in COMMON_SNIPPETS_DIR.glob("*"):
        if not snippet.is_file():
            continue
        # Match lib_composer.remove_comments_not_snippets behaviour:
        # drop blank/comment lines except those that themselves are
        # snippet markers.
        lines = []
        for raw in snippet.read_text().splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("#") and not stripped.startswith(
                "#___SNIPPET"
            ):
                continue
            lines.append(raw)
        plain_snippets[snippet.name.upper()] = "\n".join(lines)

    content = dockerfile_base_text
    counter = 0
    while "#___SNIPPET" in content:
        counter += 1
        for name, body in plain_snippets.items():
            content = content.replace(f"#___SNIPPET_{name}___", body)
        if counter > 100:
            remaining = re.findall(r"#___SNIPPET_.*", content)
            raise RecursionError(
                "Unresolved snippets in Dockerfile.base: %s" % remaining
            )
    return content


def compute_base_inputs(config):
    """Bundle the inputs needed to compute the base hash + tag.

    Returns a dict with keys:
        odoo_version, python_version, framework_requirements,
        dockerfile_base_path, dockerfile_base_text, base_hash, tag
    or ``None`` if the version has no ``Dockerfile.base`` yet.
    """
    odoo_version = getattr(config, "odoo_version", None)
    python_version = getattr(config, "ODOO_PYTHON_VERSION", None)
    if not odoo_version or not python_version:
        return None

    dockerfile_base = base_dockerfile_path(odoo_version)
    if dockerfile_base is None:
        return None

    dockerfile_text = dockerfile_base.read_text()
    framework_reqs = _odoo_framework_requirements_text(config)

    base_hash = compute_base_hash(
        odoo_version, python_version, framework_reqs, dockerfile_text
    )
    return {
        "odoo_version": odoo_version,
        "python_version": python_version,
        "framework_requirements": framework_reqs,
        "dockerfile_base_path": dockerfile_base,
        "dockerfile_base_text": dockerfile_text,
        "base_hash": base_hash,
        "tag": base_image_tag(odoo_version, base_hash),
    }


def _filter_framework_requirements(reqs_text):
    """Drop ``lxml`` from the framework requirements.

    Mirrors :func:`odoo.__after_compose._filter_framework_requirements`.
    lxml is special-cased by the project layer (older Odoo pins clash
    with newer lxml/html-clean splits) and must not be pinned in the
    base.
    """
    return "\n".join(
        line for line in (reqs_text or "").splitlines() if "lxml" not in line
    )


def _docker_build_args(config, inputs):
    """Compose the ``--build-arg`` list for the base image build."""
    reqs_b64 = base64.b64encode(
        _filter_framework_requirements(
            inputs["framework_requirements"]
        ).encode("utf-8")
    ).decode("ascii")

    args = {
        "ODOO_PYTHON_VERSION": inputs["python_version"],
        "ODOO_FRAMEWORK_REQUIREMENTS": reqs_b64,
    }

    base_image = getattr(config, "BASE_IMAGE", None) or "ubuntu:22.04"
    args["BASE_IMAGE"] = base_image

    apt_proxy = getattr(config, "APT_PROXY_IP", None)
    if apt_proxy:
        args["APT_PROXY_IP"] = apt_proxy

    flat = []
    for k, v in args.items():
        flat += ["--build-arg", f"{k}={v}"]
    return flat


def _resolve_build_context(config):
    """Return the build context dir for base-image builds.

    Reuses the project's ``run.build.odoo`` directory which the composer
    already populates with python tarballs, liberation-sans fonts and
    ``buildsettings.env``. The base build is read-only against that
    context.
    """
    try:
        return Path(config.dirs["run.build.odoo"])
    except (KeyError, TypeError, AttributeError):
        return None


def ensure_base_image(
    config,
    *,
    force_rebuild=False,
    try_pull=True,
    enqueue_push=True,
):
    """Make sure the base image exists locally; build it if not.

    Returns the local tag of the base image (``odoo_base_<v>_<hash>_<arch>``),
    or ``None`` if there is no ``Dockerfile.base`` for the project's Odoo
    version (= caller should fall back to the legacy monolithic build).

    Resolution order when the image is missing locally:
      1. If ``try_pull`` is true and a zodoo registry is configured, try
         to pull a pre-built base from the registry.
      2. Otherwise (or if pull failed) build it locally.
      3. After a successful local build, enqueue an async push to the
         zodoo registry when ``enqueue_push`` is true (skipped silently
         when ~/.odoo/images is dirty or no registry is configured).

    The function is idempotent: when the image is already present locally
    and ``force_rebuild`` is false, it returns immediately without
    invoking docker.
    """
    inputs = compute_base_inputs(config)
    if inputs is None:
        return None

    tag = inputs["tag"]
    if not force_rebuild and image_exists_locally(tag):
        click.secho(
            f"Base image {tag} already present — skipping base build.",
            fg="green",
        )
        return tag

    if try_pull and not force_rebuild:
        try:
            from .lib_zodoo_registry import try_pull_base_image

            if try_pull_base_image(config, inputs):
                return tag
        except Exception as e:
            click.secho(
                f"Base image pull attempt failed: {e}. "
                "Falling back to local build.",
                fg="yellow",
            )

    context = _resolve_build_context(config)
    if context is None or not context.exists():
        click.secho(
            "Cannot build base image: run.build.odoo directory missing. "
            "Run `odoo reload` first.",
            fg="red",
        )
        raise RuntimeError("run.build.odoo missing — cannot build base image")

    # Render the Dockerfile.base with all snippets inlined and write it
    # next to the build context so docker can find it.
    rendered = render_base_dockerfile(inputs["dockerfile_base_text"])
    rendered_path = context / f"Dockerfile.base.{inputs['base_hash']}"
    rendered_path.write_text(rendered)

    click.secho(
        f"Building base image {tag}\n"
        f"  context:    {context}\n"
        f"  dockerfile: {rendered_path}\n"
        f"  hash:       {inputs['base_hash']}",
        fg="cyan",
    )

    cmd = ["docker", "build", "-t", tag, "-f", str(rendered_path)]
    cmd += _docker_build_args(config, inputs)
    cmd += [str(context)]

    env = dict(os.environ)
    env.setdefault("DOCKER_BUILDKIT", "1")

    proc = subprocess.run(cmd, env=env)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)

    click.secho(f"Built base image {tag}", fg="green")

    if enqueue_push:
        try:
            from .lib_zodoo_registry import enqueue_base_image_upload

            enqueue_base_image_upload(config, inputs)
        except Exception as e:
            click.secho(
                f"Could not enqueue base image upload: {e}", fg="yellow"
            )

    return tag


def cross_build_base_image(config, inputs):
    """Build & push the base image for the *other* architecture via buildx.

    Mirrors :func:`zodoo.lib_zodoo_registry._build_and_push_other_arch`
    but adapted for base images: uses our rendered ``Dockerfile.base``,
    pushes directly to ``zodoo-odoo-base:<v>-<hash>-<otherarch>``, runs
    detached (Python compile via QEMU takes ages — don't block the
    caller).

    Returns the detached log file path on success, ``None`` if skipped
    (no registry, no run.build.odoo).
    """
    from .lib_zodoo_registry import _get_registry_config, _is_arm

    reg = _get_registry_config(config)
    if not reg:
        click.secho(
            "Skipping base cross-build: no zodoo registry configured.",
            fg="yellow",
        )
        return None

    other_arch_name = "amd64" if _is_arm() else "arm64"
    other_platform = f"linux/{other_arch_name}"

    context = _resolve_build_context(config)
    if context is None or not context.exists():
        click.secho(
            "Cannot cross-build base image: run.build.odoo missing. "
            "Run `odoo reload` first.",
            fg="red",
        )
        return None

    rendered = render_base_dockerfile(inputs["dockerfile_base_text"])
    rendered_path = (
        context / f"Dockerfile.base.{inputs['base_hash']}.{other_arch_name}"
    )
    rendered_path.write_text(rendered)

    try:
        v = int(float(inputs["odoo_version"]))
    except (TypeError, ValueError):
        v = inputs["odoo_version"]
    registry_image = (
        f"{reg['url']}/zodoo-odoo-base:"
        f"{v}-{inputs['base_hash']}-{other_arch_name}"
    )

    build_args = _docker_build_args(config, inputs)

    cmd = (
        [
            "docker",
            "buildx",
            "build",
            "--platform",
            other_platform,
            "--push",
            "-t",
            registry_image,
            "-f",
            str(rendered_path),
        ]
        + build_args
        + [str(context)]
    )

    log_file = (
        Path.home()
        / ".odoo"
        / "log"
        / f"cross_build_base_{v}_{inputs['base_hash']}_{other_arch_name}.log"
    )
    log_file.parent.mkdir(parents=True, exist_ok=True)

    click.secho(
        f"Background: building base image for {other_platform} (detached, "
        f"slow via QEMU)\n"
        f"  target: {registry_image}\n"
        f"  log:    {log_file}",
        fg="yellow",
    )
    with open(log_file, "w") as fh:
        subprocess.Popen(
            cmd,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return log_file
