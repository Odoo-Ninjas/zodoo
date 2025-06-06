#!/usr/bin/env wodoo_python
from collections import defaultdict
import click
import os
import sys
from pathlib import Path
from time import sleep
from wodoo import odoo_config
from wodoo.module_tools import delete_qweb as do_delete_qweb
from wodoo.module_tools import DBModules
from wodoo.odoo_config import MANIFEST
from wodoo.odoo_config import current_version
from tools import prepare_run
from tools import exec_odoo
from tools import _run_shell_cmd

YELLOW = "yellow"
MAGENTA = "magenta"
RED = "red"
GREEN = "green"

line = 80 * "-"
LINE = 80 * "="

mode_text = {
    "i": "installing",
    "u": "updating",
}


class Config(object):  # NOQA
    pass


pass_config = click.make_pass_decorator(Config, ensure=True)


def update_translations(modules):
    """
    This version is superior to '--i18n-import' of odoo, because
    server wide modules are really loaded.
    """

    def _get_lang_update_line(module):
        ref = f"env.ref('base.module_{module}')"
        if current_version() <= 13.0:
            cmd = f"{ref}.with_context(overwrite=True)._update_translations()\n"
        else:
            cmd = f"{ref}._update_translations(overwrite=True)\n"
        return cmd

    code = ""
    for module in modules:
        code += _get_lang_update_line(module)
    code += "env.cr.commit()\n"
    rc = _run_shell_cmd(code)
    if rc:
        click.secho(
            f"Error at updating translations for the modules - details are in the log.",
            fg=RED,
        )


def update(config, mode, modules):
    assert mode in ["i", "u"]
    assert isinstance(modules, list)
    if not modules:
        return

    # if ','.join(modules) == 'all': # needed for migration
    #    raise Exception("update 'all' not allowed")
    if config.run_test and not config.test_tags:
        TESTS = "--test-enable"
    else:
        TESTS = ""

    if not config.only_i18n:
        print(mode, modules)

        if mode == "i":
            modules = [x for x in modules if not DBModules.is_module_installed(x)]
            if not modules:
                return

        params = [
            "-" + mode,
            ",".join(modules),
            "--stop-after-init",
        ]
        if TESTS:
            params += [TESTS]
        if config.test_tags:
            params += ["--test-tags=" + config.test_tags]

        if config.log:
            params += [f"--log-level={config.log}"]
            params += [f"--log-handler=:{config.log.upper()}"]

        rc = exec_odoo(config.config_file, *params)
        if rc:
            click.secho(
                (f"Error at {mode_text[mode]} of: " f"{','.join(modules)}"),
                fg="red",
                bold=True,
            )

        for module in modules:
            if module != "all":
                if not DBModules.is_module_installed(module):
                    if mode == "i":
                        click.secho(
                            (
                                f"{module} is not installed - but it was tried to "
                                "be installed."
                            ),
                            fg="red",
                        )
                    else:
                        click.secho(f"{module} update error", fg="red")
            del module
        if rc:
            sys.exit(rc)

    if config.only_i18n or config.i18n_overwrite:
        update_translations(modules)

    print(mode, ",".join(modules), "done")


def update_module_list(config):
    if config.no_update_modulelist:
        click.secho("No update module list flag set. Not updating.")
        return

    rc = _run_shell_cmd("env['ir.module.module'].update_list(); env.cr.commit()")
    if rc:
        sys.exit(rc)


def _get_to_install_modules(config, modules):
    for module in modules:
        if module in ["all"]:
            continue

        if not DBModules.is_module_installed(
            module, raise_exception_not_initialized=(module not in ("base",))
        ):
            listed = DBModules.is_module_listed(module)
            if not listed:
                if module == "base":
                    continue

                if not config.no_update_modulelist:
                    update_module_list(config)
                    listed = DBModules.is_module_listed(module)
                elif not listed:
                    raise Exception(("Module not found to " f"update: {module}"))

                if not listed:
                    raise Exception(
                        (
                            "After updating module list, module "
                            f"was not found: {module}"
                        )
                    )

            yield module


def dangling_check(config):
    dangling_modules = DBModules.get_dangling_modules()
    if any(x[1] == "uninstallable" for x in dangling_modules):
        for x in dangling_modules:
            print("{}: {}".format(*x[:2]))
        if (
            config.interactive
            and input(
                (
                    "Uninstallable modules found - shall I set "
                    "them to 'uninstalled'? [y/N]"
                )
            ).lower()
            == "y"
        ):
            DBModules.set_uninstallable_uninstalled()

    if DBModules.get_dangling_modules():
        if config.interactive:
            DBModules.show_install_state(raise_error=False)
            input("Abort old upgrade and continue? (Ctrl+c to break)")
            DBModules.abort_upgrade()
        else:
            DBModules.abort_upgrade()


@click.group(invoke_without_command=True)
def cli():
    pass


@click.command()
@click.argument("modules", required=False)
@click.option("--non-interactive", is_flag=True)
@click.option("--no-update-modulelist", is_flag=True)
@click.option("--i18n", is_flag=True, help="Overwrite I18N")
@click.option("--only-i18n", is_flag=True)
@click.option("--delete-qweb", is_flag=True)
@click.option("--no-tests", is_flag=True)
@click.option("--test-tags", is_flag=False)
@click.option("--no-dangling-check", is_flag=True)
@click.option("--no-install-server-wide-first", is_flag=True)
@click.option("--no-extra-addons-paths", is_flag=True)
@click.option("--log")
@click.option(
    "--config-file",
    is_flag=False,
    default="config_update",
    help="Which config file to use",
)
@click.option("--server-wide-modules", is_flag=False)
@click.option("--additional-addons-paths", is_flag=False)
@click.option("--upgrade-path", is_flag=False)
@pass_config
def main(
    config,
    modules,
    non_interactive,
    no_update_modulelist,
    i18n,
    only_i18n,
    delete_qweb,
    no_tests,
    no_dangling_check,
    no_install_server_wide_first,
    no_extra_addons_paths,
    config_file,
    additional_addons_paths,
    server_wide_modules,
    test_tags,
    log,
    upgrade_path
):
    # region config
    config.interactive = not non_interactive
    config.i18n_overwrite = i18n
    config.odoo_version = float(os.getenv("ODOO_VERSION"))
    config.only_i18n = only_i18n
    config.no_extra_addons_paths = no_extra_addons_paths
    config.config_file = config_file
    config.server_wide_modules = server_wide_modules
    config.additional_addons_paths = additional_addons_paths
    config.upgrade_path = upgrade_path
    config.test_tags = test_tags
    config.log = log

    config.run_test = not no_tests and os.getenv("ODOO_RUN_TESTS", "1") == "1"

    config.no_update_modulelist = no_update_modulelist
    config.manifest = MANIFEST()
    # endregion

    prepare_run(config)

    modules = list(filter(bool, modules.split(",")))
    summary = defaultdict(list)
    if not modules:
        raise Exception("requires module!")

    if not no_dangling_check:
        dangling_check(config)
    to_install_modules = list(_get_to_install_modules(config, modules))

    # install server wide modules and/or update them
    if not no_install_server_wide_first and not modules or tuple(modules) == ("all",):
        server_wide_modules = config.manifest["server-wide-modules"]
        # leave out base modules
        server_wide_modules = list(
            filter(lambda x: x not in ["web"], server_wide_modules)
        )
        click.secho(line, fg=MAGENTA)
        click.secho(
            f"Installing/Updating Server wide modules {','.join(server_wide_modules)}",
            fg=MAGENTA,
        )
        click.secho(line, fg=MAGENTA)
        to_install_swm = list(
            filter(lambda x: x in to_install_modules, server_wide_modules)
        )
        to_update_swm = list(
            filter(lambda x: x not in to_install_swm, server_wide_modules)
        )
        click.secho(f"Installing {','.join(to_install_swm)}", fg=MAGENTA)
        update(config, "i", to_install_swm)
        click.secho(f"Updating {','.join(to_install_swm)}", fg=MAGENTA)
        update(config, "u", to_update_swm)

    click.secho(line, fg=YELLOW)
    click.secho(f"Updating Module {','.join(modules)}", fg=YELLOW)
    click.secho(line, fg=YELLOW)

    update(config, "i", to_install_modules)
    summary["installed"] += to_install_modules
    modules = list(filter(lambda x: x not in summary["installed"], modules))

    # if delete_qweb:
    # for module in modules:
    # print("Deleting qweb of module {}".format(module))
    # do_delete_qweb(module)

    if modules:
        update(config, "u", modules)
        summary["update"] += modules

    click.secho(LINE, fg=GREEN)
    click.secho("Summary of update module", fg=GREEN)
    click.secho(line, fg=YELLOW)
    for key, value in summary.items():
        click.secho(f'{key}: {",".join(value)}', fg=GREEN)

    click.secho(LINE, fg=YELLOW)


if __name__ == "__main__":
    main()
