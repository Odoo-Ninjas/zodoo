"""Failures while generating the compose file (issue #257).

1. A failing odoo image hook must abort ``odoo reload``: the compose file
   would otherwise lack ODOO_PROJECT_REQUIREMENTS and the odoo configuration,
   and the following ``odoo build`` produced an image without the project's
   pip packages. Auxiliary hooks of other services still only warn.
2. A module on the MANIFEST uninstall list whose dependency no longer exists
   must not break the dependency resolution that the odoo hook runs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from zodoo import lib_composer
from zodoo import module_tools


def _hook(directory, body):
    directory.mkdir(parents=True)
    (directory / "__after_compose.py").write_text(
        "def after_compose(config, settings, yml, globals):\n" + body
    )


def _run_after_compose(tmp_path, monkeypatch, odoo_body, other_body):
    images = tmp_path / "images"
    _hook(images / "odoo", odoo_body)
    _hook(images / "proxy", other_body)
    settings = tmp_path / "settings"
    settings.write_text("")
    monkeypatch.setattr(module_tools, "Modules", lambda: object())
    config = SimpleNamespace(
        dirs={"images": images},
        files={"settings": settings},
        verbose=False,
    )
    yml = {
        "services": {
            "proxy": {
                "labels": {
                    "compose.order": "1",
                    "source.path.proxy": str(
                        images / "proxy" / "docker-compose.yml"
                    ),
                }
            },
            "odoo": {
                "labels": {
                    "compose.order": "2",
                    "source.path.odoo": str(
                        images / "odoo" / "docker-compose.yml"
                    ),
                }
            },
        }
    }
    return lib_composer._execute_after_compose(config, yml)


def test_failing_odoo_hook_aborts_with_traceback(
    tmp_path, monkeypatch, capsys
):
    with pytest.raises(SystemExit) as exc:
        _run_after_compose(
            tmp_path,
            monkeypatch,
            odoo_body="    raise Exception('Module has no path: gone_module')\n",
            other_body="    pass\n",
        )
    assert exc.value.code != 0
    out = capsys.readouterr().out
    assert "Traceback" in out
    assert "Module has no path: gone_module" in out
    assert "after_compose failed" in out


def test_failing_auxiliary_hook_only_warns(tmp_path, monkeypatch, capsys):
    yml = _run_after_compose(
        tmp_path,
        monkeypatch,
        odoo_body="    yml['odoo_hook_ran'] = True\n",
        other_body="    raise PermissionError('read-only images dir')\n",
    )
    assert yml["odoo_hook_ran"] is True
    out = capsys.readouterr().out
    assert "Warning: after_compose failed" in out
    # the traceback is shown now instead of being formatted and dropped
    assert "Traceback" in out


def test_only_the_odoo_image_hook_is_fatal(tmp_path):
    config = SimpleNamespace(dirs={"images": tmp_path})
    assert lib_composer._after_compose_is_fatal(
        config, tmp_path / "odoo" / "__after_compose.py"
    )
    assert not lib_composer._after_compose_is_fatal(
        config, tmp_path / "proxy" / "__after_compose.py"
    )
    assert not lib_composer._after_compose_is_fatal(
        config, tmp_path / "project" / "odoo" / "__after_compose.py"
    )


class FakeModule:
    def __init__(self, name, exists=True):
        self.name = name
        self.exists = exists

    def __repr__(self):
        return f"FakeModule({self.name})"


@pytest.fixture
def modules(monkeypatch):
    """Modules with a fixed dependency graph instead of scanning addon paths.

    keep -> base; old_module (uninstall list) -> gone_dep (no longer exists).
    """
    deps = {
        "keep": [FakeModule("base")],
        "old_module": [
            FakeModule("base"),
            FakeModule("gone_dep", exists=False),
        ],
        "broken": [FakeModule("missing_dep", exists=False)],
    }
    manifest = {"install": ["keep"], "uninstall": ["old_module"]}
    monkeypatch.setattr(module_tools, "MANIFEST", lambda: manifest)

    obj = module_tools.Modules.__new__(module_tools.Modules)
    monkeypatch.setattr(
        obj,
        "get_customs_modules",
        lambda include_uninstall=False: [
            FakeModule(x)
            for x in manifest["install"]
            + (manifest["uninstall"] if include_uninstall else [])
        ],
    )
    monkeypatch.setattr(
        obj,
        "get_filtered_auto_install_modules_based_on_module_list",
        lambda m: [],
    )
    monkeypatch.setattr(
        obj,
        "get_module_flat_dependency_tree",
        lambda module: deps[module.name],
    )
    return obj, manifest


def _names(result):
    return {x if isinstance(x, str) else x.name for x in result}


def test_missing_dependency_of_uninstall_module_is_ignored(modules):
    obj, _ = modules
    names = _names(obj.get_all_used_modules(include_uninstall=True))
    assert "old_module" in names  # still collected: it may still be installed
    assert "gone_dep" not in names


def test_missing_dependency_of_install_module_still_surfaces(modules):
    obj, manifest = modules
    manifest["install"].append("broken")
    result = obj.get_all_used_modules(include_uninstall=True)
    missing = [x for x in result if not isinstance(x, str) and not x.exists]
    assert [x.name for x in missing] == ["missing_dep"]


def test_module_on_both_lists_is_treated_as_install(modules):
    obj, manifest = modules
    manifest["install"].append("old_module")
    names = _names(obj.get_all_used_modules(include_uninstall=True))
    assert "gone_dep" in names
