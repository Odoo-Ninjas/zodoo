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


def test_the_pgbackrest_passphrase_counts_as_a_secret(tmp_path, monkeypatch):
    """PGBR_CIPHER_PASS fiel durch das Raster.

    Es heisst weder ...PASSPHRASE noch ...PASSWORD, also griff das Verengen
    nicht - ausgerechnet bei der Passphrase, die den ganzen Datenbankbestand
    eines Kunden aufschliesst. Auf einer produktiven Instanz lag die Datei
    deshalb weiter auf 0664, gerettet nur von den Rechten des Home.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "settings"
    path.write_text("")
    path.chmod(0o664)

    cfg = MyConfigParser(path)
    cfg["PGBR_CIPHER_PASS"] = "geheim"
    cfg.write()

    assert _mode(path) == 0o600
    assert "PGBR_CIPHER_PASS=geheim" in path.read_text()


def test_the_cipher_type_alone_does_not_tighten():
    """PGBR_CIPHER_TYPE ist kein Geheimnis - und hat IMMER einen Wert.

    Erst stand hier das Gegenteil, mit dem Argument "zu eng kostet nichts".
    Es kostet doch: mit "CIPHER" als Hinweiswort waere jede
    Einstellungsdatei verengt worden, weil die Art immer gesetzt ist. Der
    Bake-Lauf ist daran gescheitert.
    """
    # Fachlich deckt das der Test unten mit ab (leere Passphrase, gesetzte
    # Art -> keine Verengung); hier bleibt nur die Begruendung stehen.


def test_an_empty_secret_is_not_a_secret(tmp_path, monkeypatch):
    """Der Schluessel allein genuegt nicht, der Wert muss da sein.

    In jeder Projektdatei stehen PGBR_CIPHER_PASS und DEFAULT_DEV_PASSWORD
    auch leer. Wuerde schon der Name verengen, waere jede Einstellungsdatei
    betroffen - breiter als noetig, und im Bake-Lauf hat es gestoert.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "settings"
    path.write_text("")
    path.chmod(0o664)

    cfg = MyConfigParser(path)
    cfg["PGBR_CIPHER_PASS"] = ""
    cfg["PGBR_CIPHER_TYPE"] = "aes-256-cbc"
    cfg.write()

    assert _mode(path) == 0o664
