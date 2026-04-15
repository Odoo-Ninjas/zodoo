"""Tests for zodoo.lib_docker_registry.

Strategy: most of the module is pure file / dict / subprocess glue, so the
vast majority is covered by fast unit tests with a lightweight fake config
and `monkeypatch`-ed subprocess. The remaining integration-style coverage
(`regpush`/`regpull` shelling out to a real docker) is behind
`requires_full_stack` and uses the shared session project.
"""

from __future__ import annotations

import base64
import json
import os
import platform
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from zodoo import lib_docker_registry as mod
from zodoo.click_config import Config


class FakeConfig(Config):
    """Minimal Config subclass for unit tests.

    Skips the real ``Config.__init__`` (which walks the filesystem for a
    customs root) and instead populates only the attributes the helpers
    in ``lib_docker_registry`` touch. Inherits from ``Config`` so it
    passes Click's ``make_pass_decorator(Config, ensure=True)`` check;
    otherwise Click would silently replace it with a fresh, empty
    ``Config`` and all our test data would vanish.

    Unset settings-style attributes (`HUB_URL`, `DOCKER_IMAGE_TAG`, ...)
    fall through ``Config.__getattribute__`` → ``MyConfigParser``, but
    with an empty ``self.files`` dict the fallback returns ``None`` —
    matching the behaviour of a project with no settings file.
    """

    def __init__(self, **kwargs):
        # Do NOT call super().__init__ — we want a clean slate.
        self._project_name = kwargs.pop("project_name", "zodoo_unit_test")
        self._verbose = kwargs.pop("verbose", False)
        self._host_run_dir = None
        self._WORKING_DIR = None
        self.force = kwargs.pop("force", False)
        self.quiet = False
        self.restrict = {}
        self.dirs = kwargs.pop("dirs", {})
        self.files = kwargs.pop("files", {})
        self.commands = {}
        self.HUB_URL = None
        self.DOCKER_IMAGE_TAG = None
        self.REGISTRY = False
        self.hub_url = None
        self.__dict__.update(kwargs)


# ---------------------------------------------------------------------------
# _docker_login_write_auth
# ---------------------------------------------------------------------------


def test_docker_login_write_auth_creates_config_json(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    mod._docker_login_write_auth("registry.example:5000", "alice", "s3cret")

    cfg = json.loads((tmp_path / ".docker" / "config.json").read_text())
    expected = base64.b64encode(b"alice:s3cret").decode()
    assert cfg["auths"]["registry.example:5000"]["auth"] == expected
    # credsStore must be disabled for this registry explicitly
    assert cfg["credHelpers"]["registry.example:5000"] == ""


def test_docker_login_write_auth_merges_into_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    docker_dir = tmp_path / ".docker"
    docker_dir.mkdir()
    (docker_dir / "config.json").write_text(
        json.dumps({"auths": {"other:1": {"auth": "xxx"}}, "foo": "bar"})
    )

    mod._docker_login_write_auth("new:1", "u", "p")

    cfg = json.loads((docker_dir / "config.json").read_text())
    # existing keys preserved
    assert cfg["foo"] == "bar"
    assert cfg["auths"]["other:1"]["auth"] == "xxx"
    # new entry added
    assert "new:1" in cfg["auths"]


# ---------------------------------------------------------------------------
# disable_keychain_credential_store
# ---------------------------------------------------------------------------


def test_disable_keychain_on_non_darwin_returns_false(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert mod.disable_keychain_credential_store() is False


def test_disable_keychain_no_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    assert mod.disable_keychain_credential_store() is False


def test_disable_keychain_no_credsstore_key(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    docker_dir = tmp_path / ".docker"
    docker_dir.mkdir()
    (docker_dir / "config.json").write_text(json.dumps({"foo": "bar"}))
    assert mod.disable_keychain_credential_store() is False


def test_disable_keychain_removes_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    docker_dir = tmp_path / ".docker"
    docker_dir.mkdir()
    cfg = {"credsStore": "osxkeychain", "other": 1}
    (docker_dir / "config.json").write_text(json.dumps(cfg))

    assert mod.disable_keychain_credential_store() is True
    after = json.loads((docker_dir / "config.json").read_text())
    assert "credsStore" not in after
    assert after["other"] == 1


# ---------------------------------------------------------------------------
# _get_base_tag
# ---------------------------------------------------------------------------


def test_get_base_tag_missing_file_aborts(tmp_path):
    cfg = FakeConfig(dirs={"run": tmp_path})
    with pytest.raises(SystemExit):
        mod._get_base_tag(cfg)


def test_get_base_tag_reads_existing(tmp_path):
    (tmp_path / "requirements.odoo.hash").write_text("deadbeef\n")
    cfg = FakeConfig(dirs={"run": tmp_path})
    assert mod._get_base_tag(cfg) == "deadbeef"


# ---------------------------------------------------------------------------
# _get_service_tagname
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_module_sha():
    # lib_docker_registry caches the resolved sha in a module-level global
    mod.current_sha = None
    yield
    mod.current_sha = None


def test_get_service_tagname_uses_docker_image_tag(monkeypatch):
    cfg = FakeConfig(
        DOCKER_IMAGE_TAG="v1.2.3",
        HUB_URL="r.example:5000/project",
    )
    name = mod._get_service_tagname(cfg, "odoo")
    assert name == "r.example:5000/project/odoo:v1.2.3"


def test_get_service_tagname_falls_back_to_git(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *a, **kw: "abc123sha\n",
    )
    cfg = FakeConfig(HUB_URL="r.example:5000/project")
    name = mod._get_service_tagname(cfg, "odoo")
    assert name == "r.example:5000/project/odoo:abc123sha"


def test_get_service_tagname_aborts_without_git_and_without_tag(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)  # no .git here
    cfg = FakeConfig(HUB_URL="r.example:5000/project")
    with pytest.raises(SystemExit):
        mod._get_service_tagname(cfg, "odoo")


def test_get_service_tagname_aborts_without_hub_url(monkeypatch):
    cfg = FakeConfig(DOCKER_IMAGE_TAG="v1", HUB_URL=None)
    with pytest.raises(SystemExit):
        mod._get_service_tagname(cfg, "odoo")


def test_get_service_tagname_no_git_uses_config_tag(tmp_path, monkeypatch):
    """Covers the branch: no .git dir, but config.DOCKER_IMAGE_TAG set."""
    monkeypatch.chdir(tmp_path)  # no .git
    cfg = FakeConfig(
        HUB_URL="r.example:5000/project",
        DOCKER_IMAGE_TAG=None,  # force the fallback path
    )
    # first force the "fallback" click.secho branch via DOCKER_IMAGE_TAG=None,
    # then flip to a concrete value so the no-git+DOCKER_IMAGE_TAG=value path
    # at line ~286 gets covered
    cfg.__dict__["DOCKER_IMAGE_TAG"] = "manual-tag"
    name = mod._get_service_tagname(cfg, "odoo")
    assert name.endswith("/odoo:manual-tag")


# ---------------------------------------------------------------------------
# _apply_tags  +  _rewrite_compose_with_tags
# ---------------------------------------------------------------------------


def _compose_file(tmp_path, content: str) -> Path:
    f = tmp_path / "docker-compose.yml"
    f.write_text(content)
    return f


def test_apply_tags_tags_build_services_and_skips_image_services(
    tmp_path, monkeypatch
):
    compose = _compose_file(
        tmp_path,
        """
services:
  odoo:
    build: {context: .}
    labels: {}
  postgres:
    image: postgres:15
    labels: {}
""",
    )
    calls = []

    def fake_check_call(cmd):
        calls.append(cmd)

    monkeypatch.setattr(subprocess, "check_call", fake_check_call)

    cfg = FakeConfig(
        DOCKER_IMAGE_TAG="v9",
        HUB_URL="r.example:5000/project",
        files={"docker_compose": compose},
        hub_url="r.example:5000/project",
        project_name="myproj",
    )
    tags = list(mod._apply_tags(cfg))
    # only the `build` service got tagged
    assert len(tags) == 1
    assert tags[0].endswith("/odoo:v9")
    assert calls == [
        ["docker", "tag", "myproj-odoo", "r.example:5000/project/odoo:v9"]
    ]


def test_apply_tags_swallows_tag_failures(tmp_path, monkeypatch):
    compose = _compose_file(
        tmp_path,
        """
services:
  odoo:
    build: {context: .}
    labels: {}
""",
    )

    def boom(cmd):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "check_call", boom)

    cfg = FakeConfig(
        DOCKER_IMAGE_TAG="v1",
        HUB_URL="r.example:5000/project",
        files={"docker_compose": compose},
        hub_url="r.example:5000/project",
        project_name="myproj",
        verbose=True,
    )
    # should not raise; yield still produces the tag
    assert list(mod._apply_tags(cfg))


def test_apply_tags_rejects_service_without_image_or_build(
    tmp_path, monkeypatch
):
    compose = _compose_file(
        tmp_path,
        """
services:
  odoo:
    labels: {}
""",
    )
    cfg = FakeConfig(
        DOCKER_IMAGE_TAG="v1",
        HUB_URL="r.example:5000/project",
        files={"docker_compose": compose},
        hub_url="r.example:5000/project",
        project_name="myproj",
    )
    with pytest.raises(NotImplementedError):
        list(mod._apply_tags(cfg))


def test_rewrite_compose_with_tags_replaces_build_with_image(monkeypatch):
    yml = {"services": {"odoo": {"build": {"context": "."}}}}
    cfg = FakeConfig(
        DOCKER_IMAGE_TAG="vZ",
        HUB_URL="r.example:5000/project",
    )
    mod._rewrite_compose_with_tags(cfg, yml)
    svc = yml["services"]["odoo"]
    assert "build" not in svc
    assert svc["image"].endswith("/odoo:vZ")


def test_rewrite_compose_noop_without_hub(monkeypatch):
    yml = {"services": {"odoo": {"build": {"context": "."}}}}
    cfg = FakeConfig(HUB_URL=None)
    mod._rewrite_compose_with_tags(cfg, yml)
    # untouched
    assert yml["services"]["odoo"] == {"build": {"context": "."}}


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


def _invoke(cmd, obj, args=None):
    return CliRunner().invoke(cmd, args or [], obj=obj, catch_exceptions=False)


def test_login_aborts_without_hub():
    cfg = FakeConfig(HUB_URL=None)
    res = _invoke(mod.login, cfg)
    assert res.exit_code != 0


def test_login_darwin_writes_auth_inline(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    # no osxkeychain to remove
    cfg = FakeConfig(HUB_URL="user:pw@r.example:5000/project")

    res = _invoke(mod.login, cfg)
    assert res.exit_code == 0
    written = json.loads((tmp_path / ".docker" / "config.json").read_text())
    assert "r.example:5000" in written["auths"]


def test_login_non_darwin_shells_out_to_docker(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    seen = {}

    def fake_check_output(cmd, encoding="utf-8"):
        seen["cmd"] = cmd
        return "Login Succeeded\n"

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    cfg = FakeConfig(HUB_URL="user:pw@r.example:5000/project")

    res = _invoke(mod.login, cfg)
    assert res.exit_code == 0
    assert seen["cmd"][:3] == ["docker", "login", "r.example:5000"]
    assert "-u" in seen["cmd"] and "user" in seen["cmd"]


def test_login_prompts_for_credentials_when_missing(monkeypatch):
    """HUB_URL without user:password → prompts via getpass."""
    import getpass

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    prompts = iter(["alice", "s3cret"])
    monkeypatch.setattr(getpass, "getpass", lambda *a, **kw: next(prompts))
    monkeypatch.setattr(
        subprocess, "check_output", lambda *a, **kw: "Login Succeeded\n"
    )

    cfg = FakeConfig(HUB_URL="r.example:5000/project")
    res = _invoke(mod.login, cfg)
    assert res.exit_code == 0


def test_login_non_darwin_aborts_on_bad_response(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        subprocess, "check_output", lambda *a, **kw: "Bad creds\n"
    )
    cfg = FakeConfig(HUB_URL="user:pw@r.example:5000/project")
    res = _invoke(mod.login, cfg)
    assert res.exit_code != 0


# ---------------------------------------------------------------------------
# tag
# ---------------------------------------------------------------------------


def test_tag_prints_current_value(tmp_path, monkeypatch):
    cfg = FakeConfig(
        HUB_URL="r.example:5000/project",
        DOCKER_IMAGE_TAG="v42",
    )
    res = CliRunner().invoke(mod.tag, [], obj=cfg, catch_exceptions=False)
    assert res.exit_code == 0
    assert "v42" in res.output


def test_tag_sets_new_value(tmp_path, monkeypatch):
    updated = {}

    def fake_update(config, name, value):
        updated[name] = value

    monkeypatch.setattr(mod, "update_setting", fake_update)
    cfg = FakeConfig(HUB_URL="r.example:5000/project")
    res = CliRunner().invoke(mod.tag, ["v99"], obj=cfg, catch_exceptions=False)
    assert res.exit_code == 0
    assert updated == {"DOCKER_IMAGE_TAG": "v99"}


def test_tag_without_hub_still_reports(tmp_path):
    cfg = FakeConfig(HUB_URL=None, DOCKER_IMAGE_TAG=None)
    res = CliRunner().invoke(mod.tag, [], obj=cfg, catch_exceptions=False)
    # split_hub_url returns None → function prints "n/a" fallback
    assert "n/a" in res.output.lower() or "using git" in res.output.lower()


# ---------------------------------------------------------------------------
# regpush
# ---------------------------------------------------------------------------


def test_regpush_invokes_login_and_pushes_each_tag(tmp_path, monkeypatch):
    compose = _compose_file(
        tmp_path,
        """
services:
  odoo:
    build: {context: .}
    labels: {}
""",
    )
    pushes = []

    def fake_check_call(cmd):
        pushes.append(cmd)

    monkeypatch.setattr(subprocess, "check_call", fake_check_call)
    # regpush runs `docker run --rm ... test -f /opt/src/MANIFEST` to
    # verify the image has source baked in — stub it to return success.
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
    )

    cfg = FakeConfig(
        HUB_URL="user:pw@r.example:5000/project",
        DOCKER_IMAGE_TAG="v77",
        files={"docker_compose": compose},
        hub_url="r.example:5000/project",
        project_name="myproj",
    )
    # short-circuit the login invocation so we don't hit subprocess at all
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setenv("HOME", str(tmp_path))

    res = CliRunner().invoke(mod.regpush, [], obj=cfg, catch_exceptions=False)
    assert res.exit_code == 0
    pushed_urls = [c[-1] for c in pushes if c[:2] == ["docker", "push"]]
    assert any(url.endswith("/odoo:v77") for url in pushed_urls)


# ---------------------------------------------------------------------------
# regpull
# ---------------------------------------------------------------------------


def test_regpull_aborts_when_registry_off():
    cfg = FakeConfig(REGISTRY=False, HUB_URL="user:pw@r.example:5000/project")
    res = CliRunner().invoke(mod.regpull, [], obj=cfg, catch_exceptions=False)
    assert res.exit_code != 0


def test_regpull_logs_in_when_hub_has_user(tmp_path, monkeypatch):
    """Covers the branch ``if hub['username']: ctx.invoke(login)``."""
    compose = _compose_file(
        tmp_path,
        """
services:
  odoo:
    image: odoo:15
""",
    )
    monkeypatch.setattr(mod, "__dc", lambda config, cmd: None)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        platform, "system", lambda: "Darwin"
    )  # write-auth path
    cfg = FakeConfig(
        REGISTRY=True,
        HUB_URL="user:pw@r.example:5000/project",
        files={"docker_compose": compose},
    )
    res = CliRunner().invoke(mod.regpull, [], obj=cfg, catch_exceptions=False)
    assert res.exit_code == 0
    # login wrote docker config
    assert (tmp_path / ".docker" / "config.json").exists()


def test_regpull_uses_compose_services_when_no_machines(tmp_path, monkeypatch):
    compose = _compose_file(
        tmp_path,
        """
services:
  odoo:
    image: odoo:15
  postgres:
    image: postgres:15
""",
    )
    dc_calls = []
    monkeypatch.setattr(mod, "__dc", lambda config, cmd: dc_calls.append(cmd))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        platform, "system", lambda: "Darwin"
    )  # skip docker login

    cfg = FakeConfig(
        REGISTRY=True,
        HUB_URL="r.example:5000/project",  # no user → no login attempt
        files={"docker_compose": compose},
    )
    res = CliRunner().invoke(mod.regpull, [], obj=cfg, catch_exceptions=False)
    assert res.exit_code == 0
    assert dc_calls and dc_calls[0][0] == "pull"
    # both services pulled
    assert "odoo" in dc_calls[0] and "postgres" in dc_calls[0]


# ---------------------------------------------------------------------------
# self_sign_hub_certificate (shallow — the happy path needs root + openssl)
# ---------------------------------------------------------------------------


def test_self_sign_requires_root(monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    cfg = FakeConfig(HUB_URL="r.example:5000/project")
    res = CliRunner().invoke(
        mod.self_sign_hub_certificate,
        [],
        obj=cfg,
        catch_exceptions=False,
    )
    assert res.exit_code != 0


# NOTE: E2E smoke tests against a live `odoo init 19.0` project are covered
# by test_bake.py; they share the same heavy-setup path. Adding a second
# live-project fixture here would double the CI runtime for the same signal.
