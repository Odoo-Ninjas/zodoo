import os
import shutil
import sys
import tempfile
import click
import subprocess
import re
from pathlib import Path
from .tools import _askcontinue
from .tools import remove_webassets
from .cli import cli, pass_config, Commands
from .lib_clickhelpers import AliasedGroup
from .tools import abort
from .tools import is_git_clean
from .tools import on_osx, on_windows_wsl
from .tools import split_external_domains
from .tools import update_setting
from .tools import vscode_setting
from .tools import __assure_gitignore
from .tools import run_root_cmd

ALL_PORTS = [
    "PROXY_PORT",
    "DEBUG_PORT",
    "HOST_DB_PORT",
    "ODOO_PYTHON_DEBUG_PORT",
]


@cli.group(
    cls=AliasedGroup,
    help="Setup and maintenance commands (ports, web assets, upgrade, status).",
)
@pass_config
def setup(config):
    pass


@setup.command(
    help="Find and assign the next free port for PROXY_PORT, DEBUG_PORT (and HOST_DB_PORT on macOS/WSL)."
)
@pass_config
@click.pass_context
def next_port(ctx, config):
    ports = list(x for x in ALL_PORTS)
    if not (on_osx() or on_windows_wsl()):
        ports.remove("HOST_DB_PORT")
    _setup_port(ctx, config, ports)


def _setup_port(ctx, config, required_ports):
    for required_port in required_ports:
        if (
            getattr(config, required_port)
            and str(getattr(config, required_port)) != "80"
        ):
            click.secho(
                f"Port {required_port} is already configured: {getattr(config, required_port)}"
            )
            continue
        # perhaps not reloaded:
        settings = config.files["project_settings"]
        content = ""
        if settings.exists():
            content = settings.read_text() if settings.exists() else ""
            # hacky...with =80
            if (
                f"{required_port}=" in content
                and "{required_port}=80" not in content
            ):
                click.secho(f"Already configured: {content}")
                return
        port = _next_port(config)
        update_setting(config, required_port, port)
        click.secho(
            f"Configured {required_port}: {port}. Please reload and restart machines."
        )


def _next_port(config):
    PORTS = {2000}  # usually starting with 1023
    parentfolder = config.dirs["user_conf_dir"]
    for file in parentfolder.glob("settings.*"):
        lines = [
            x
            for x in file.read_text().splitlines()
            if any(
                x.startswith(SETTING_NAME + "=") for SETTING_NAME in ALL_PORTS
            )
        ]
        for line in lines:
            for port in re.findall(r"\d+", line):
                PORTS.add(int(port))
    port = max(PORTS) + 1
    return port


@setup.command(name="remove-web-assets")
@pass_config
@click.pass_context
def remove_web_assets(ctx, config):
    """
    if odoo-web interface is broken (css, js) then purging the web-assets helps;
    they are usually recreated when admin login
    """
    from .odoo_config import current_version

    _askcontinue(config)
    conn = config.get_odoo_conn().clone(dbname=config.dbname)
    remove_webassets(conn)
    if current_version() <= 10.0:
        click.echo("Please login as admin, so that assets are recreated.")


# Mirror of ASSET_BUNDLES_DEFAULT in odoo/bin/tools.py. Kept here so the CLI
# entrypoint can run before/without the odoo container's tools.py being
# importable. Override per-call via ODOO_WARMUP_BUNDLES.
_ASSET_BUNDLES_DEFAULT = (
    "web.assets_common,web.assets_frontend,web.assets_backend,"
    "web.assets_common_lazy,web.assets_frontend_lazy,"
    "web.assets_common_minimal,web.assets_frontend_minimal,"
    "web.assets_backend_prod_only"
)


@setup.command(name="regenerate-assets")
@pass_config
@click.pass_context
def regenerate_assets(ctx, config):
    """
    Pre-render all asset bundles into the DB so a subsequent dump ships
    with bundle attachments already in place (no cold-render on first
    request after restore). Pairs with `remove-web-assets`.
    """
    bundles = [
        b.strip()
        for b in os.getenv(
            "ODOO_WARMUP_BUNDLES", _ASSET_BUNDLES_DEFAULT
        ).split(",")
        if b.strip()
    ]
    if not bundles:
        click.secho("No bundles to regenerate.", fg="yellow")
        return
    click.secho(
        f"Pre-generating {len(bundles)} asset bundles via odoo-shell..."
    )
    script = (
        f"bundles = {bundles!r}\n"
        "for _b in bundles:\n"
        "    try:\n"
        "        env['ir.qweb']._get_asset_link_urls(_b)\n"
        "        env['ir.qweb']._get_asset_nodes(_b)\n"
        "    except Exception as _e:\n"
        "        print(f'asset regenerate {_b}: {_e}')\n"
        "env.cr.commit()\n"
        "print('regenerated assets:', bundles)\n"
    )
    Commands.invoke(ctx, "odoo-shell", command=[script])


@setup.command()
@pass_config
def status(config):
    _status(config)


def _status(config):
    color = "yellow"
    EXTERNAL_DOMAIN = config.EXTERNAL_DOMAIN
    if not EXTERNAL_DOMAIN:
        click.secho(
            "No external domain configured, please set: EXTERNAL_DOMAIN",
            fg="red",
        )
    click.secho("projectname: ", nl=False)
    click.secho(config.project_name, fg=color, bold=True)
    click.secho("version: ", nl=False)
    click.secho(config.odoo_version, fg=color, bold=True)
    click.secho("db: ", nl=False)
    click.secho(
        f"{config.dbname}@{config.db_host} (user: {config.db_user})",
        fg=color,
        bold=True,
    )
    if config.PROXY_PORT:
        domains = split_external_domains(EXTERNAL_DOMAIN) or [""]
        for idx, d in enumerate(domains):
            url = f"{d}:{config.PROXY_PORT}" if d else f":{config.PROXY_PORT}"
            click.secho("url: " if idx == 0 else "     ", nl=False)
            click.secho(url, fg=color, bold=True)

    for key in [
        "DEFAULT_DEV_PASSWORD",
        "ODOO_DEMO",
        "ODOO_QUEUEJOBS_CHANNELS",
        "RUN_ODOO_CRONJOBS",
    ]:
        click.secho(f"{key}:", nl=False, fg=color)
        click.secho(getattr(config, key))

    msg_file = config.files["project_msg"]
    if msg_file.exists():
        msg = msg_file.read_text().strip()
        if msg:
            click.secho("")
            click.secho(msg, fg="cyan")


@setup.command(
    name="edit-msg", help="Edit the project message shown in status."
)
@pass_config
def edit_msg(config):
    msg_file = config.files["project_msg"]
    if not msg_file.exists():
        msg_file.parent.mkdir(parents=True, exist_ok=True)
        msg_file.write_text("")
    editor = os.environ.get("EDITOR", "vi")
    subprocess.call([editor, str(msg_file)])


def _show_changelog_since(images_dir, old_version):
    """Show changelog entries for versions newer than old_version using less."""
    changelog = images_dir / "CHANGELOG.md"
    if not changelog.exists() or not old_version:
        return

    lines = changelog.read_text().splitlines()
    collected = []
    for line in lines:
        # Match version headers like "## 0.12.0 — April 2026" or "## 0.7.0"
        m = re.match(r"^## (\S+)", line)
        if m:
            version = m.group(1)
            if version == old_version:
                break
        collected.append(line)

    # Strip leading blank lines and the "# Changelog" header
    while collected and (
        not collected[0].strip() or collected[0].startswith("# ")
    ):
        collected.pop(0)

    if not collected:
        return

    text = "\n".join(collected) + "\n"
    click.secho(f"\nChangelog since v{old_version}:\n", fg="green", bold=True)
    try:
        proc = subprocess.Popen(["less", "-R"], stdin=subprocess.PIPE)
        proc.communicate(input=text.encode())
    except (FileNotFoundError, BrokenPipeError):
        click.echo(text)


@click.option("-I", "--no-install", is_flag=True)
@setup.command(help="Upgrade zodoo")
@pass_config
@click.pass_context
def upgrade(ctx, config, no_install):

    # Production installs pin to the latest release tag. If CI is currently
    # running on main, a new release is probably minutes away — let the user
    # wait so they upgrade straight to it. Skipped for devmode/alpha (those
    # track a branch, not releases) and never blocks on API/network errors.
    if not _zodoo_devmode(config) and not _zodoo_alpha(config):
        running = _release_pipelines_running(config)
        if running:
            click.secho(
                f"\nA new zodoo version may be on the way — "
                f"{len(running)} pipeline(s) currently running on main:",
                fg="yellow",
            )
            for r in running:
                click.secho(
                    f"  - {r['name']} ({r['status']})  {r['html_url']}",
                    fg="yellow",
                )
            click.secho(
                "Waiting a few minutes lets you upgrade straight to the new "
                "release.",
                fg="yellow",
            )
            if sys.stdin.isatty():
                if not click.confirm("Upgrade anyway now?", default=False):
                    click.secho("Upgrade cancelled.", fg="cyan")
                    return

    stashed = False
    if not is_git_clean(config.dirs["images"]):
        click.secho("Stashing local changes...", fg="yellow")
        subprocess.run(
            ["git", "stash", "--include-untracked"],
            cwd=config.dirs["images"],
            check=True,
        )
        stashed = True

    try:
        images_dir = config.dirs["images"]
        version_file = images_dir / "VERSION"
        old_version = (
            version_file.read_text().strip() if version_file.exists() else ""
        )

        if _zodoo_devmode(config):
            changed = _upgrade_track_main(images_dir)
        elif _zodoo_alpha(config):
            changed = _upgrade_track_alpha(images_dir)
        else:
            changed = _upgrade_checkout_latest_tag(images_dir)

        if not changed:
            return

        if not no_install:
            _reinstall()
        _show_changelog_since(images_dir, old_version)

        _update_gimera_src(config)
        _fix_permissions(config, [str(images_dir)])
    finally:
        if stashed:
            click.secho("Restoring stashed changes...", fg="yellow")
            subprocess.run(
                ["git", "stash", "pop"],
                cwd=config.dirs["images"],
                check=False,
            )


def _zodoo_devmode(config):
    """True when ZODOO_DEVMODE=1 (env, user settings, or defaults).

    Used by `odoo setup upgrade` to decide whether to track `main` (dev
    machines) or pin to the latest release tag (production installs).
    """
    val = os.environ.get("ZODOO_DEVMODE")
    if val is None:
        try:
            from .myconfigparser import MyConfigParser

            user_settings_file = config.files.get("user_settings")
            if user_settings_file and Path(user_settings_file).exists():
                val = MyConfigParser(user_settings_file).get(
                    "ZODOO_DEVMODE", ""
                )
        except Exception:
            val = None
    if not val:
        val = getattr(config, "ZODOO_DEVMODE", "0") or "0"
    return str(val).strip() in ("1", "true", "True", "yes", "on")


def _zodoo_alpha(config):
    """True when ZODOO_ALPHA=1 (env or user settings).

    Used by `odoo setup upgrade` to track the `alpha` branch instead of
    the latest release tag. Mirrors :func:`_zodoo_devmode` but stays
    opt-in via a separate setting so devmode users still get whatever
    branch they checked out manually.
    """
    val = os.environ.get("ZODOO_ALPHA")
    if val is None:
        try:
            from .myconfigparser import MyConfigParser

            user_settings_file = config.files.get("user_settings")
            if user_settings_file and Path(user_settings_file).exists():
                val = MyConfigParser(user_settings_file).get("ZODOO_ALPHA", "")
        except Exception:
            val = None
    if not val:
        val = getattr(config, "ZODOO_ALPHA", "0") or "0"
    return str(val).strip() in ("1", "true", "True", "yes", "on")


def _github_repo_slug(images_dir):
    """owner/repo from the origin remote, or None."""
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=images_dir,
            capture_output=True,
            encoding="utf-8",
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return None
    m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def _release_pipelines_running(config):
    """Queued/running GitHub Actions runs on `main`.

    Returns a list of {name, status, html_url} dicts, or None when it could
    not be determined (offline, rate-limited, non-GitHub remote, ...). Never
    raises — upgrading must not depend on GitHub being reachable. Works without
    authentication on the public repo (subject to GitHub's anonymous rate
    limit).
    """
    try:
        import json
        import urllib.request

        slug = _github_repo_slug(config.dirs["images"])
        if not slug:
            return None
        url = (
            f"https://api.github.com/repos/{slug}/actions/runs"
            "?branch=main&per_page=30"
        )
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "zodoo-upgrade",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        active = {"queued", "in_progress", "waiting", "requested", "pending"}
        runs = []
        for run in data.get("workflow_runs", []):
            if run.get("status") in active:
                runs.append(
                    {
                        "name": run.get("name") or "?",
                        "status": run.get("status"),
                        "html_url": run.get("html_url") or "",
                    }
                )
        return runs
    except Exception:
        return None


def _upgrade_track_alpha(images_dir):
    """Alpha channel: switch to and fast-forward the `alpha` branch.

    Returns True when HEAD actually moved.
    """
    click.secho(
        "ZODOO_ALPHA=1 → tracking 'alpha' branch (git fetch + checkout + pull)...",
        fg="yellow",
    )
    subprocess.run(
        ["git", "fetch", "--prune", "--quiet", "origin", "alpha"],
        cwd=images_dir,
        check=True,
    )

    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=images_dir,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    ).stdout.strip()

    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=images_dir,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    ).stdout.strip()

    if current_branch != "alpha":
        click.secho("Checking out 'alpha'...", fg="yellow")
        subprocess.run(
            ["git", "checkout", "--quiet", "alpha"],
            cwd=images_dir,
            check=True,
        )

    result = subprocess.run(
        [
            "git",
            "pull",
            "--ff-only",
            "--no-edit",
            "--progress",
            "--rebase=false",
            "--autostash",
            "--quiet",
            "origin",
            "alpha",
        ],
        cwd=images_dir,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )
    output = result.stdout.strip() + result.stderr.strip()

    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=images_dir,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    ).stdout.strip()

    if head_before == head_after and "Already up to date" in output:
        click.secho("Already on latest 'alpha' — nothing to do.", fg="green")
        return False
    return True


def _upgrade_track_main(images_dir):
    """Dev mode: fast-forward pull of the current branch (usually main).

    Returns True when something was actually pulled.
    """
    click.secho(
        "ZODOO_DEVMODE=1 → tracking current branch (git pull)...", fg="yellow"
    )
    result = subprocess.run(
        [
            "git",
            "pull",
            "--ff-only",
            "--no-edit",
            "--progress",
            "--rebase=false",
            "--autostash",
            "--quiet",
        ],
        cwd=images_dir,
        capture_output=True,
        encoding="utf-8",
        text=True,
        env={**os.environ, "LANG": "C", "LC_ALL": "C"},
    )
    output = result.stdout.strip() + result.stderr.strip()
    if "Already up to date." in output or "Already up-to-date." in output:
        click.secho("Already up to date — nothing to do.", fg="green")
        return False
    return True


def _latest_semver_tag(images_dir):
    """Return the highest vX.Y.Z tag (semver-sorted), or empty string."""
    result = subprocess.run(
        ["git", "tag", "--list", "v*", "--sort=-v:refname"],
        cwd=images_dir,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    )
    for line in result.stdout.splitlines():
        tag = line.strip()
        # Guard against non-semver tags sneaking in (e.g. "vnext").
        if re.match(r"^v\d+\.\d+\.\d+$", tag):
            return tag
    return ""


def _upgrade_checkout_latest_tag(images_dir):
    """Production mode: fetch tags and check out the highest semver tag.

    Returns True when HEAD actually moved.
    """
    click.secho("Fetching tags from origin...", fg="yellow")
    subprocess.run(
        ["git", "fetch", "--tags", "--prune", "--quiet", "origin"],
        cwd=images_dir,
        check=True,
    )

    latest = _latest_semver_tag(images_dir)
    if not latest:
        abort(
            "No semver tags (vX.Y.Z) found in origin — set ZODOO_DEVMODE=1 "
            "to fall back to tracking main."
        )

    current = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=images_dir,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    ).stdout.strip()
    target = subprocess.run(
        ["git", "rev-parse", latest],
        cwd=images_dir,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    ).stdout.strip()

    if current == target:
        click.secho(
            f"Already on latest tag {latest} — nothing to do.", fg="green"
        )
        return False

    click.secho(f"Checking out {latest}...", fg="yellow")
    subprocess.run(
        ["git", "checkout", "--quiet", latest],
        cwd=images_dir,
        check=True,
    )
    return True


def _update_gimera_src(config):
    """Update the integrated gimera source unless it is in submodule mode."""
    import yaml

    zodoo_src = config.dirs["images"] / "zodoo" / "src"
    gimera_yml = zodoo_src / "gimera.yml"
    if not gimera_yml.exists():
        return
    data = yaml.safe_load(gimera_yml.read_text())
    for repo in data.get("repos", []):
        if repo.get("path") == "gimera_src":
            if repo.get("type") == "submodule":
                click.secho(
                    "gimera_src is in submodule mode - skipping update.",
                    fg="cyan",
                )
                return
            break
    else:
        return

    click.secho("Updating gimera source...", fg="yellow")
    python = (
        sys.executable
        if Path(sys.executable).exists()
        else (shutil.which("python3") or "python3")
    )
    env = {**os.environ, "PYTHONPATH": str(zodoo_src / "gimera_src")}
    subprocess.run(
        [
            python,
            "-m",
            "gimera.gimera",
            "apply",
            "gimera_src",
            "--update",
            "-I",
            "-C",
        ],
        cwd=zodoo_src,
        env=env,
        check=False,
    )


def _ensure_pipx_version():
    # pipx <1.4 misclassifies absolute paths as URL requirements under
    # packaging>=22, silently dropping --editable. Force-upgrade.
    try:
        ver = subprocess.check_output(
            ["pipx", "--version"], encoding="utf-8"
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    parts = ver.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return
    if major > 1 or (major == 1 and minor >= 4):
        return
    click.secho(
        f"Old pipx detected ({ver}) — upgrading to current.", fg="yellow"
    )
    subprocess.check_call(
        ["python3", "-m", "pip", "install", "--user", "--upgrade", "pipx"]
    )
    local_bin = os.path.expanduser("~/.local/bin")
    if local_bin not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = (
            local_bin + os.pathsep + os.environ.get("PATH", "")
        )


def _reinstall():
    _ensure_pipx_version()
    images_dir = Path(os.path.expanduser("~/.odoo/images"))
    path = str(images_dir / "zodoo" / "src")
    for name in ["zodoo", "wodoo"]:
        try:
            subprocess.check_call(["pipx", "uninstall", name], shell=False)
        except subprocess.CalledProcessError:
            pass
    cmd = ["pipx", "install", "--force", "-e", path]
    if on_osx():
        python_version = (
            (images_dir / "darwin_python_version").read_text().strip()
        )
        cmd.extend(["--python", f"python{python_version}"])
    subprocess.check_call(cmd, shell=False)
    subprocess.check_call(
        ["pipx", "inject", "--force", "zodoo", "gimera"], shell=False
    )


@setup.command(help="Reinstall zodoo python")
def reinstall():
    _reinstall()


@setup.command(
    name="zodoo-tests",
    help="Run the zodoo unit-test suite. Use --slow to include heavy "
    "end-to-end tests that need Docker + gimera + network.",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
@click.option(
    "--slow",
    is_flag=True,
    help="Include @slow E2E tests (requires Docker, minutes to run).",
)
@click.pass_context
def zodoo_tests(ctx, slow):
    zodoo_src = Path(os.path.expanduser("~/.odoo/images/zodoo/src"))
    if not (zodoo_src / "pytest.ini").exists():
        abort(f"pytest.ini not found in {zodoo_src}")

    cmd = [sys.executable, "-m", "pytest"]
    if slow:
        cmd += ["-m", "slow"]
    else:
        cmd += ["-m", "not slow"]
    cmd += ctx.args
    click.secho(f"Running: {' '.join(cmd)}", fg="yellow")
    rc = subprocess.run(cmd, cwd=zodoo_src).returncode
    sys.exit(rc)


@setup.command()
@click.argument("lines")
def produce_test_lines(lines):
    import lorem

    lines = int(lines)
    for i in range(lines):
        click.secho(lorem.paragraph())


@setup.command()
@pass_config
@click.option(
    "-o", "--old", is_flag=True, help="Uses old setuptools - odoo version 11"
)
@click.pass_context
def setup_pyenv(ctx, config, old):
    _setup_robo_pyenv(ctx, config)
    # _setup_odoo_pyenv(ctx, config, old)


def is_robot_env_installed(config):
    return _is_pyenv_installed("zodoo-robot")


def _is_pyenv_installed(name):
    path = Path(os.path.expanduser(f"~/.pyenv/versions/{name}"))
    if path.exists():
        return str(path / "bin" / "python")


def _setup_odoo_pyenv(ctx, config, old):
    raise Exception("outdated")
    from .odoo_config import MANIFEST

    name = config.project_name
    from .odoo_config import customs_dir

    SRC = customs_dir()
    python_version = config.ODOO_PYTHON_VERSION
    python_version_int = tuple(map(int, python_version.split(".")))
    python_version_int2 = python_version_int[:2]
    reqfile = SRC / "requirements.txt.all"
    manifest = MANIFEST()

    if python_version_int2 < (3, 11):
        old = True
        click.secho(
            f"Warning: Python {python_version} < 3.11 --> old modus is set (cython<3, setuptools<55).",
            fg="red",
        )
    if manifest["version"] <= 16.0:
        if not old:
            click.secho(
                "Warning: Odoo version <= 16.0 is not compatible with latest setuptools, using old setuptools and cython versions. Use --old to suppress this warning.",
                fg="red",
            )
    pyexec = _setup_pyenv(ctx, config, name, old, reqfile, python_version)
    vscode_setting("python.pythonPath", str(pyexec))
    vscode_setting("python.defaultInterpreterPath", str(pyexec))

    (SRC / ".python-version").write_text(name)
    __assure_gitignore(SRC / ".gitignore", ".python-version")


def _setup_robo_pyenv(ctx, config):
    name = "zodoo-robot"
    python_version = "3.12.11"
    pyexec = _setup_pyenv(
        ctx,
        config,
        name,
        False,
        config.dirs["images"] / "robot" / "requirements.txt",
        python_version,
    )
    vscode_setting("robotcode.python", str(pyexec))


def _setup_pyenv(ctx, config, name, old, reqfile, python_version):
    from .tools import require_homebrew

    require_homebrew()

    if on_osx():
        subprocess.run(
            [
                "brew",
                "install",
                "pyenv-virtualenv",
                "libpq",
                "libxml2",
                "libxslt",
                "zlib",
                "freetype",
                "jpeg",
                "libpng",
                "openjpeg",
                "libtiff",
                "webp",
                "little-cms2",
                "postgresql",
            ],
            check=True,
        )

    click.secho(f"Setting up pyenv {name} {python_version}...", fg="yellow")

    subprocess.run(["pyenv", "uninstall", "-f", name], check=True)
    subprocess.run(["pyenv", "install", "-s", python_version], check=True)
    subprocess.run(
        ["pyenv", "virtualenv", python_version, name],
        check=True,
    )
    pyexec = os.path.expanduser(f"~/.pyenv/versions/{name}/bin/python")

    with tempfile.TemporaryDirectory() as tmpdir:
        subdir = Path(tmpdir) / "wheels"
        if old:
            subprocess.run(
                [
                    pyexec,
                    "-mpip",
                    "install",
                    "-U",
                    "setuptools<55.0.0",
                    "cython<3",
                    "wheel",
                    "pip",
                ],
                check=True,
            )
        else:
            subprocess.run(
                [
                    pyexec,
                    "-mpip",
                    "install",
                    "-U",
                    "setuptools",
                    "cython",
                    "wheel",
                    "pip",
                ],
                check=True,
            )
        subprocess.run(
            [
                pyexec,
                "-mpip",
                "wheel",
                "--no-build-isolation",
                "--prefer-binary",
                "-r",
                str(reqfile),
                "-w",
                str(subdir),
            ],
            check=True,
        )
        subprocess.run(
            [
                pyexec,
                "-mpip",
                "install",
                "--no-build-isolation",
                "--no-index",
                "--find-links",
                str(subdir),
                "-r",
                str(reqfile),
            ],
            check=True,
        )

        # install binary version of psyco - better on platforms
        try:
            version = _get_package_version(pyexec, "psycopg2")
        except (FileNotFoundError, subprocess.CalledProcessError):
            version = _get_package_version(pyexec, "psycopg2-binary")
        if version >= (2, 9, 0):
            subprocess.run(
                [pyexec, "-mpip", "uninstall", "-y", "psycopg2"], check=True
            )
            subprocess.run(
                [
                    pyexec,
                    "-mpip",
                    "install",
                    f"psycopg2-binary=={'.'.join(map(str, version))}",
                ],
                check=True,
            )

    click.secho(f"Pyenv setup done at {pyexec}", fg="green")
    return pyexec


def _get_package_version(python, name):
    psyco = (
        subprocess.run(
            [python, "-mpip", "show", name],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )
    version = None
    for line in psyco:
        if line.startswith("Version:"):
            version = line.split(":", 1)[1].strip()
            version = tuple(int(x) for x in version.split("."))
            return version
    else:
        raise FileNotFoundError(f"Package {name} not found.")


def _fix_permissions(config, dirs_to_fix):
    import pwd
    import platform

    uid = config.owner_uid
    if not uid:
        return

    uid_int = int(uid)
    gid = pwd.getpwuid(uid_int).pw_gid
    owner = f"{uid}:{gid}"

    for path in dirs_to_fix:
        if not os.path.exists(path):
            click.secho(f"Skipping (does not exist): {path}", fg="red")
            continue

        click.secho(f"Fixing {path} to {owner} ...", fg="yellow")

        if platform.system() == "Darwin":
            # Docker Desktop on macOS proxies filesystem ops through the macOS
            # user, so container-root cannot chown host-mounted files. Use
            # native find to check ownership; if already correct, skip.
            check = subprocess.run(
                [
                    "find",
                    path,
                    "-not",
                    "-type",
                    "l",
                    "(",
                    "-not",
                    "-user",
                    str(uid_int),
                    "-o",
                    "-not",
                    "-group",
                    str(gid),
                    ")",
                    "-print",
                    "-quit",
                ],
                capture_output=True,
                text=True,
            )
            if not check.stdout.strip():
                click.secho(f"  OK: {path}", fg="green")
                continue
            try:
                run_root_cmd(["chown", "-R", owner, path])
                click.secho(f"  OK: {path}", fg="green")
            except subprocess.CalledProcessError as ex:
                click.secho(f"  FAILED: {path}: {ex}", fg="red")
            continue

        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{path}:{path}",
            "ubuntu:22.04",
            "find",
            path,
            "-not",
            "-type",
            "l",
            "(",
            "-not",
            "-user",
            str(uid),
            "-o",
            "-not",
            "-group",
            str(gid),
            ")",
            "-exec",
            "chown",
            owner,
            "{}",
            "+",
        ]
        try:
            subprocess.check_call(cmd)
            click.secho(f"  OK: {path}", fg="green")
        except subprocess.CalledProcessError as ex:
            click.secho(f"  FAILED: {path}: {ex}", fg="red")


@setup.command(
    help="Fix directory permissions via a Docker container (no sudo needed)."
)
@click.argument("paths", required=False, nargs=-1)
@pass_config
def fix_permissions(config, paths):
    if paths:
        dirs_to_fix = [os.path.abspath(os.path.expanduser(p)) for p in paths]
    else:
        dirs_to_fix = []
        for key in ["images", "run", "odoo_data_dir", "user_conf_dir"]:
            p = config.dirs.get(key)
            if p:
                p = str(p)
                if os.path.exists(p):
                    dirs_to_fix.append(p)

    if not dirs_to_fix:
        raise click.ClickException("No directories found to fix.")

    _fix_permissions(config, dirs_to_fix)


Commands.register(status)
Commands.register(fix_permissions)
Commands.register(edit_msg)
