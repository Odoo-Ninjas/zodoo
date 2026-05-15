import traceback
import arrow
import re
import click
from .tools import _execute_sql
from .tools import table_exists
from .cli import cli, pass_config, Commands
from .lib_clickhelpers import AliasedGroup
from .tools import __hash_odoo_password
from .tools import __replace_all_envs_in_str
from .tools import _update_setting
from .tools import abort
from datetime import datetime


@cli.group(cls=AliasedGroup, name="dev-env")
@pass_config
def turn_into_dev(config):
    pass


@turn_into_dev.command()
@click.argument("password", required=False)
@click.option("-d", "--default", help="Set the default password", is_flag=True)
@click.pass_context
@pass_config
def set_password_all_users(config, ctx, password, default):
    from .odoo_config import current_version

    if default:
        password = config.DEFAULT_DEV_PASSWORD
    else:
        if not password:
            abort("Passwort required!")
    pwd = __hash_odoo_password(password)
    conn = config.get_odoo_conn().clone()
    check_sql = "select 1 from information_schema.tables where table_name = 'res_users' limit 1"
    if not _execute_sql(conn, check_sql, fetchall=True):
        click.secho("Skipping set_password_all_users: res_users table does not exist yet (database not initialized).", fg="yellow")
        return
    sql = "select login, password from res_users order by login"
    users = _execute_sql(conn, sql, fetchall=True)
    l = len(users)
    for i, user in enumerate(users, 1):
        click.secho(f"{i}/{l} Setting password for user {user[0]}", fg="green")
        # if not __verify_password(password, user[1]):  # WHY USED?
        sql = "update res_users set password=%s where login=%s"
        _execute_sql(conn, sql, params=(pwd, user[0]))
    if current_version() in [11.0]:
        sql = f"update res_users set password_crypt=password"
        _execute_sql(conn, sql)

    # update a possible robot file also
    Commands.invoke(ctx, "robot:make-var-file", userpassword=password)


@turn_into_dev.command()
@click.argument("username", required=True)
@click.argument("password", required=True)
@click.pass_context
@pass_config
def user_password(config, ctx, username, password):
    pwd = __hash_odoo_password(password)
    conn = config.get_odoo_conn().clone()
    _execute_sql(
        conn,
        "update res_users set password=%s where login=%s",
        params=(pwd, username),
    )
    click.secho(f"Password set to {pwd} for user {username}", fg="green")


@turn_into_dev.command()
@click.argument("password")
@pass_config
def hash_password(config, password):
    click.secho(__hash_odoo_password(password))


@turn_into_dev.command(name="turn-into-dev")
@pass_config
@click.pass_context
def turn_into_dev_(ctx, config):
    if not config.devmode and not config.force:
        raise Exception(
            "When applying this sql scripts, "
            "the database is not usable anymore "
            "for production environments.\n"
            "Please set DEVMODE=1 to allow this"
        )
    __turn_into_devdb(ctx, config, config.get_odoo_conn())


def __collect_other_turndb2dev_sql():
    from .odoo_config import MANIFEST
    from .odoo_config import customs_dir

    cdir = customs_dir()
    dir = cdir / "devscripts"
    sqls = []

    manifest = MANIFEST()
    for file in manifest.get("neutralize", []):
        if not file.endswith(".sql"):
            raise NotImplementedError(file.name)
        sqls.append({"file": cdir / file, "mode": "plain"})

    if dir.exists():
        for file in dir.glob("turn-into-dev.sql"):
            sqls.append({"file": file, "mode": "plain"})
    return sqls


def __turn_into_devdb(ctx, config, conn):
    from .odoo_config import current_version
    from .myconfigparser import MyConfigParser

    started = datetime.now()

    sql_file = (
        config.dirs["images"]
        / "odoo"
        / "config"
        / str(int(current_version()))
        / "turndb2dev.sql"
    )
    sqls = [{"file": sql_file, "mode": "linebyline"}]

    sqls += __collect_other_turndb2dev_sql()

    for sqlfile in sqls:
        sql = sqlfile["file"].read_text()
        mode = sqlfile["mode"]
        if mode not in ["linebyline", "plain"]:
            raise NotImplementedError(mode)
        myconfig = MyConfigParser(config.files["settings"])
        env = dict(map(lambda k: (k, myconfig.get(k)), myconfig.keys()))

        if mode == "plain":
            click.secho(f"executing {sqlfile['file']}", fg="green")
            _execute_sql(conn, sql)

        elif mode == "linebyline":
            __execute_linebyline_sql(conn, sql, env)
        else:
            raise NotImplementedError(mode)

    _update_setting(
        conn=conn,
        key="web.base.url",
        value=f"http://localhost:{config.proxy_port}",
    )
    _update_setting(
        conn=conn,
        key="report.url",
        value=f"http://localhost:8069",
    )
    seconds = (datetime.now() - started).total_seconds()
    click.secho(
        f"Successfully applied neutralization scripts in {seconds} seconds"
    )


def __execute_linebyline_sql(conn, sql, env):
    sql = __replace_all_envs_in_str(sql, env)
    critical = False
    for line in sql.split("\n"):
        if not line:
            continue
        if line.startswith("--set critical"):
            critical = True
            continue
        elif line.startswith("--set not-critical"):
            critical = False
            continue

        comment = re.findall(r"\/\*[^\*^\/]*\*\/", line)
        if comment:

            def ignore_line(comment):
                comment = comment[2:-2]
                if "if-table-exists" in comment:
                    table = comment.split("if-table-exists")[1].strip()
                    res = _execute_sql(
                        conn,
                        "select count(*) from information_schema.tables where table_schema='public' and table_name='{}'".format(
                            table
                        ),
                        fetchone=True,
                    )
                    return not res[0]
                if "if-column-exists" in comment:
                    parts = (
                        comment.split("if-column-exists")[1].strip().split(".")
                    )
                    if len(parts) != 2:
                        abort(f"Malformed sql: {comment}")
                    table, column = parts
                    res = _execute_sql(
                        conn,
                        (
                            f"select count(*) "
                            f"from information_schema.columns "
                            f"where table_schema='public' and "
                            f"table_name='{table}' and column_name='{column}'"
                        ),
                        fetchone=True,
                    )
                    return not res[0]
                return False

            if any(
                list(ignore_line(comment) for comment in comment[0].split(";"))
            ):
                continue
        try:
            click.secho(line, fg="green")
            _execute_sql(conn, line)
        except Exception:
            if critical:
                raise
            msg = traceback.format_exc()
            print("failed un-critical sql:", msg)


@turn_into_dev.command()
@pass_config
def prolong(config):
    conn = config.get_odoo_conn()
    date = arrow.get().shift(months=6).strftime("%Y-%m-%d %H:%M:%S")
    _execute_sql(
        conn,
        (
            "UPDATE \n"
            "   ir_config_parameter "
            "SET "
            f"value = '{date}' "
            "WHERE "
            "key = 'database.expiration_date'"
        ),
    )


@turn_into_dev.command()
@click.option("--settings", required=True)
@pass_config
def remove_settings(config, settings):
    conn = config.get_odoo_conn()
    if not table_exists(conn, "ir_config_parameter"):
        click.secho(
            "ir_config_parameter does not exist yet - skipping remove-settings.",
            fg="yellow",
        )
        return
    for setting in settings.split(","):
        _execute_sql(
            conn,
            "DELETE FROM ir_config_parameter WHERE key=%s",
            params=(setting,),
        )


@turn_into_dev.command()
@click.argument("key", required=True)
@click.argument("value", required=True)
@pass_config
def update_setting(config, key, value):
    conn = config.get_odoo_conn()
    if not table_exists(conn, "ir_config_parameter"):
        click.secho(
            f"ir_config_parameter does not exist yet - skipping update-setting "
            f"{key}={value}.",
            fg="yellow",
        )
        return
    _update_setting(conn, key, value)


Commands.register(set_password_all_users, "set-password-all-users")
