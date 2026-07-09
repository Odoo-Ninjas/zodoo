import json
import subprocess
import xml.etree.ElementTree as ET
import arrow
import time
from pathlib import Path

import click
from tabulate import tabulate

from .cli import Commands, cli, pass_config
from .lib_clickhelpers import AliasedGroup
from .tools import _execute_sql
from .tools import _get_setting
from .tools import odoorpc
from .tools import _is_in_container
from .tools import abort
from .tools import __assure_gitignore


def _stringify_translated_dict(v):
    if isinstance(v, dict):
        res = []
        for k, d in v.items():
            if k != "en_US":
                continue
            res.append(d)
            # res.append(f"{k}: {d}")
        return ", ".join(res)
    else:
        return v


@cli.group(cls=AliasedGroup)
@pass_config
def talk(config):
    pass


@talk.command()
@click.argument("name", required=False, nargs=-1)
@click.option("-M", "--module")
@click.option("-m", "--model")
@click.option("-r", "--resid")
@click.option("-d", "--delete", is_flag=True)
@pass_config
def xmlids(config, name, module, model, resid, delete):
    return _xmlids(config, name, module, model, resid, delete)


def _xmlids(config, name, module, model, resid, delete):
    conn = config.get_odoo_conn()
    where = " where 1 = 1"
    params = []
    if model:
        where += " AND model = %s"
        params.append(model)
    if module:
        where += " AND module = %s"
        params.append(module)
    if resid:
        resid_ints = list(map(lambda x: int(x.strip()), resid.split(",")))
        placeholders = ",".join(["%s"] * len(resid_ints))
        where += f" AND res_id in ({placeholders})"
        params.extend(resid_ints)
    for n in name or []:
        where += " and ( (model ilike %s or name ilike %s or module ilike %s))"
        pattern = f"%{n}%"
        params.extend([pattern, pattern, pattern])
    rows = _execute_sql(
        conn,
        sql=(
            "SELECT module||'.'|| name as xmlid, model, res_id, noupdate, id from ir_model_data "
            f"{where} "
            "order by module, name, model "
        ),
        params=tuple(params),
        fetchall=True,
        return_columns=True,
    )
    click.secho(tabulate(rows[1], rows[0], tablefmt="fancy_grid"), fg="yellow")
    if delete:
        for row in rows[1]:
            click.secho(f"Deleting {row[0]}...", fg="red")
            _execute_sql(
                conn,
                sql="DELETE FROM ir_model_data WHERE id = %s",
                params=(row[4],),
                fetchall=False,
                return_columns=False,
            )


@talk.command()
@click.argument("field", nargs=-1)
@pass_config
def deactivate_field_in_views(config, field):
    conn = config.get_odoo_conn()
    for field in field:
        click.secho(f"Turning {field} into create_date.", fg="green")
        _execute_sql(
            conn,
            sql=(
                "UPDATE ir_ui_view set arch_db = "
                f"replace(arch_db, '{field}', 'create_date')"
            ),
            fetchall=False,
            return_columns=False,
        )


@talk.command()
@click.argument("name", required=True)
@pass_config
@click.pass_context
def get_config_parameter(ctx, config, name):
    conn = config.get_odoo_conn()
    click.secho(_get_setting(conn, name))


RIBBON_MODULE = "web_environment_ribbon"


def _is_odoo_module(path):
    # Odoo >= 10 uses __manifest__.py, <= 9 uses __openerp__.py
    return (path / "__manifest__.py").exists() or (
        path / "__openerp__.py"
    ).exists()


def _fetch_oca_ribbon_module(branch, dest_root):
    """Sparse-clone the OCA/web ``web_environment_ribbon`` module of the given
    branch into ``dest_root/web_environment_ribbon`` (without the .git)."""
    import shutil
    import tempfile

    url = "https://github.com/OCA/web"
    dest_root.mkdir(parents=True, exist_ok=True)
    click.secho(
        f"Fetching {RIBBON_MODULE} from OCA/web@{branch}...", fg="blue"
    )
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        try:
            subprocess.check_call(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--filter=blob:none",
                    "--sparse",
                    "-b",
                    branch,
                    url,
                    str(tmp),
                ]
            )
            subprocess.check_call(
                [
                    "git",
                    "-C",
                    str(tmp),
                    "sparse-checkout",
                    "set",
                    RIBBON_MODULE,
                ]
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            abort(
                f"Could not fetch {RIBBON_MODULE} from {url} (branch {branch}). "
                "Check that git is installed, network access works and the "
                "branch exists."
            )
        src = tmp / RIBBON_MODULE
        if not _is_odoo_module(src):
            abort(f"OCA/web@{branch} does not contain {RIBBON_MODULE}.")
        target = dest_root / RIBBON_MODULE
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target, ignore=shutil.ignore_patterns(".git"))
    click.secho(f"Provided {RIBBON_MODULE} at {target}", fg="green")


def _ensure_ribbon_module(config):
    """Make sure the OCA ``web_environment_ribbon`` module is available: fetch a
    version-matched copy into ``<customs>/addons_zodoo_provided`` and register
    that path in the project MANIFEST (idempotent)."""
    from .odoo_config import MANIFEST, current_version, customs_dir

    rel_path = "addons_zodoo_provided"
    customs = customs_dir()
    provided_root = customs / rel_path
    module_dir = provided_root / RIBBON_MODULE

    if not _is_odoo_module(module_dir):
        branch = f"{current_version():.1f}"
        _fetch_oca_ribbon_module(branch, provided_root)

    # keep the vendored copy out of the project's git history
    __assure_gitignore(customs / ".gitignore", "/" + rel_path + "/")

    manifest = MANIFEST()
    paths = list(manifest["addons_paths"])
    if rel_path not in paths:
        paths.append(rel_path)
        manifest["addons_paths"] = paths
        click.secho(
            f"Added '{rel_path}' to MANIFEST addons_paths.", fg="green"
        )


def _ribbon_installed(config):
    res = _execute_sql(
        config.get_odoo_conn(),
        "SELECT state FROM ir_module_module WHERE name = %s;",
        params=(RIBBON_MODULE,),
        fetchone=True,
    )
    return bool(res and res[0] == "installed")


def _install_ribbon_module(ctx):
    Commands.invoke(
        ctx, "update", module=[RIBBON_MODULE], no_dangling_check=True
    )


def _set_ribbon(ctx, config, name, quick):
    if not quick and not _ribbon_installed(config):
        # First try to install from addons paths that are already available
        # (module provided via gimera, or an ADDITIONAL_ADDONS_PATHS vendored
        # copy as odoo-cicd does) so we do not hit the network needlessly.
        try:
            _install_ribbon_module(ctx)
        except (Exception, SystemExit):
            # includes abort() -> SystemExit ("Missing after installation");
            # this attempt is best-effort, the re-check below drives the fetch
            pass
        # Still not installed -> the module is nowhere in the addons paths;
        # fetch a version-matched OCA copy, wire it into the MANIFEST and retry.
        if not _ribbon_installed(config):
            _ensure_ribbon_module(config)
            _install_ribbon_module(ctx)

    # upsert so the ribbon text is set even if the parameter row does not
    # exist yet (e.g. -Q/--quick without a prior install)
    _execute_sql(
        config.get_odoo_conn(),
        """
        INSERT INTO ir_config_parameter (key, value)
        VALUES ('ribbon.name', %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
    """,
        params=(name,),
    )
    click.secho(f"Ribbon set to: {name}", fg="green")


@talk.command(name="set-ribbon")
@click.argument("name", required=True)
@click.option("-Q", "--quick", is_flag=True)
@pass_config
@click.pass_context
def set_ribbon(ctx, config, name, quick):
    _set_ribbon(ctx, config, name, quick)


@cli.command(
    name="set-ribbon",
    help=(
        "Show a ribbon (e.g. 'Neutralized') in the web client. Fetches the OCA "
        "web_environment_ribbon module, wires it into the MANIFEST addons_paths "
        "and installs it if missing (-Q/--quick to only set the text)."
    ),
)
@click.argument("name", required=True)
@click.option("-Q", "--quick", is_flag=True)
@pass_config
@click.pass_context
def set_ribbon_toplevel(ctx, config, name, quick):
    _set_ribbon(ctx, config, name, quick)


@talk.command(
    help=(
        "As the name says: if db was transferred, web-icons are restored"
        " on missing assets"
    )
)
@pass_config
@click.pass_context
def restore_web_icons(ctx, config):
    if config.use_docker:
        from .lib_control_with_docker import shell as lib_shell

    click.secho("Restoring web icons...", fg="blue")
    lib_shell(
        config,
        (
            "for x in self.env['ir.ui.menu'].search([]):\n"
            "   if not x.web_icon: continue\n"
            "   x.web_icon_data = x._compute_web_icon_data(x.web_icon)\n"
            "   env.cr.commit()\n"
        ),
    )
    click.secho("Restored web icons.", fg="green")


@talk.command(
    help=(
        "If menu items are missing, then recomputing the parent store"
        "can help"
    )
)
@pass_config
@click.pass_context
def recompute_parent_store(ctx, config):
    if config.use_docker:
        from .lib_control_with_docker import shell as lib_shell

    click.secho("Recomputing parent store...", fg="blue")
    lib_shell(
        config,
        (
            "for model in self.env['ir.model'].search([]):\n"
            "   try:\n"
            "       obj = self.env[model.model]\n"
            "   except KeyError: pass\n"
            "   else:\n"
            "       obj._parent_store_compute()\n"
            "       env.cr.commit()\n"
        ),
    )
    click.secho("Recompute parent store done.", fg="green")


@talk.command()
@click.option(
    "-n", "--last", default=10, help="Show last N connection samples."
)
@pass_config
def diagnose(config, last):
    """
    Show runtime diagnose values.

    Currently delegates to the db connection sampler in the cronjobs
    container. As more diagnose sources are added (memory, queue depths,
    etc.), this command will aggregate them.
    """
    import subprocess
    import sys

    from .tools import ensure_project_name

    ensure_project_name(config)
    container = f"{config.project_name}_cronjobs"

    click.secho("=== DB connection samples ===", fg="cyan", bold=True)
    rc = subprocess.call(
        [
            "docker",
            "exec",
            container,
            "python3",
            "/usr/local/bin/diag_maxconn_sampler.py",
            "show",
            "-n",
            str(last),
        ]
    )
    if rc:
        sys.exit(rc)


@talk.command()
@pass_config
def progress(config):
    """
    Displays installation progress
    """
    for row in _execute_sql(
        config.get_odoo_conn(),
        "select state, count(*) from ir_module_module group by state;",
        fetchall=True,
    ):
        click.echo(f"{row[0]}: {row[1]}")


@talk.command()
@pass_config
def modules_overview(config):
    from .lib_src import _modules_overview

    res = _modules_overview(config)
    print("===")
    print(json.dumps(res, indent=4))


def _get_xml_id(conn, model, res_id):
    xmlid = _execute_sql(
        conn,
        sql=f"SELECT module||'.'||name FROM ir_model_data WHERE model = '{model}' AND res_id = {res_id}",
        params=(model, res_id),
        fetchone=True,
    )
    return xmlid and xmlid[0] or ""


@talk.command()
@click.argument("name", required=False, default="%")
@pass_config
def menus(config, name):
    conn = config.get_odoo_conn()
    pattern = f"%{name}%"
    ids = map(
        lambda x: x[0],
        _execute_sql(
            conn,
            sql=(
                "SELECT id FROM ir_ui_menu WHERE name::text ILIKE %s "
                " UNION "
                "SELECT res_id FROM ir_model_data WHERE model = 'ir.ui.menu' AND (name::text ILIKE %s OR module ILIKE %s )"
            ),
            params=(pattern, pattern, pattern),
            fetchall=True,
            return_columns=False,
        ),
    )

    def get_parents(parent_id):
        rows = _execute_sql(
            conn,
            sql=(
                "SELECT id, name, parent_id FROM ir_ui_menu "
                f"WHERE id = {parent_id}"
            ),
            fetchall=True,
            return_columns=False,
        )
        for row in rows:
            yield row
            if row[2]:
                yield from get_parents(row[2])

    ids = ",".join(map(str, [0] + list(ids)))
    rows = _execute_sql(
        conn,
        sql=(
            f"SELECT id, name, parent_id FROM ir_ui_menu WHERE id in ({ids})"
        ),
        fetchall=True,
        return_columns=True,
    )
    tablerows = []
    for row in rows[1]:
        xml_id = _get_xml_id(conn, "ir.ui.menu", row[0])
        row = list(row)
        path = "/".join(
            map(
                lambda x: _stringify_translated_dict(x[1]),
                reversed(list(get_parents(row[0]))),
            )
        )
        row.insert(0, xml_id)
        row.insert(0, path)
        row = row[:2]
        tablerows.append(row)
    cols = list(rows[0])[:2]
    cols.insert(0, "xmlid")
    cols.insert(0, "path")
    tablerows = list(sorted(tablerows, key=lambda x: x[0]))
    click.secho(tabulate(tablerows, cols, tablefmt="fancy_grid"), fg="yellow")


@talk.command()
@click.argument("name", required=False, default="%")
@pass_config
def groups(config, name):
    conn = config.get_odoo_conn()
    pattern = f"%{name}%"
    ids = map(
        lambda x: x[0],
        _execute_sql(
            conn,
            sql=(
                "SELECT id FROM res_groups WHERE name::text ILIKE %s "
                " UNION "
                "SELECT res_id FROM ir_model_data WHERE model = 'res.groups' AND name::text ILIKE %s"
            ),
            params=(pattern, pattern),
            fetchall=True,
            return_columns=False,
        ),
    )

    ids = ",".join(map(str, [0] + list(ids)))
    rows = _execute_sql(
        conn,
        sql=(
            f"SELECT id, name FROM res_groups WHERE id in ({ids}) ORDER BY name"
        ),
        fetchall=True,
        return_columns=True,
    )
    tablerows = []
    for row in rows[1]:
        xml_id = _get_xml_id(conn, "res.groups", row[0])
        row = list(row)
        row.insert(0, xml_id)
        row.pop(1)
        tablerows.append(row)
    cols = ["XML-ID", "Name"]
    click.secho(
        tabulate(
            sorted(tablerows, key=lambda x: x[0]), cols, tablefmt="fancy_grid"
        ),
        fg="yellow",
    )


@talk.command()
@click.argument("login", required=False, default="%")
@pass_config
def users(config, login):
    conn = config.get_odoo_conn()
    pattern = f"%{login}%"
    rows = _execute_sql(
        conn,
        sql=(
            "SELECT res_users.id as user_id, login, name FROM res_users INNER JOIN "
            "res_partner p on p.id = res_users.partner_id "
            "WHERE p.name ILIKE %s or login ILIKE %s"
        ),
        params=(pattern, pattern),
        fetchall=True,
        return_columns=False,
    )

    cols = ["login", "name", "user_id"]
    click.secho(
        tabulate(rows, cols, tablefmt="fancy_grid"),
        fg="yellow",
    )


@talk.command()
@click.argument("model", required=False, default="%")
@click.argument("field", required=False, default="%")
@click.option("-r", "--relation", required=False)
@pass_config
def fields(config, model, field, relation):
    conn = config.get_odoo_conn()
    sql = (
        "SELECT f.model, f.name, f.ttype, f.relation "
        "FROM ir_model_fields f INNER JOIN "
        "ir_model m ON "
        "f.model_id = m.id "
        "WHERE 1=1 "
    )
    params = []
    if model:
        sql += " AND m.model ilike %s "
        params.append(f"%{model}%")
    if field:
        sql += " AND f.name ilike %s "
        params.append(f"%{field}%")
    if relation:
        sql += " AND f.relation = %s "
        params.append(relation)

    sql += "ORDER BY 2, 1 "

    rows = _execute_sql(
        conn,
        sql=sql,
        params=tuple(params),
        fetchall=True,
        return_columns=False,
    )

    cols = ["model", "field-name", "ttype", "relation"]
    click.secho(
        tabulate(rows, cols, tablefmt="fancy_grid"),
        fg="yellow",
    )


@talk.command()
@click.argument("model", required=False, default="%")
@pass_config
def models(config, model):
    conn = config.get_odoo_conn()
    sql = "SELECT name, model " "FROM ir_model " "WHERE 1=1 "
    if model:
        sql += f" AND model ilike '%{model}%' "

    rows = _execute_sql(
        conn,
        sql=sql,
        fetchall=True,
        return_columns=False,
    )

    cols = ["model", "name"]
    click.secho(
        tabulate(rows, cols, tablefmt="fancy_grid"),
        fg="yellow",
    )


@talk.command()
@click.option("-i", "--interval", default=5, type=int)
@pass_config
def queuejobs(config, interval):
    conn = config.get_odoo_conn()
    last_data, last_time = None, None
    averages = {}
    while True:
        rows = _execute_sql(
            conn,
            sql=(
                "SELECT count(*) as count, state "
                "FROM queue_job "
                "GROUP BY state "
                "UNION "
                "SELECT count(*), 'total' FROM queue_job"
            ),
            fetchall=True,
            return_columns=True,
        )
        rows = list(rows)
        rows[1] = sorted(
            rows[1], key=lambda x: x[1] == "total" and "zzzzzzzz" or x[1]
        )
        data = {x[1]: x[0] for x in rows[1]}

        click.secho(
            tabulate(rows[1], rows[0], tablefmt="fancy_grid"), fg="yellow"
        )
        if last_data:
            click.secho("Changes: ")
            now = arrow.get()
            avg_rows = []
            for state, v in data.items():
                diff = data.get(state, 0) - last_data.get(state, 0)
                seconds = round((now - last_time).total_seconds())
                if seconds:
                    diff_per_second = round(abs(diff / seconds), 1)
                else:
                    diff_per_second = 0
                averages.setdefault(state, [])
                averages[state].append(diff_per_second)
                avg_diff_per_second = round(
                    sum(averages[state]) / len(averages[state]), 1
                )
                avg_rows.append([state, diff, avg_diff_per_second])
            click.secho(
                tabulate(
                    avg_rows,
                    ["state", "items", "items per second"],
                    tablefmt="fancy_grid",
                ),
                fg="blue",
            )
            # click.secho(f"{state}: {diff} with {avg_diff_per_second}/s")

        time.sleep(interval)
        last_data = data
        last_time = arrow.get()


def _get_xmlid(conn, id, model):
    where = f"model = 'ir.ui.view' and res_id={id}"
    sql = (
        "SELECT module||'.'|| name as xmlid, model, res_id from ir_model_data "
        f"where {where} "
    )
    rows = _execute_sql(
        conn,
        sql=sql,
        fetchall=True,
        return_columns=False,
    )
    if rows:
        return rows[0][0]
    return None


@talk.command()
@click.argument("name", required=False)
@click.option("-M", "--module")
@click.option("-a", "--arch", required=False)
@click.option("-m", "--model", required=False)
@click.option("-t", "--type", required=False)
@click.option("-x", "--xmlid", required=False)
@click.option("-S", "--show", is_flag=True)
@click.option("--mode", help="Mode")
@pass_config
def views(config, name, arch, model, type, xmlid, show, module, mode):
    odoo = odoorpc(config)
    domain = []
    if module:
        # from .module_tools import Module
        # module = Module.get_by_name(module, nocache=False)
        domain += [("arch_fs", "=ilike", f"{str(module)}/%")]
    if name:
        domain += [("name", "ilike", name)]
    if arch:
        domain += [("arch_prev", "ilike", arch)]
    if type:
        domain += [("type", "ilike", type)]
    if model:
        domain += [("model", "=", model)]
    if mode:
        domain += [("mode", "=", mode)]
    if xmlid:
        id = odoo.env.ref(xmlid).id
        domain += [("id", "=", id)]
    click.secho(f"Searching with domain: {domain}", fg="blue")
    views = odoo.env["ir.ui.view"].search(domain)
    rows = []
    for view in views:
        v = odoo.env["ir.ui.view"].browse(view)
        id = v.get_external_id()
        if id:
            for id, xmlid in id.items():
                break
        else:
            ix, xmlid = "", ""
        rows.append(
            (
                id,
                v.type,
                v.model,
                xmlid,
                v.mode,
                v.inherit_id.id or "",
                v.arch_fs,
            )
        )
    rows = sorted(rows, key=lambda x: (str(x[1]), str(x[3])))
    click.secho(
        tabulate(
            rows,
            ("id", "type", "model", "xmlid", "mode", "inherits", "filepath"),
            tablefmt="fancy_grid",
        ),
        fg="yellow",
    )

    if show:
        for view in views:
            v = odoo.env["ir.ui.view"].browse(view)
            click.secho(f"{v.get_external_id()} {v.arch_fs}", fg="green")
            pretty_xml = ET.fromstring(v.arch_db)
            ET.indent(pretty_xml, space="    ")
            click.secho(
                ET.tostring(pretty_xml, encoding="unicode"), fg="yellow"
            )


@talk.command()
@pass_config
@click.pass_context
def set_remote_keys(ctx, config):
    Commands.invoke(
        ctx,
        "odoo-shell",
        command=[
            'env["res.users"].set_remote_keys();',
            "env.cr.commit()",
        ],
    )


@talk.command()
@click.argument("job_command", required=True)
def queue_job_func_to_shell(job_command):
    """
    Converts:
    wdb.backend(4,)._import(model_name='cdp.task', item=84263602, importer_usage='record.importer')

    into:
    env['wdb.backend'].browse(4)._import(model_name='cdp.task', item=84263602, importer_usage='record.importer')
    """

    model, func = job_command.split(").")
    model, id = model.split("(")
    click.secho(f"env['{model}'].browse({id}).{func}", fg="green")


@talk.command(
    help="Finds the server or window action name behind an action ID"
)
@click.argument("action_id", required=True)
@pass_config
def resolve_action_id(config, action_id):
    odoo = odoorpc(config)
    action = odoo.env["ir.actions.actions"].browse(int(action_id))
    type = action.type
    action = odoo.env[type].browse(action.id)
    click.secho(action.get_external_id(), fg="green")


@talk.command()
@pass_config
def rpc(config):
    from IPython.terminal.prompts import Prompts, Token
    from IPython.terminal.embed import InteractiveShellEmbed
    from IPython.terminal.prompts import Prompts, Token
    from rich.console import Console

    # ----- pretty/colored output (rich) -----
    try:
        from rich import print as rprint
        from rich.pretty import pprint as rpprint

        USE_RICH = True
    except Exception:
        USE_RICH = False

    class OdooPrompts(Prompts):
        def in_prompt_tokens(self, cli=None):
            return [
                (
                    Token.Prompt,
                    f"[{config.DBNAME}] [{self.shell.execution_count}]: ",
                )
            ]

    odoo = odoorpc(config)
    local_vars = {"odoo": odoo, "env": odoo.env}

    # Build a banner
    info_line = (
        f"Connected to Odoo [{config.DBNAME}] @ PORT: {config.PROXY_PORT}"
    )
    tips = (
        "Examples:\n"
        "  Partner = env['res.partner']\n"
        "  Partner.search_read([], ['name'], limit=5)"
    )
    console = Console(force_terminal=True, soft_wrap=True)
    rprint = console.print  # <-- define rprint
    rprint(f"[bold green]{info_line}[/bold green]")
    rprint(
        "[cyan]Variables:[/cyan] [bold]odoo[/bold]  |  [cyan]Helpers:[/cyan] print (rich), pprint (rich.pretty)"
    )
    rprint(tips)

    # Create and configure shell
    ipshell = InteractiveShellEmbed(banner1="")
    ipshell.colors = (
        "Linux"  # nice default; try 'Neutral' or 'LightBG' if you prefer
    )
    try:
        # True color & verbose tracebacks
        ipshell.run_line_magic(
            "config", "TerminalInteractiveShell.true_color = True"
        )
        ipshell.run_line_magic("xmode", "Verbose")
    except Exception:
        pass

    # Attach prompt & helpers
    ipshell.prompts = OdooPrompts(ipshell)
    local_ns = {"odoo": odoo, "env": odoo.env}
    if USE_RICH:
        local_ns.update({"print": rprint, "pprint": rpprint})
    # Drop into the shell
    ipshell(local_ns=local_ns, global_ns={})

    # After exit, print a friendly message
    print("Bye! 👋")


@talk.command()
def is_in_container():
    print("docker container" if _is_in_container() else "no container")


Commands.register(progress)
