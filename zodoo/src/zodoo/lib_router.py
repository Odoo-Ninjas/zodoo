"""Manage the global / project-local nginx web-router.

This is the host-wide nginx reverse proxy formerly set up by the
`ansible-web_router` role. The router runs as its own docker-compose stack
(separate from the per-project odoo stack) and is therefore intentionally
NOT touched by `odoo restart` / `odoo down` / `odoo up`. Steer it
explicitly via `odoo router restart|reload|docker-status|...`.

Two install modes:
- `--global` (default install_dir `/opt/proxy`): host-wide router.
- project-mode (no `--global`): per-project router under
  `<WORKING_DIR>/.odoo/router/`.

vhost configuration is persisted in `<install_dir>/vhosts.yml` (same schema
as the ansible `web_router.virtual_hosts` list). It can be loaded via
`--vhosts-file` or edited with the `vhost` subcommands.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import click
import inquirer
import yaml

from .cli import cli, pass_config
from .lib_clickhelpers import AliasedGroup
from .tools import abort, is_interactive, update_setting

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
    if config.WORKING_DIR:
        update_setting(config, "RUN_PROXY_PUBLISHED", "0")
        click.secho(
            "Set RUN_PROXY_PUBLISHED=0 (proxy ports not published; router handles public traffic).",
            fg="yellow",
        )

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


@router.command(name="docker-status", help="Show router container status.")
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@pass_config
def docker_status(config, is_global, install_dir):
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


# ---------------------------------------------------------------------------
# vhost wizard
# ---------------------------------------------------------------------------

# Which fields a template cannot render without. Everything else is guarded
# with "is defined" in the templates and therefore optional.
REQUIRED_FIELDS = {
    "upstream": [
        "server_name",
        "upstream_name",
        "upstream_server",
        "upstream_port",
        "timeout",
    ],
    "upstream_direct_odoo": [
        "server_name",
        "upstream_name",
        "upstream_server",
        "upstream_port",
        "timeout",
    ],
    "redirect": ["server_name", "redirect_to"],
    "static_files": ["server_name", "folder"],
    "existing_ssl_certificates": ["server_name"],
}

# Optional fields offered when editing, with the type so we can ask properly.
OPTIONAL_FIELDS = [
    ("use_certbot", "bool", "get a Let's Encrypt certificate"),
    ("allowed_ips", "text", "restrict to these networks (comma separated)"),
    ("allowlist_public_paths", "text", "paths open despite the allowlist"),
    ("basic_auth", "basic_auth", "user/password prompt"),
    ("rate_limit", "text", "per-IP rate limit, e.g. 30r/m"),
    ("rate_limit_burst", "int", "burst for the rate limit"),
    ("client_max_body_size", "text", "upload limit, e.g. 512M, 0 = unlimited"),
    ("upstream_scheme", "text", "https if the backend speaks TLS itself"),
    ("filename", "text", "file name under sites-enabled"),
    ("certificate_name", "text", "directory under /etc/ssl/custom_ssl"),
]
INT_FIELDS = {"upstream_port", "timeout", "rate_limit_burst"}


def _suggest_backend_address(existing):
    """Best guess for upstream_server: what the other vhosts point at, else a
    local address. Beats an empty prompt - most vhosts on a host share it."""
    addresses = [
        v["upstream_server"] for v in existing if v.get("upstream_server")
    ]
    if addresses:
        return max(set(addresses), key=addresses.count)
    try:
        from .tools import get_local_ips

        ips = [ip for ip in get_local_ips() if not ip.startswith("169.254.")]
        if ips:
            return sorted(ips)[0]
    except Exception:
        pass
    return ""


def _suggest_port(existing, template):
    """One above the highest port already in use, so it is free by default."""
    ports = [
        int(v["upstream_port"])
        for v in existing
        if str(v.get("upstream_port", "")).isdigit()
    ]
    if ports:
        return str(max(ports) + 1)
    return "6000" if template == "upstream_direct_odoo" else "8069"


def _missing_required(vhost):
    required = REQUIRED_FIELDS.get(vhost.get("template"), ["server_name"])
    return [f for f in required if not vhost.get(f)]


VHOST_TEMPLATES = [
    ("upstream_direct_odoo", "Odoo instance (adds the chat upstream on 8072)"),
    ("upstream", "any service behind the proxy"),
    ("redirect", "redirect to another address"),
    ("static_files", "serve a directory"),
    ("existing_ssl_certificates", "certificate block only, no backend"),
]

# `upstream_name` ends up in an nginx variable (`set $var_<name>`), so a dot or
# a dash in it produces a config nginx refuses to load.
_UPSTREAM_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _invalid(reason):
    """inquirer treats ANY truthy return from validate as 'valid' - a returned
    error string therefore passes. Raise instead, that also shows the reason.
    """
    raise inquirer.errors.ValidationError("", reason=reason)


def _require(value, reason="Required"):
    if not str(value).strip():
        _invalid(reason)
    return True


def _ask_port(key, message, default):
    def _validate(_, value):
        value = value.strip()
        if not (value.isdigit() and 1 <= int(value) <= 65535):
            _invalid("Must be a port between 1 and 65535")
        return True

    return inquirer.Text(
        key, message=message, default=default, validate=_validate
    )


def _ask_upstream_fields(server_name, existing=(), template="upstream"):
    suggested = re.sub(r"[^A-Za-z0-9_]", "_", server_name.split(".")[0])
    suggested_server = _suggest_backend_address(existing)
    suggested_port = _suggest_port(existing, template)
    answers = inquirer.prompt(
        [
            inquirer.Text(
                "upstream_name",
                message="Upstream name (letters, digits, underscore)",
                default=suggested,
                validate=lambda _, x: bool(_UPSTREAM_NAME_RE.match(x))
                or _invalid(
                    "Only letters, digits and underscore - it becomes an "
                    "nginx variable name"
                ),
            ),
            inquirer.Text(
                "upstream_server",
                message="Backend address (LAN ip of the machine, not the "
                "VPN one)",
                default=suggested_server,
                validate=lambda _, x: _require(x),
            ),
            _ask_port("upstream_port", "Backend port", suggested_port),
            _ask_port("timeout", "Proxy timeout in seconds", "600"),
        ]
    )
    if not answers:
        abort("Aborted.")
    answers["upstream_port"] = int(answers["upstream_port"])
    answers["timeout"] = int(answers["timeout"])
    return answers


def _ask_protection(vhost):
    """IP allowlist and basic auth - both easy to get wrong by hand."""
    answers = inquirer.prompt(
        [
            inquirer.Text(
                "allowed_ips",
                message="Restrict to these networks (comma separated, "
                "empty = open)",
                default="",
            ),
            inquirer.Confirm(
                "want_basic_auth", message="Add basic auth?", default=False
            ),
        ]
    )
    if not answers:
        abort("Aborted.")
    if answers["allowed_ips"].strip():
        vhost["allowed_ips"] = answers["allowed_ips"].strip()
        public = inquirer.prompt(
            [
                inquirer.Text(
                    "allowlist_public_paths",
                    message="Paths that stay open despite the allowlist "
                    "(comma separated, empty = none)",
                    default="",
                )
            ]
        )
        if public and public["allowlist_public_paths"].strip():
            vhost["allowlist_public_paths"] = public[
                "allowlist_public_paths"
            ].strip()
    if answers["want_basic_auth"]:
        creds = inquirer.prompt(
            [
                inquirer.Text(
                    "user",
                    message="Basic auth user",
                    validate=lambda _, x: _require(x),
                ),
                inquirer.Password(
                    "password",
                    message="Basic auth password",
                    validate=lambda _, x: _require(x),
                ),
            ]
        )
        if not creds:
            abort("Aborted.")
        vhost["basic_auth"] = {creds["user"]: creds["password"]}


def _collect_new_vhost(existing):
    """Ask for everything a new vhost needs and return it as a dict.

    Shared by `vhost new` and the `config` menu.
    """
    chosen = inquirer.prompt(
        [
            inquirer.List(
                "template",
                message="What kind of vhost?",
                choices=[
                    (f"{name} - {desc}", name)
                    for name, desc in VHOST_TEMPLATES
                ],
            ),
            inquirer.Text(
                "server_name",
                message="Domain (server_name)",
                validate=lambda _, x: _require(x),
            ),
        ]
    )
    if not chosen:
        abort("Aborted.")
    template = chosen["template"]
    vhost_data = {
        "template": template,
        "server_name": chosen["server_name"].strip(),
    }

    if template in ("upstream", "upstream_direct_odoo"):
        vhost_data.update(
            _ask_upstream_fields(vhost_data["server_name"], existing, template)
        )
    elif template == "redirect":
        answers = inquirer.prompt(
            [
                inquirer.Text(
                    "redirect_to",
                    message="Redirect to (a path in it means: land exactly "
                    "there, e.g. zebroo.de/experience)",
                    validate=lambda _, x: _require(x),
                )
            ]
        )
        if not answers:
            abort("Aborted.")
        vhost_data["redirect_to"] = answers["redirect_to"].strip()
    elif template == "static_files":
        answers = inquirer.prompt(
            [
                inquirer.Text(
                    "folder",
                    message="Directory to serve",
                    validate=lambda _, x: _require(x),
                )
            ]
        )
        if not answers:
            abort("Aborted.")
        vhost_data["folder"] = answers["folder"].strip()

    certbot = inquirer.prompt(
        [
            inquirer.Confirm(
                "use_certbot",
                message="Get a Let's Encrypt certificate (odoo router ssl)?",
                default=True,
            )
        ]
    )
    if certbot and certbot["use_certbot"]:
        vhost_data["use_certbot"] = True

    if template in ("upstream", "upstream_direct_odoo"):
        _ask_protection(vhost_data)

    return vhost_data


def _show_vhost(vhost_data):
    click.secho("\nThis is the vhost:\n", fg="green")
    click.echo(yaml.safe_dump([vhost_data], sort_keys=False))


@vhost.command(
    name="new",
    help="Assemble a vhost interactively. --dry-run just prints it, so it "
    "also works as a reference for the vhosts.yml schema.",
)
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the vhost and change nothing (no router needed).",
)
@pass_config
@click.pass_context
def vhost_new(ctx, config, is_global, install_dir, dry_run):
    if not is_interactive():
        abort("This is a wizard - it needs an interactive terminal.")

    existing = []
    if not dry_run:
        existing = _load_vhosts(
            _install_dir_from_opts(config, is_global, install_dir)
        )
    vhost_data = _collect_new_vhost(existing)
    _show_vhost(vhost_data)
    click.secho(
        "Rarely used fields (locations, headers, before_server_conf, "
        "client_max_body_size, rate_limit, custom certificates) are not asked "
        "for - add them by hand, see router_global/vhosts.example.yml.",
        fg="yellow",
    )
    if dry_run:
        return

    confirm = inquirer.prompt(
        [
            inquirer.Confirm(
                "save", message="Write this into vhosts.yml?", default=True
            )
        ]
    )
    if not confirm or not confirm["save"]:
        click.secho("Nothing written.", fg="yellow")
        return

    d = _install_dir_from_opts(config, is_global, install_dir)
    vhosts = _load_vhosts(d)
    replaced = any(
        v["server_name"] == vhost_data["server_name"] for v in vhosts
    )
    if replaced:
        overwrite = inquirer.prompt(
            [
                inquirer.Confirm(
                    "yes",
                    message=f"{vhost_data['server_name']} already exists - "
                    "replace it?",
                    default=False,
                )
            ]
        )
        if not overwrite or not overwrite["yes"]:
            click.secho("Nothing written.", fg="yellow")
            return
        vhosts = [
            v for v in vhosts if v["server_name"] != vhost_data["server_name"]
        ]
    vhosts.append(vhost_data)
    _save_vhosts(d, vhosts)
    click.secho(f"Written to {d / 'vhosts.yml'}.", fg="green")

    apply_now = inquirer.prompt(
        [
            inquirer.Confirm(
                "apply",
                message="Render and reload nginx now?",
                default=True,
            )
        ]
    )
    if apply_now and apply_now["apply"]:
        ctx.invoke(apply_vhosts, is_global=is_global, install_dir=install_dir)
        if vhost_data.get("use_certbot"):
            click.secho(
                "Certificate is not issued yet - run: "
                f"odoo router ssl{' --global' if is_global else ''}",
                fg="yellow",
            )


# ---------------------------------------------------------------------------
# guided config menu
# ---------------------------------------------------------------------------


def _vhost_label(vhost):
    label = f"{vhost['server_name']}  [{vhost.get('template', '?')}]"
    if vhost.get("upstream_server"):
        label += f"  -> {vhost['upstream_server']}:{vhost.get('upstream_port', '?')}"
    missing = _missing_required(vhost)
    if missing:
        label += f"  (incomplete: {', '.join(missing)})"
    return label


def _pick_vhost(vhosts, message):
    """Cursor-selectable list of vhosts. Returns the index or None."""
    choices = [(_vhost_label(v), i) for i, v in enumerate(vhosts)]
    choices.append(("<- back", None))
    answer = inquirer.prompt(
        [inquirer.List("idx", message=message, choices=choices)]
    )
    return answer["idx"] if answer else None


def _ask_field_value(vhost, field, ftype):
    """Ask for one field. Empty input removes an optional field.

    Returns True when something changed.
    """
    current = vhost.get(field)
    if ftype == "bool":
        answer = inquirer.prompt(
            [inquirer.Confirm("value", message=field, default=bool(current))]
        )
        if answer is None:
            return False
        if answer["value"]:
            vhost[field] = True
        else:
            vhost.pop(field, None)
        return True

    if ftype == "basic_auth":
        keep = inquirer.prompt(
            [
                inquirer.Confirm(
                    "want",
                    message="Protect with basic auth?",
                    default=bool(current),
                )
            ]
        )
        if keep is None:
            return False
        if not keep["want"]:
            vhost.pop("basic_auth", None)
            return True
        creds = inquirer.prompt(
            [
                inquirer.Text(
                    "user",
                    message="Basic auth user",
                    default=next(iter(current), "") if current else "",
                    validate=lambda _, x: _require(x),
                ),
                inquirer.Password(
                    "password",
                    message="Basic auth password",
                    validate=lambda _, x: _require(x),
                ),
            ]
        )
        if creds is None:
            return False
        vhost["basic_auth"] = {creds["user"]: creds["password"]}
        return True

    required = field in REQUIRED_FIELDS.get(
        vhost.get("template"), ["server_name"]
    )

    def _validate(_, value):
        value = value.strip()
        if not value:
            if required:
                _invalid("Required")
            return True
        if field in INT_FIELDS and not value.isdigit():
            _invalid("Must be a number")
        if field == "upstream_name" and not _UPSTREAM_NAME_RE.match(value):
            _invalid(
                "Only letters, digits and underscore - it becomes an nginx "
                "variable name"
            )
        return True

    answer = inquirer.prompt(
        [
            inquirer.Text(
                "value",
                message=field + ("" if required else " (empty = remove)"),
                default="" if current is None else str(current),
                validate=_validate,
            )
        ]
    )
    if answer is None:
        return False
    value = answer["value"].strip()
    if not value:
        vhost.pop(field, None)
    elif field in INT_FIELDS:
        vhost[field] = int(value)
    else:
        vhost[field] = value
    return True


def _edit_vhost(vhost):
    """Field-by-field editing. Returns True when something changed."""
    changed = False
    while True:
        required = REQUIRED_FIELDS.get(vhost.get("template"), ["server_name"])
        choices = []
        for field in required:
            value = vhost.get(field)
            shown = value if value not in (None, "") else "MISSING"
            choices.append((f"{field}: {shown}", (field, "text")))
        for field, ftype, hint in OPTIONAL_FIELDS:
            if field in vhost:
                value = "***" if field == "basic_auth" else vhost[field]
                choices.append((f"{field}: {value}", (field, ftype)))
            else:
                choices.append((f"+ {field}  ({hint})", (field, ftype)))
        choices.append(("<- back", None))
        answer = inquirer.prompt(
            [
                inquirer.List(
                    "field",
                    message=f"Edit {vhost['server_name']}",
                    choices=choices,
                )
            ]
        )
        if not answer or answer["field"] is None:
            return changed
        field, ftype = answer["field"]
        if _ask_field_value(vhost, field, ftype):
            changed = True


@router.command(
    name="config",
    help="Guided menu: create, edit and delete virtual hosts.",
)
@click.option("--global", "is_global", is_flag=True)
@click.option("--install-dir", default=None)
@pass_config
@click.pass_context
def config_menu(ctx, config, is_global, install_dir):
    if not is_interactive():
        abort("This is a menu - it needs an interactive terminal.")
    d = _install_dir_from_opts(config, is_global, install_dir)
    unapplied = False

    while True:
        vhosts = _load_vhosts(d)
        choices = [("Create a vhost", "new")]
        if vhosts:
            choices += [
                ("Edit a vhost", "edit"),
                ("Delete a vhost", "delete"),
                ("Show a vhost", "show"),
            ]
        choices.append(
            (
                "Render and reload nginx"
                + (" (there are unapplied changes)" if unapplied else ""),
                "apply",
            )
        )
        choices += [
            ("Issue certificates (certbot)", "ssl"),
            ("Quit", "quit"),
        ]
        answer = inquirer.prompt(
            [
                inquirer.List(
                    "action",
                    message=f"Router {d} - {len(vhosts)} vhost(s)",
                    choices=choices,
                )
            ]
        )
        action = answer["action"] if answer else "quit"

        if action == "quit":
            if unapplied:
                last = inquirer.prompt(
                    [
                        inquirer.Confirm(
                            "apply",
                            message="Apply the changes before leaving?",
                            default=True,
                        )
                    ]
                )
                if last and last["apply"]:
                    ctx.invoke(
                        apply_vhosts,
                        is_global=is_global,
                        install_dir=install_dir,
                    )
                else:
                    click.secho(
                        "Changes are in vhosts.yml but not live - run "
                        "'odoo router apply-vhosts' when you are ready.",
                        fg="yellow",
                    )
            return

        if action == "new":
            vhost_data = _collect_new_vhost(vhosts)
            _show_vhost(vhost_data)
            confirm = inquirer.prompt(
                [inquirer.Confirm("save", message="Keep it?", default=True)]
            )
            if confirm and confirm["save"]:
                vhosts = [
                    v
                    for v in vhosts
                    if v["server_name"] != vhost_data["server_name"]
                ]
                vhosts.append(vhost_data)
                _save_vhosts(d, vhosts)
                unapplied = True
                click.secho(f"Saved to {d / 'vhosts.yml'}.", fg="green")

        elif action == "edit":
            idx = _pick_vhost(vhosts, "Which vhost?")
            if idx is None:
                continue
            if _edit_vhost(vhosts[idx]):
                _save_vhosts(d, vhosts)
                unapplied = True
                click.secho("Saved.", fg="green")

        elif action == "delete":
            idx = _pick_vhost(vhosts, "Delete which vhost?")
            if idx is None:
                continue
            name = vhosts[idx]["server_name"]
            confirm = inquirer.prompt(
                [
                    inquirer.Confirm(
                        "yes", message=f"Really delete {name}?", default=False
                    )
                ]
            )
            if confirm and confirm["yes"]:
                del vhosts[idx]
                _save_vhosts(d, vhosts)
                unapplied = True
                click.secho(f"{name} removed.", fg="green")

        elif action == "show":
            idx = _pick_vhost(vhosts, "Show which vhost?")
            if idx is not None:
                click.echo(yaml.safe_dump(vhosts[idx], sort_keys=False))

        elif action == "apply":
            ctx.invoke(
                apply_vhosts, is_global=is_global, install_dir=install_dir
            )
            unapplied = False

        elif action == "ssl":
            ctx.invoke(ssl_, is_global=is_global, install_dir=install_dir)
