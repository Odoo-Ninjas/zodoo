"""Der Zertifikatsordner muss dem pgbackrest-Benutzer gehoeren.

Gehoert er ihm nicht, meldet pgBackRest [CryptoError] "unable to set
user-defined CA certificate location" - eine Meldung, die auf ein kaputtes
Zertifikat zeigt, waehrend in Wahrheit nur ein 0700-Ordner dem falschen
Benutzer gehoert. Am 13.09.2026 auf cicd-3dm genau so passiert.
"""

import subprocess
from types import SimpleNamespace

import pytest

from zodoo import lib_pgbackrest as modul


class _Ergebnis:
    def __init__(self, stdout=""):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


@pytest.fixture
def aufgezeichnet(monkeypatch):
    """subprocess.run abfangen und den Aufruf festhalten."""
    aufrufe = []

    def _run(cmd, **kwargs):
        aufrufe.append(cmd)
        return _Ergebnis(_run.ausgabe)

    _run.ausgabe = ""
    monkeypatch.setattr(modul.subprocess, "run", _run)
    monkeypatch.setattr(modul, "__get_cmd", lambda config: ["docker", "compose"])
    return aufrufe, _run


def test_richtet_als_root_und_nur_bei_bedarf(aufgezeichnet):
    aufrufe, _run = aufgezeichnet
    modul._richte_zertifikate(SimpleNamespace())

    assert len(aufrufe) == 1
    befehl = aufrufe[0]
    # Nur root darf den Besitz vergeben - deshalb explizit --user 0.
    assert "--user" in befehl and befehl[befehl.index("--user") + 1] == "0"
    assert "pgbackrest" in befehl
    skript = befehl[-1]
    # Erst pruefen, dann anfassen: stimmt der Besitz, passiert nichts.
    assert "stat -c %u /etc/pgbackrest/cert" in skript
    assert "chown -R 999:999 /etc/pgbackrest/cert" in skript
    assert "chmod 700 /etc/pgbackrest/cert" in skript


def test_meldet_wenn_gerichtet_wurde(aufgezeichnet, capsys):
    aufrufe, _run = aufgezeichnet
    _run.ausgabe = "GERICHTET\n"
    modul._richte_zertifikate(SimpleNamespace())
    assert "Zertifikatsordner" in capsys.readouterr().out


def test_schweigt_wenn_alles_stimmt(aufgezeichnet, capsys):
    modul._richte_zertifikate(SimpleNamespace())
    assert capsys.readouterr().out == ""


def test_ein_fehler_haelt_den_befehl_nicht_auf(monkeypatch):
    """Die Reparatur ist Beiwerk - sie darf `info` nicht verhindern."""

    def _kaputt(cmd, **kwargs):
        raise subprocess.SubprocessError("kein Container")

    monkeypatch.setattr(modul.subprocess, "run", _kaputt)
    monkeypatch.setattr(modul, "__get_cmd", lambda config: ["docker", "compose"])
    modul._richte_zertifikate(SimpleNamespace())   # darf nicht werfen
