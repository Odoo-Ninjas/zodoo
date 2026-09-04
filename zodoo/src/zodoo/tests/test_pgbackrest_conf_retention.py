"""Tests der erzeugten pgbackrest.conf - Schwerpunkt Aufbewahrung.

Warum ausgerechnet die: bis 2026-08-31 lief NIRGENDS ein `expire`. Die Instanz
liess die Aufbewahrung weg, weil sie beim Repo-Host "drueben" gehoere, und der
Repo-Host kann sie nicht durchsetzen - `expire` muss `backup.info` lesen, und
die ist verschluesselt. Eine Aufraeumung, die eingerichtet war und nie wirkte;
genau der Fehler, vor dem der Kommentar in `_retention_lines` warnt.
"""

import importlib.util
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[4]
QUELLE = WURZEL / "pgbackrest" / "__after_compose.py"


def _modul():
    if not QUELLE.exists():          # ausserhalb des Repos (installiertes Paket)
        pytest.skip(f"{QUELLE} nicht vorhanden")
    spec = importlib.util.spec_from_file_location("pgbr_after_compose", QUELLE)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


BASIS = {
    "PGBR_REPO_HOST": "db.backup.zebroo.de",
    "PGBR_REPO_HOST_PORT": "443",
    "PGBR_CIPHER_PASS": "geheim",
    "PGBR_STANZA": "kunde-a",
}


def test_the_pusher_gets_retention():
    """Wer sichert, raeumt auch auf - und nur er kann es hier."""
    m = _modul()
    text = m._repo_section(dict(BASIS, PGBR_BACKUP_FROM="here"))
    assert "repo1-retention-full-type=time" in text
    assert "repo1-retention-full=14" in text


def test_retention_defaults_are_used_when_empty():
    """Leer heisst 'Vorgabe', niemals 'alles behalten'."""
    m = _modul()
    text = m._repo_section(dict(BASIS, PGBR_BACKUP_FROM="here",
                                PGBR_RETENTION_FULL="",
                                PGBR_RETENTION_FULL_TYPE=""))
    assert "repo1-retention-full=14" in text
    assert "repo1-retention-full-type=time" in text


def test_the_puller_does_not_get_retention():
    """Sichert der Repo-Host selbst, waere die Regel hier wirkungslos."""
    m = _modul()
    text = m._repo_section(dict(BASIS, PGBR_BACKUP_FROM="repo-host"))
    assert "repo1-retention" not in text


def test_a_local_repository_still_gets_retention():
    m = _modul()
    text = m._repo_section({"PGBR_CIPHER_PASS": "geheim"})
    assert "repo1-path=/var/lib/pgbackrest" in text
    assert "repo1-retention-full=14" in text


def test_the_pusher_never_gets_a_repo_path():
    """Der Pfad liegt auf der anderen Maschine und geht uns nichts an."""
    m = _modul()
    text = m._repo_section(dict(BASIS, PGBR_BACKUP_FROM="here"))
    assert "repo1-path" not in text
    assert "repo1-host=db.backup.zebroo.de" in text


# --------------------------------------------------------------------------- #
# Die Passphrase gehoert in keine Dienst-Umgebung                              #
# --------------------------------------------------------------------------- #
#
# zodoo haengt jedem Dienst die Einstellungsdatei als env_file an, und
# `docker compose config` loest sie auf. Auf einer produktiven Instanz stand
# PGBR_CIPHER_PASS damit 18 Mal in der erzeugten docker-compose.yml (0644) und
# in der Umgebung von Grafana, Proxy, Konsole und allem anderen. Gelesen wird
# sie von dort NIRGENDS.


def _yml_mit_passphrase():
    return {"services": {
        "postgres": {"environment": {"PGBR_CIPHER_PASS": "geheim",
                                     "DB_PORT": "5432"}},
        "grafana": {"environment": {"PGBR_CIPHER_PASS": "geheim"}},
        "proxy": {"environment": ["PGBR_CIPHER_PASS=geheim", "FOO=bar"]},
        "ohne": {},
    }}


def test_the_passphrase_is_stripped_from_every_service():
    m = _modul()
    yml = _yml_mit_passphrase()
    assert m._strip_passphrase_from_environments(yml) == 3
    for name, service in yml["services"].items():
        u = service.get("environment")
        if isinstance(u, dict):
            assert "PGBR_CIPHER_PASS" not in u, name
        elif isinstance(u, list):
            assert not any("PGBR_CIPHER_PASS" in e for e in u), name


def test_other_variables_survive():
    """Nur die Passphrase, nicht das halbe Environment."""
    m = _modul()
    yml = _yml_mit_passphrase()
    m._strip_passphrase_from_environments(yml)
    assert yml["services"]["postgres"]["environment"]["DB_PORT"] == "5432"
    assert "FOO=bar" in yml["services"]["proxy"]["environment"]


def test_a_service_without_environment_is_no_problem():
    m = _modul()
    yml = {"services": {"leer": {}}}
    assert m._strip_passphrase_from_environments(yml) == 0


def test_it_also_runs_with_pgbackrest_switched_off():
    """Sonst bleibt die leere Variable ueberall stehen - und ist wieder da,
    sobald jemand einschaltet."""
    m = _modul()
    yml = _yml_mit_passphrase()
    m.after_compose(None, {"RUN_PGBACKREST": "0"}, yml, {})
    assert "PGBR_CIPHER_PASS" not in yml["services"]["grafana"]["environment"]


# --------------------------------------------------------------------------- #
# Die Passphrase steht nicht in der gemounteten Konfiguration                  #
# --------------------------------------------------------------------------- #
#
# Die pgbackrest.conf wird nach /etc/pgbackrest der Container gemountet und
# muss fuer den Container-Benutzer lesbar bleiben - 0644. Das Verzeichnis
# enger zu ziehen hilft nicht, dann kommt der Container selbst nicht mehr hin.
# Also gehoert das Geheimnis nicht in diese Datei, sondern in die Umgebung
# der zwei Dienste, die es brauchen. Nachgewiesen am 02.09.2026: pgBackRest
# oeffnet ein verschluesseltes Repository allein mit
# PGBACKREST_REPO1_CIPHER_PASS aus der Umgebung.


def test_the_conf_has_the_cipher_type_but_not_the_passphrase():
    m = _modul()
    text = m._repo_section(dict(BASIS, PGBR_BACKUP_FROM="here"))
    assert "repo1-cipher-type=aes-256-cbc" in text
    assert "repo1-cipher-pass=" not in text
    assert "geheim" not in text


def test_only_postgres_and_the_sidecar_get_the_passphrase():
    m = _modul()
    yml = {"services": {
        "postgres": {"environment": {}},
        "pgbackrest": {"environment": {}},
        "grafana": {"environment": {}},
        "odoo": {"environment": {}},
    }}
    assert m._inject_passphrase(yml, {"PGBR_CIPHER_PASS": "geheim"}) == 2
    assert yml["services"]["postgres"]["environment"][m.CIPHER_ENV] == "geheim"
    assert yml["services"]["pgbackrest"]["environment"][m.CIPHER_ENV] == "geheim"
    assert m.CIPHER_ENV not in yml["services"]["grafana"]["environment"]
    assert m.CIPHER_ENV not in yml["services"]["odoo"]["environment"]


def test_without_a_passphrase_nothing_is_injected():
    """Unverschluesselt ist eine eigene Lage, kein leerer Wert ueberall."""
    m = _modul()
    yml = {"services": {"postgres": {"environment": {}}}}
    assert m._inject_passphrase(yml, {"PGBR_CIPHER_PASS": ""}) == 0
    assert yml["services"]["postgres"]["environment"] == {}


def test_a_missing_sidecar_is_no_problem():
    m = _modul()
    yml = {"services": {"postgres": {"environment": {}}}}
    assert m._inject_passphrase(yml, {"PGBR_CIPHER_PASS": "geheim"}) == 1


def test_switched_off_puts_the_passphrase_nowhere():
    """Der Reihenfolge-Fehler, den ich beim Bauen erst falsch hatte."""
    m = _modul()
    yml = {"services": {
        "postgres": {"environment": {"PGBR_CIPHER_PASS": "geheim"}},
        "grafana": {"environment": {"PGBR_CIPHER_PASS": "geheim"}},
    }}
    m.after_compose(None, {"RUN_PGBACKREST": "0",
                           "PGBR_CIPHER_PASS": "geheim"}, yml, {})
    for name, service in yml["services"].items():
        assert "PGBR_CIPHER_PASS" not in service["environment"], name
        assert m.CIPHER_ENV not in service["environment"], name
