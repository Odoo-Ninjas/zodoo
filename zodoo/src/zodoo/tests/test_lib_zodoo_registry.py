"""Tests for zodoo.lib_zodoo_registry.

Two things are guarded here:

* the interactive ``_get_push_credentials`` flow, which has historically
  broken CI bake runs by aborting on a non-tty stdin, and
* the split between reading and writing. Pulling is anonymous
  (registry.zebroo.de serves zodoo/python without auth), so the read paths
  must never ask for an account -- otherwise a fresh machine is stopped by
  a question before it can pull the prebuilt CPython image.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from zodoo import lib_zodoo_registry as mod


class _FakeConfig(SimpleNamespace):
    pass


@pytest.fixture
def never_asks(monkeypatch):
    """Turn any prompt into a failure."""

    def _boom(*a, **kw):  # pragma: no cover - guard
        raise AssertionError("must not prompt here")

    monkeypatch.setattr(mod.click, "confirm", _boom)
    monkeypatch.setattr(mod.click, "prompt", _boom)


def test_push_credentials_return_none_in_non_interactive_shell(
    monkeypatch, never_asks
):
    """CI / cron / scripted invocations have no tty -- must NOT prompt
    (and must NOT call sys.exit) but silently fall through, leaving
    the build to continue without registry caching."""
    monkeypatch.setattr(mod, "_read_user_setting", lambda config, key: None)
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    assert mod._get_push_credentials(_FakeConfig()) is None


def test_push_credentials_respect_suggested_zero(monkeypatch, never_asks):
    """User previously declined: must not prompt, must return None."""
    monkeypatch.setattr(mod, "_read_user_setting", lambda config, key: "0")

    assert mod._get_push_credentials(_FakeConfig()) is None


class TestGetRegistryUrl:
    """The read side: a URL, no questions, no settings written."""

    def test_falls_back_to_the_config_default(self, monkeypatch, never_asks):
        """This is what makes a fresh machine pull instead of compile:
        ZODOO_REGISTRY_URL has a default in zodoo/src/zodoo/defaults, and
        no credentials are needed to use it."""
        monkeypatch.setattr(mod, "_read_user_setting", lambda config, key: "")
        config = _FakeConfig(ZODOO_REGISTRY_URL="registry.zebroo.de")

        assert mod.get_registry_url(config) == "registry.zebroo.de"

    def test_user_setting_wins(self, monkeypatch, never_asks):
        monkeypatch.setattr(
            mod,
            "_read_user_setting",
            lambda config, key: (
                "other.example.com" if key == "ZODOO_REGISTRY_URL" else ""
            ),
        )
        config = _FakeConfig(ZODOO_REGISTRY_URL="registry.zebroo.de")

        assert mod.get_registry_url(config) == "other.example.com"

    def test_opt_out_still_works(self, monkeypatch, never_asks):
        monkeypatch.setattr(mod, "_read_user_setting", lambda config, key: "0")
        config = _FakeConfig(ZODOO_REGISTRY_URL="registry.zebroo.de")

        assert mod.get_registry_url(config) == ""

    def test_survives_a_missing_settings_file(self, monkeypatch, never_asks):
        """Containers and CI have no ~/.odoo/settings -- that is not an
        opt-out, the default URL must still come through."""

        def _explode(config, key):
            raise KeyError("user_settings")

        monkeypatch.setattr(mod, "_read_user_setting", _explode)
        config = _FakeConfig(ZODOO_REGISTRY_URL="registry.zebroo.de")

        assert mod.get_registry_url(config) == "registry.zebroo.de"

    def test_trailing_slash_is_dropped(self, monkeypatch, never_asks):
        monkeypatch.setattr(mod, "_read_user_setting", lambda config, key: "")
        config = _FakeConfig(ZODOO_REGISTRY_URL="registry.zebroo.de/")

        assert mod.get_registry_url(config) == "registry.zebroo.de"


class TestReadPathsDoNotPrompt:
    """The regression this whole change is about: a machine that only
    consumes images must get through the build without being asked to
    create an account."""

    @pytest.fixture(autouse=True)
    def _no_settings(self, monkeypatch, never_asks):
        monkeypatch.setattr(mod, "_read_user_setting", lambda config, key: "")

        def _no_write(*a, **kw):  # pragma: no cover - guard
            raise AssertionError("read path must not write settings")

        monkeypatch.setattr(mod, "_write_user_setting", _no_write)

    def test_image_exists(self, monkeypatch):
        monkeypatch.setattr(
            mod, "_resolve_registry_image", lambda url, svc, tag: None
        )
        config = _FakeConfig(ZODOO_REGISTRY_URL="registry.zebroo.de")

        assert mod.zodoo_image_exists(config, "odoo", "t") is False

    def test_pull_and_tag(self, monkeypatch):
        monkeypatch.setattr(
            mod, "_resolve_registry_image", lambda url, svc, tag: None
        )
        config = _FakeConfig(ZODOO_REGISTRY_URL="registry.zebroo.de")

        assert mod.zodoo_pull_and_tag(config, "odoo", "t") is False

    def test_login_without_credentials_is_a_noop(self, monkeypatch):
        """No account on this host: hand docker nothing and move on,
        rather than opening the account wizard."""
        monkeypatch.setattr(
            mod, "registry_credentials_from_settings", lambda *a, **kw: None
        )

        def _boom(*a, **kw):  # pragma: no cover - guard
            raise AssertionError("must not touch docker without credentials")

        monkeypatch.setattr(mod, "_docker_login_write_auth", _boom)
        monkeypatch.setattr(mod, "_docker_login_subprocess", _boom)

        mod.zodoo_registry_login(_FakeConfig())


class TestVerifyCredentials:
    """`docker login` reports success for any password once /v2/ is served
    anonymously, so the credentials have to be checked against an endpoint
    that is still protected."""

    @staticmethod
    def _patch_urlopen(monkeypatch, behaviour):
        seen = {}

        def _urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["auth"] = req.headers.get("Authorization")
            return behaviour()

        monkeypatch.setattr(mod.urllib.request, "urlopen", _urlopen)
        return seen

    def test_accepted(self, monkeypatch):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        seen = self._patch_urlopen(monkeypatch, _Resp)

        assert mod.verify_credentials("reg.example", "u", "p") is True
        assert seen["url"].endswith("/v2/_catalog"), (
            "must query an endpoint that is still behind auth — /v2/ itself "
            "is open and would accept anything"
        )
        assert seen["auth"].startswith("Basic ")

    @pytest.mark.parametrize("code", [401, 403])
    def test_rejected(self, monkeypatch, code):
        def _raise():
            raise mod.urllib.error.HTTPError(
                "u", code, "denied", hdrs=None, fp=None
            )

        self._patch_urlopen(monkeypatch, _raise)

        assert mod.verify_credentials("reg.example", "u", "p") is False

    def test_unreachable_is_not_a_wrong_password(self, monkeypatch):
        """Must be distinguishable from a rejection, otherwise a network
        hiccup tells the user their password is wrong."""

        def _raise():
            raise mod.urllib.error.URLError("no route")

        self._patch_urlopen(monkeypatch, _raise)

        assert mod.verify_credentials("reg.example", "u", "p") is None

    def test_server_error_says_nothing_about_the_password(self, monkeypatch):
        def _raise():
            raise mod.urllib.error.HTTPError(
                "u", 500, "boom", hdrs=None, fp=None
            )

        self._patch_urlopen(monkeypatch, _raise)

        assert mod.verify_credentials("reg.example", "u", "p") is None


class TestSiteFromFqdn:
    """odoo.3dm.de -> "3dm": the machine's own name is a better account
    name than the service account it happens to run as."""

    @pytest.mark.parametrize(
        "fqdn,expected",
        [
            ("odoo.3dm.de", "3dm"),
            ("erp.3dm.de", "3dm"),
            ("3dm.de", "3dm"),
            ("odoo.customer.example.com", "customer"),
            ("3dm.odoo.zebroo.de", "3dm"),
            ("ODOO.3DM.DE", "3dm"),
            ("odoo.3dm.de.", "3dm"),
        ],
    )
    def test_derives_the_site(self, fqdn, expected):
        assert mod._site_from_fqdn(fqdn) == expected

    @pytest.mark.parametrize(
        "fqdn",
        [
            "",
            None,
            "odoo",  # no domain at all
            "localhost",  # single label
            "odoo.local",  # nothing left but the suffix
            "odoo.co.uk",  # would otherwise yield "co"
        ],
    )
    def test_gives_up_rather_than_guessing(self, fqdn):
        assert mod._site_from_fqdn(fqdn) == ""


class TestDefaultRegistryUsername:
    def test_a_personal_account_name_is_kept(self, monkeypatch):
        monkeypatch.setattr(mod.getpass, "getuser", lambda: "marcwimmer")
        monkeypatch.setattr(mod.socket, "getfqdn", lambda: "odoo.3dm.de")

        assert mod._default_registry_username() == "marcwimmer"

    def test_a_service_account_is_replaced_by_the_site(self, monkeypatch):
        """ "odoo" is taken on registry.zebroo.de and says nothing about
        which machine is asking."""
        monkeypatch.setattr(mod.getpass, "getuser", lambda: "odoo")
        monkeypatch.setattr(mod.socket, "getfqdn", lambda: "odoo.3dm.de")

        assert mod._default_registry_username() == "3dm"

    def test_falls_back_to_the_account_when_the_fqdn_says_nothing(
        self, monkeypatch
    ):
        monkeypatch.setattr(mod.getpass, "getuser", lambda: "odoo")
        monkeypatch.setattr(mod.socket, "getfqdn", lambda: "localhost")

        assert mod._default_registry_username() == "odoo"

    def test_survives_a_broken_resolver(self, monkeypatch):
        monkeypatch.setattr(mod.getpass, "getuser", lambda: "root")

        def _explode():
            raise OSError("no resolver")

        monkeypatch.setattr(mod.socket, "getfqdn", _explode)

        assert mod._default_registry_username() == "root"
