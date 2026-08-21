"""Settings files holding secrets must not be readable by others.

Enrolling against the backup server puts the backup passphrase
(OFFSITE_PASSPHRASE) into a settings file. Whoever has it can decrypt the
project's entire offsite backup - parking it behind the permissions of the home
directory is not enough, because a home with 0755 does occur on a machine with
several instance users.
"""

import os
import stat

from ..myconfigparser import MyConfigParser


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_secret_tightens_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "settings"
    path.write_text("")
    path.chmod(0o664)

    cfg = MyConfigParser(path)
    cfg["OFFSITE_PASSPHRASE"] = "geheim"
    cfg.write()

    assert _mode(path) == 0o600
    assert "OFFSITE_PASSPHRASE=geheim" in path.read_text()


def test_harmless_settings_are_left_alone(tmp_path, monkeypatch):
    """No secret, no tightening - otherwise we break files that are readable
    by others on purpose (e.g. shared project settings)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "settings"
    path.write_text("")
    path.chmod(0o664)

    cfg = MyConfigParser(path)
    cfg["RUN_OFFSITE"] = "1"
    cfg.write()

    assert _mode(path) == 0o664


def test_outside_home_is_not_touched(tmp_path, monkeypatch):
    """/etc/odoo/settings is system-wide and has to stay readable."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    path = tmp_path / "etc-settings"
    path.write_text("")
    path.chmod(0o664)

    cfg = MyConfigParser(path)
    cfg["OFFSITE_PASSPHRASE"] = "geheim"
    cfg.write()

    assert _mode(path) == 0o664


def test_already_tight_stays_tight(tmp_path, monkeypatch):
    """Never loosen: a 0400 file stays 0400."""
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "settings"
    path.write_text("")
    path.chmod(0o400)

    cfg = MyConfigParser(path)
    cfg["OFFSITE_PASSPHRASE"] = "geheim"
    cfg.write()

    assert _mode(path) == 0o400
    assert os.access(path, os.R_OK)
