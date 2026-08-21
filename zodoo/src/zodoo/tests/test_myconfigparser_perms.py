"""Settings-Dateien mit Geheimnissen duerfen nicht fuer andere lesbar sein.

Die Backup-Passphrase (OFFSITE_PASSPHRASE) landet beim Anmelden am
Backup-Server in einer Settings-Datei. Wer sie hat, kann das gesamte Offsite-
Backup des Projekts entschluesseln - sie hinter den Rechten des
Home-Verzeichnisses zu parken reicht nicht, weil ein Home mit 0755 auf einer
Maschine mit mehreren Instanz-Usern durchaus vorkommt.
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
    """Kein Geheimnis, keine Verengung - sonst brechen wir Dateien, die
    absichtlich fuer andere lesbar sind (z.B. gemeinsame Projekt-Settings)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "settings"
    path.write_text("")
    path.chmod(0o664)

    cfg = MyConfigParser(path)
    cfg["RUN_OFFSITE"] = "1"
    cfg.write()

    assert _mode(path) == 0o664


def test_outside_home_is_not_touched(tmp_path, monkeypatch):
    """/etc/odoo/settings ist systemweit und muss lesbar bleiben."""
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
    """Nie lockern: eine 0400-Datei bleibt 0400."""
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "settings"
    path.write_text("")
    path.chmod(0o400)

    cfg = MyConfigParser(path)
    cfg["OFFSITE_PASSPHRASE"] = "geheim"
    cfg.write()

    assert _mode(path) == 0o400
    assert os.access(path, os.R_OK)
