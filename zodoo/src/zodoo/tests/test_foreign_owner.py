"""Warn when odoo is run from a shell that does not own the project tree.

The case this is for: a root shell inside /home/odoo/odoo. Everything the
command writes ends up owned by root, and the odoo user cannot change it
afterwards. It surfaces much later as a build stopping with "permission
denied" or a container that will not start -- by which point nobody connects
it to the one command that ran as the wrong user.

Sibling of settings._check_owner_uid, which catches the same mistake once it
has reached OWNER_UID and aborts. Here we only warn: running as another user
is unusual, not impossible.
"""

import os

import pytest

from zodoo import tools


@pytest.fixture
def as_uid(monkeypatch):
    def _set(my_uid, owner_uid):
        monkeypatch.setattr(tools.os, "getuid", lambda: my_uid, raising=False)
        monkeypatch.setattr(
            tools.os,
            "stat",
            lambda p: os.stat_result((0,) * 4 + (owner_uid, 0) + (0,) * 4),
        )
        monkeypatch.setattr(tools, "_is_in_container", lambda: False)

    return _set


class TestQuietWhenNothingIsWrong:
    def test_owner_is_the_current_user(self, as_uid, capsys):
        as_uid(my_uid=1000, owner_uid=1000)

        assert tools.warn_if_foreign_owner("/home/odoo/odoo") is None
        assert capsys.readouterr().out == ""

    def test_inside_a_container(self, monkeypatch, capsys):
        """The entrypoint rewrites uids in there on purpose, so a mismatch
        is the normal state and means nothing."""
        monkeypatch.setattr(tools.os, "getuid", lambda: 0, raising=False)
        monkeypatch.setattr(tools, "_is_in_container", lambda: True)

        assert tools.warn_if_foreign_owner("/opt/src") is None
        assert capsys.readouterr().out == ""

    def test_unreadable_path_is_not_an_error(self, monkeypatch, capsys):
        """A failing check must never stop the command."""
        monkeypatch.setattr(tools, "_is_in_container", lambda: False)

        def _boom(p):
            raise OSError("gone")

        monkeypatch.setattr(tools.os, "stat", _boom)

        assert tools.warn_if_foreign_owner("/does/not/exist") is None
        assert capsys.readouterr().out == ""


class TestWarns:
    def test_root_in_a_user_directory(self, as_uid, capsys):
        as_uid(my_uid=0, owner_uid=1000)

        msg = tools.warn_if_foreign_owner("/home/odoo/odoo")
        out = capsys.readouterr().out

        assert msg is not None
        assert "/home/odoo/odoo" in out
        assert "root" in out
        assert "owned by root" in out, "must say what the damage is"
        assert "su - " in out, "must say how to do it right"

    def test_root_warning_steers_away_from_sudo_iu(self, as_uid, capsys):
        """`sudo -iu odoo` out of a root shell is what produces OWNER_UID=0;
        recommending it here would send people into the next trap."""
        as_uid(my_uid=0, owner_uid=1000)
        tools.warn_if_foreign_owner("/home/odoo/odoo")

        out = capsys.readouterr().out
        assert "sudo -iu" in out and "not `sudo -iu" in out.replace("\n", " ")

    def test_other_user_gets_a_milder_message(self, as_uid, capsys):
        as_uid(my_uid=1001, owner_uid=1000)

        msg = tools.warn_if_foreign_owner("/home/odoo/odoo")
        out = capsys.readouterr().out

        assert msg is not None
        assert "owned by root" not in out
        assert "right account" in out
