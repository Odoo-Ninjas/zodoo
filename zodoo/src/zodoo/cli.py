import os
import sys
import click
import subprocess
from pathlib import Path

try:
    from .lib_clickhelpers import AliasedGroup
except ImportError:
    click = None
from .click_config import Config
from .click_global_commands import GlobalCommands

Commands = GlobalCommands()
pass_config = click.make_pass_decorator(Config, ensure=True)


@click.group(cls=AliasedGroup)
@click.option("-f", "--force", is_flag=True)
@click.option("-v", "--verbose", is_flag=True)
@click.option(
    "-xs",
    "--restrict-setting",
    multiple=True,
    help="Several parameters; limit to special configuration files settings and docker-compose files. All other configuration files will be ignored.",
)
@click.option(
    "-xd",
    "--restrict-docker-compose",
    multiple=True,
    help="Several parameters; limit to special configuration files settings and docker-compose files. All other configuration files will be ignored.",
)
@click.option("-p", "--project-name", help="Set Project-Name")
@click.option("--chdir", help="Set Working Directory")
@pass_config
def cli(
    config,
    force,
    verbose,
    project_name,
    restrict_setting,
    restrict_docker_compose,
    chdir,
):
    config.force = force
    config.verbose = verbose
    if chdir:
        chdir = Path(chdir).absolute()
        os.chdir(chdir)
        config.WORKING_DIR = chdir

    from .tools import _get_default_project_name
    from .tools import _project_name_from_settings
    from .tools import _get_customs_root
    from .tools import _is_in_container
    from .tools import abort

    explicit_project_name = bool(project_name)
    if not project_name:
        try:
            project_name = _get_default_project_name(restrict_setting)
        except Exception:
            project_name = ""

    # A PROJECT_NAME pinned in a settings file is a deliberate choice to
    # decouple the project-name from the source directory name (e.g. dir
    # 'ipe' but PROJECT_NAME='odoo_prod'). Treat it like an explicit -p
    # override and skip the directory-name sanity check below.
    try:
        project_name_from_settings = bool(
            _project_name_from_settings(restrict_setting)
        )
    except Exception:
        project_name_from_settings = False

    # Sanity: if we're inside a project tree (cwd has a MANIFEST root),
    # its directory name must equal the effective project_name. The
    # rendered compose file, container labels and ~/.odoo/run/<project>/
    # all key off project_name; a mismatch means commands like `up` look
    # for the compose under ~/.odoo/run/<project_name>/ while sources
    # live in <cwd>, which silently breaks lookups in subtle ways. Skip
    # when:
    #   - we're inside a container (project_name comes from env)
    #   - the caller used -xs to intentionally point at custom settings
    #     (advanced wrapper mode — e.g. project-specific control planes
    #     that bind a fixed project_name to a differently-named source
    #     tree)
    #   - the caller passed -p explicitly (the user knows the source
    #     tree's name differs from the project_name — typical for CI
    #     workflows that use a hashed project_name on a checkout dir)
    #   - PROJECT_NAME is pinned in a settings file (a deliberate decoupling
    #     of project-name from the source directory name)
    skip_dir_check = (
        _is_in_container()
        or bool(restrict_setting)
        or explicit_project_name
        or project_name_from_settings
    )
    if project_name and not skip_dir_check:
        try:
            cwd_root = _get_customs_root(Path(os.getcwd()))
        except Exception:
            cwd_root = None
        if cwd_root and cwd_root.name != project_name:
            from .tools import _sanitize_project_name

            dir_sanitized = _sanitize_project_name(
                "".join(
                    c if c not in " ?:/*\\!@#$%^&*()." else "_"
                    for c in cwd_root.name
                )
            )
            if dir_sanitized == project_name:
                pass  # name was auto-shortened from this directory — ok
            else:
                abort(
                    f"Directory name '{cwd_root.name}' (at {cwd_root}) does "
                    f"not match project-name '{project_name}'. Either "
                    f"rename the directory to '{project_name}', or change "
                    "--project-name / ~/.odoo/settings PROJECT_NAME to "
                    "match. (Compose state lives in "
                    f"~/.odoo/run/{project_name}/ but the source tree is "
                    f"at {cwd_root}; a mismatch causes 'no such file' "
                    "lookups inside `odoo up` and friends.)"
                )

    config.set_restrict("settings", restrict_setting)
    config.set_restrict("docker-compose", restrict_docker_compose)
    config.project_name = project_name


@cli.command()
@click.option(
    "-x",
    "--execute",
    is_flag=True,
    help=("Execute the script to insert completion into users rc-file."),
)
def completion(execute):
    shell = os.environ["SHELL"].split("/")[-1]
    rc_file = Path(os.path.expanduser(f"~/.{shell}rc"))
    line = f'eval "$(_ODOO_COMPLETE={shell}_source odoo)"'
    if execute:
        content = rc_file.read_text().splitlines()
        if not list(
            filter(
                lambda x: line in x and not x.strip().startswith("#"),
                content,
            )
        ):
            content += [f"\n{line}\n"]
            click.secho(
                f"Inserted successfully\n{line}"
                "\n\nPlease restart you shell."
            )
            rc_file.write_text("\n".join(content))
        else:
            click.secho("Nothing done - already existed.")
    else:
        click.secho(
            "\n\n"
            f"Insert into {rc_file}\n\n"
            f"echo '{line}' >> {rc_file}"
            "\n\n"
        )
    sys.exit(0)


@cli.command()
@pass_config
def version(config):
    from .tools import _get_version

    version = _get_version()

    images_sha = subprocess.check_output(
        ["git", "log", "-n1", "--format=%H"],
        encoding="utf8",
        cwd=config.dirs["images"],
    ).strip()
    images_branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        encoding="utf8",
        cwd=config.dirs["images"],
    ).strip()
    click.secho(
        (
            f"Zodoo Version:    {version}\n"
            f"Images SHA:       {images_sha}\n"
            f"Images Branch:    {images_branch}\n"
        ),
        fg="yellow",
    )
