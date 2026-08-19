"""Keep the generated requirements artifacts in sync with their inputs.

Three files in the project root are *generated* from the requirements inputs
(``requirements.static``, the module manifests' ``external_dependencies`` and
Odoo's own ``requirements.txt``):

    requirements.txt        project pip delta
    requirements.txt.all    everything that gets installed
    requirements.hash       sha of the resolved dependency set

Two of them feed the image tag (``odoo/registry_tag.yml``:
``include_requirements_hash`` and ``project_files: requirements.txt.all``), and
the resolved list is baked into the compose build args. If an input changes but
the generated files are not refreshed, the tag stays *identical* — every machine
keeps pulling the old image although a new library was requested, and nothing
anywhere complains. That happened with the fonttools requirement: the commit
touched only ``requirements.static``, so no machine ever got fonttools.

This module detects that state by resolving the dependencies again and comparing
the result with ``requirements.hash``. On a mismatch it regenerates everything
via ``odoo reload`` (which rewrites the files *and* the compose build args —
rewriting only the hash would produce a fresh tag for an image that still
installs the stale list, which is worse than the original bug).
"""

import importlib.util
import subprocess
from pathlib import Path

import click

IMAGES_DIR = Path.home() / ".odoo" / "images"

# The generated artifacts, relative to the project root.
GENERATED_FILES = (
    "requirements.txt",
    "requirements.txt.all",
    "requirements.hash",
)


def _load_odoo_after_compose():
    """Import the odoo image hook so its dependency resolution can be reused.

    Duplicating the resolution here would be the more obvious approach and the
    wrong one: the day the two implementations disagree, this guard starts
    reporting phantom staleness on every build.
    """
    path = IMAGES_DIR / "odoo" / "__after_compose.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(
        "zodoo_requirements_guard_after_compose", str(path)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hook_globals():
    from . import module_tools, tools
    from .module_tools import Module, Modules

    return dict(
        Modules=Modules(),
        tools=tools,
        module_tools=module_tools,
        Module=Module,
    )


def _python_version(config, settings):
    if float(settings["ODOO_VERSION"]) < 13.0:
        return (3, 8, 3)
    return tuple(int(x) for x in config.ODOO_PYTHON_VERSION.split("."))


def expected_requirements_hash(config, settings):
    """Resolve the dependencies and return the hash requirements.hash must hold.

    Returns None when the hash cannot be determined (old Odoo version, hook
    missing, resolution failing) — the caller then simply skips the check
    instead of blocking a build over a diagnostic.
    """
    hook = _load_odoo_after_compose()
    if hook is None:
        return None
    if float(config.ODOO_VERSION) < 13.0:
        return None

    globals_ = _hook_globals()
    python_version = _python_version(config, settings)

    all_dependencies = hook._get_dependencies(config, globals_, python_version)

    # requirements.static wins over collected deps — same order as the hook.
    static_reqs_path = config.WORKING_DIR / "requirements.static"
    if static_reqs_path.exists():
        static_reqs = static_reqs_path.read_text().splitlines()
        all_dependencies["pip"] = hook._remove_requirements_from_requirements(
            all_dependencies["pip"], static_reqs
        )
        all_dependencies["pip"] += static_reqs

    value = ""
    for key in sorted(all_dependencies.keys()):
        value += str(all_dependencies[key])
    value += str(python_version)
    return hook.get_string_hash(value)


def _stored_requirements_hash(config):
    path = config.WORKING_DIR / "requirements.hash"
    if not path.exists():
        return None
    return path.read_text().strip()


def _dirty_generated_files(config):
    """Which generated files differ from git HEAD."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--"] + list(GENERATED_FILES),
            cwd=str(config.WORKING_DIR),
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except OSError:
        return []
    return [line[3:].strip() for line in out.splitlines() if line.strip()]


def ensure_requirements_current(config, settings, autofix=True):
    """Regenerate the requirements artifacts if they no longer match the inputs.

    Called before image tags are computed. Never raises on its own problems: a
    guard that breaks builds when it cannot resolve dependencies would be worse
    than the bug it guards against.
    """
    try:
        expected = expected_requirements_hash(config, settings)
    except Exception as ex:  # noqa: BLE001 - diagnostics must not break builds
        click.secho(
            f"Could not verify requirements.hash ({ex}). "
            "Continuing without the check.",
            fg="yellow",
        )
        return False

    if expected is None:
        return False

    stored = _stored_requirements_hash(config)
    if stored == expected:
        _warn_about_uncommitted(config)
        return False

    click.secho(
        "\nrequirements.hash does not match the current requirements "
        f"(stored: {stored or 'missing'}, expected: {expected}).\n"
        "The image tag is derived from these generated files, so without a "
        "refresh every machine would keep pulling the old image.",
        fg="yellow",
    )

    if not autofix:
        click.secho(
            "Run 'odoo reload' and commit the requirements files.", fg="red"
        )
        return True

    # --no-gimera-apply on purpose: this runs from inside 'odoo build', and a
    # build must never quietly re-vendor submodules. Regenerating the compose
    # file and the requirements artifacts is all that is needed here.
    click.secho(
        "Regenerating them now: odoo reload --no-gimera-apply", fg="yellow"
    )
    subprocess.check_call(
        ["odoo", "reload", "--no-gimera-apply"], cwd=str(config.WORKING_DIR)
    )
    _warn_about_uncommitted(config)
    return True


def _warn_about_uncommitted(config):
    """Point out generated files that only exist locally.

    Regenerating is half the job: as long as the refreshed files sit
    uncommitted, every *other* machine still computes the old tag from the
    committed ones — which is exactly how a fix ends up living on a single
    developer's laptop.
    """
    dirty = _dirty_generated_files(config)
    if not dirty:
        return
    click.secho(
        "These generated requirements files are not committed: "
        + ", ".join(dirty)
        + "\nCommit them together with requirements.static, otherwise other "
        "machines keep computing the previous image tag.",
        fg="yellow",
    )
