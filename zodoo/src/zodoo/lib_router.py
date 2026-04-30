"""Manage the global / project-local nginx web-router.

This is the host-wide nginx reverse proxy formerly set up by the
`ansible-web_router` role. The router runs as its own docker-compose stack
(separate from the per-project odoo stack) and is therefore intentionally
NOT touched by `odoo restart` / `odoo down` / `odoo up`. Steer it
explicitly via `odoo router restart|reload|status|...`.

Two install modes:
- `--global` (default install_dir `/opt/proxy`): host-wide router.
- project-mode (no `--global`): per-project router under
  `<WORKING_DIR>/.odoo/router/`.

vhost configuration is persisted in `<install_dir>/vhosts.yml` (same schema
as the ansible `web_router.virtual_hosts` list). It can be loaded via
`--vhosts-file` or edited with the `vhost` subcommands.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import click
import yaml

from .cli import cli, pass_config
from .lib_clickhelpers import AliasedGroup
from .tools import abort

DEFAULT_GLOBAL_INSTALL_DIR = Path("/opt/proxy")
ROUTER_FILES_SUBDIR = "router_global"
PRESERVE_ON_SYNC = {
    "sites-available",
    "sites-enabled",
    "sites-incoming",
    "sites-last-deployed",
    "letsencrypt",
    "custom_ssl",
    "htpasswd",
    "webapp_download",
    "vhosts.yml",
    ".env",
    "docker-compose.override.yml",
}


def _images_dir(config):
    return Path(config.dirs["images"])


def _router_files_dir(config):
    return _images_dir(config) / ROUTER_FILES_SUBDIR


def _resolve_install_dir(config, is_global, install_dir):
    if install_dir:
        return Path(install_dir).expanduser().resolve()
    if is_global:
        return DEFAULT_GLOBAL_INSTALL_DIR
    if not config.WORKING_DIR:
        abort(
            "Project-mode router setup requires running inside an odoo "
            "project, or pass --global / --install-dir."
        )
    run_router = Path(config.dirs["run/router"])
    legacy = Path(config.WORKING_DIR) / ".odoo" / "router"
    if legacy.exists() and not run_router.exists():
        shutil.copytree(legacy, run_router)
    return run_router


def _load_vhosts(install_dir):
    vhosts_file = install_dir / "vhosts.yml"
    if not vhosts_file.exists():
        return []
    data = yaml.safe_load(vhosts_file.read_text()) or []
    if not isinstance(data, list):
        abort(f"{vhosts_file} must be a YAML list of vhost dicts.")
    return data


def _save_vhosts(install_dir, vhosts):
    (install_dir / "vhosts.yml").write_text(
        yaml.safe_dump(vhosts, sort_keys=False)
    )


def _dc(install_dir, *args, check=True, capture=False):
    cmd = ["docker", "compose", *args]
    return subprocess.run(
        cmd,
        cwd=install_dir,
        check=check,
        text=True,
        capture_output=capture,
    )


def _ensure_network(name):
    res = subprocess.run(
        ["docker", "network", "create", name],
        capture_output=True,
        text=True,
    )
    if res.returncode and "already exists" not in res.stderr:
        abort(f"Failed to create docker network {name}: {res.stderr}")


def _sync_files(src, dst):
    """Copy contents of src/ into dst/, preserving live state directories."""
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if entry.name in PRESERVE_ON_SYNC and (dst / entry.name).exists():
            continue
        target = dst / entry.name
        if entry.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)
    for d in (
        "sites-available",
        "sites-enabled",
        "sites-incoming",
        "sites-last-deployed",
        "letsencrypt",
        "custom_ssl",
        "htpasswd",
        "webapp_download",
        "www",
    ):
        (dst / d).mkdir(exist_ok=True)


def _write_env(install_dir, binding_80, binding_443):
    (install_dir / ".env").write_text(
        f"BINDING_80={binding_80}\nBINDING_443={binding_443}\n"
    )


def _patch_compose_networks(install_dir, networks):
    """Add external networks to docker-compose.yml (idempotent)."""
    if not networks:
        return
    dcfile = install_dir / "docker-compose.yml"
    config = yaml.safe_load(dcfile.read_text())
    svc_nets = config["services"]["router"].setdefault("networks", ["default"])
    config.setdefault("networks", {})
    for net in networks:
        _ensure_network(net)
        if net not in svc_nets:
            svc_nets.append(net)
        config["networks"][net] = {"name": net, "external": True}
    dcfile.write_text(yaml.safe_dump(config, sort_keys=False))


def _render_and_sync_vhosts(config, install_dir, vhosts):
    if not vhosts:
        return False  # nothing to render
    src_root = _router_files_dir(config)
    incoming = install_dir / "sites-incoming"
    if incoming.exists():
        shutil.rmtree(incoming)
    incoming.mkdir()
    subprocess.run(
        [
            sys.executable,
            str(src_root / "render_configs.py"),
            str(src_root / "templates"),
            str(incoming),
        ],
        input=json.dumps(vhosts),
        check=True,
        text=True,
    )
    res = subprocess.run(
        [sys.executable, "bin/sync_configs.py"],
        cwd=install_dir,
        capture_output=True,
        text=True,
    )
    if res.returncode not in (0, 10):
        abort(f"sync_configs failed: {res.stderr}")
    for vhost in vhosts:
        ba = vhost.get("basic_auth")
        if ba:
            subprocess.run(
                [
                    sys.executable,
                    "bin/setup_basic_auth.py",
                    vhost["server_name"],
                    json.dumps(ba),
                ],
                cwd=install_dir,
                check=True,
            )
    return res.returncode == 10  # True == reload required


@cli.group(
    cls=AliasedGroup,
    help=(
        "Manage the global/project nginx web-router. "
        "NOTE: not affected by 'odoo restart' — use 'odoo router restart'."
    ),
)
@pass_config
def router(config):
    pass


@router.command(name="setup", help="Install or update the web-router.")
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    help=f"Install host-wide ({DEFAULT_GLOBAL_INSTALL_DIR}).",
)
@click.option(
    "--install-dir",
    default=None,
    help="Override install dir (default: /opt/proxy with --global, "
    "<project>/.odoo/router otherwise).",
)
@click.option("--binding-80", default="80", show_default=True)
@click.option("--binding-443", default="443", show_default=True)
@click.option(
    "--network",
    "networks",
    multiple=True,
    help="External docker network(s) the router should join. Repeatable.",
)
@click.option(
    "--vhosts-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="YAML/JSON file with virtual_hosts (replaces existing vhosts.yml).",
)
@click.option(
    "--no-start",
    is_flag=True,
    help="Skip 'docker-compose up -d' at the end (files only).",
)
@pass_config
def setup_(
    config,
    is_global,
    install_dir,
    binding_80,
    binding_443,
    networks,
    vhosts_file,
    no_start,
):
    install_dir = _resolve_install_dir(config, is_global, install_dir)
    src_root = _router_files_dir(config)
    docker_files_src = src_root / "files"
    if not docker_files_src.exists():
        abort(f"Router source files missing: {docker_files_src}")

    click.secho(f"Installing router into {install_dir}", fg="green")
    _sync_files(docker_files_src, install_dir)
    _write_env(install_dir, binding_80, binding_443)
    _patch_compose_networks(install_dir, list(networks))

    if vhosts_file:
        data = yaml.safe_load(Path(vhosts_file).read_text()) or []
        _save_vhosts(install_dir, data)

    vhosts = _load_vhosts(install_dir)
    _render_and_sync_vhosts(config, install_dir, vhosts)

    if no_start:
        click.secho(
            f"Files installed in {install_dir}. Skipping start.", fg="yellow"
        )
        return

    if not is_global and getattr(config, "run_router", False):
        click.secho(
            "Router files installed. RUN_ROUTER=1 detected — "
            "managed by project compose. Run 'odoo up -d' to start.",
            fg="green",
        )
        return

    _dc(install_dir, "pull")
    _dc(install_dir, "build")
    _dc(install_dir, "up", "-d")
    click.secho(
        f"Router up. Run 'odoo router ssl' to (re)issue certificates.",
        fg="green",
    )


def _install_dir_from_opts(config, is_global, install_dir):
    return _resolve_install_dir(config, is_global, install_dir)


_global_opts = [
    click.option("--global", "is_global", is_flag=True),
    click.option("--install-dir", default=None),
]


def _add_global_opts(cmd):
    for opt in reversed(_global_opts):
        cmd = opt(cmd)
    return cmd


@router.command(help="Restart the router container.")
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@pass_config
def restart(config, is_global, install_dir):
    d = _install_dir_from_opts(config, is_global, install_dir)
    _dc(d, "restart")


@router.command(name="reload", help="Reload nginx config without restart.")
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@pass_config
def reload_(config, is_global, install_dir):
    d = _install_dir_from_opts(config, is_global, install_dir)
    _dc(d, "exec", "-T", "router", "nginx", "-s", "reload")


@router.command(help="Show router container status.")
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@pass_config
def status(config, is_global, install_dir):
    d = _install_dir_from_opts(config, is_global, install_dir)
    _dc(d, "ps")


@router.command(help="Stop and remove the router container.")
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@pass_config
def down(config, is_global, install_dir):
    d = _install_dir_from_opts(config, is_global, install_dir)
    _dc(d, "down")


@router.command(name="apply-vhosts", help="Re-render vhosts and reload nginx.")
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@pass_config
@click.pass_context
def apply_vhosts(ctx, config, is_global, install_dir):
    d = _install_dir_from_opts(config, is_global, install_dir)
    vhosts = _load_vhosts(d)
    reload_required = _render_and_sync_vhosts(config, d, vhosts)
    if reload_required:
        ctx.invoke(reload_, is_global=is_global, install_dir=install_dir)
        click.secho("Reloaded.", fg="green")
    else:
        click.secho("No change.", fg="yellow")


@router.command(
    name="ssl",
    help="(Re-)issue SSL certificates via certbot for use_certbot vhosts.",
)
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@pass_config
def ssl_(config, is_global, install_dir):
    d = _install_dir_from_opts(config, is_global, install_dir)
    for vhost in _load_vhosts(d):
        if not vhost.get("use_certbot"):
            continue
        subprocess.run(
            [sys.executable, "bin/setup_ssl.py", vhost["server_name"]],
            cwd=d,
            check=True,
        )
    _dc(d, "exec", "-T", "router", "nginx", "-s", "reload", check=False)


# ---------------------------------------------------------------------------
# vhost subcommands
# ---------------------------------------------------------------------------


@router.group(cls=AliasedGroup, help="Manage virtual hosts (vhosts.yml).")
def vhost():
    pass


@vhost.command(name="list", help="List configured vhosts.")
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@pass_config
def vhost_list(config, is_global, install_dir):
    d = _install_dir_from_opts(config, is_global, install_dir)
    for v in _load_vhosts(d):
        click.echo(f"  {v['server_name']:<40s}  {v.get('template', '?')}")


@vhost.command(name="show", help="Show one vhost as YAML.")
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@click.argument("server_name")
@pass_config
def vhost_show(config, is_global, install_dir, server_name):
    d = _install_dir_from_opts(config, is_global, install_dir)
    for v in _load_vhosts(d):
        if v["server_name"] == server_name:
            click.echo(yaml.safe_dump(v, sort_keys=False))
            return
    abort(f"vhost not found: {server_name}")


@vhost.command(name="remove", help="Remove a vhost and re-apply.")
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@click.argument("server_name")
@pass_config
@click.pass_context
def vhost_remove(ctx, config, is_global, install_dir, server_name):
    d = _install_dir_from_opts(config, is_global, install_dir)
    vhosts = _load_vhosts(d)
    new = [v for v in vhosts if v["server_name"] != server_name]
    if len(new) == len(vhosts):
        abort(f"vhost not found: {server_name}")
    _save_vhosts(d, new)
    ctx.invoke(apply_vhosts, is_global=is_global, install_dir=install_dir)


@vhost.command(
    name="add", help="Add or replace a vhost from a YAML/JSON file."
)
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@click.argument("vhost_file", type=click.Path(exists=True, dir_okay=False))
@pass_config
@click.pass_context
def vhost_add(ctx, config, is_global, install_dir, vhost_file):
    d = _install_dir_from_opts(config, is_global, install_dir)
    new_vhost = yaml.safe_load(Path(vhost_file).read_text())
    if not isinstance(new_vhost, dict) or "server_name" not in new_vhost:
        abort(
            "vhost file must be a single YAML dict with at least 'server_name'."
        )
    vhosts = _load_vhosts(d)
    vhosts = [
        v for v in vhosts if v["server_name"] != new_vhost["server_name"]
    ]
    vhosts.append(new_vhost)
    _save_vhosts(d, vhosts)
    ctx.invoke(apply_vhosts, is_global=is_global, install_dir=install_dir)
