"""Tests fuer zodoo.lib_offsite.

Der eigentliche Backup-Lauf steckt im offsite-Container (restic) und wird
nicht hier geprueft. Was hier zaehlt, sind die Teile auf der Host-Seite, an
denen ein Fehler teuer ist:

* die Ableitung des Bereichsnamens (ein ungueltiger Name prallt sonst erst
  beim Backup-Server ab, und zwar bei jedem Kunden anders),
* die Anmeldung am Backup-Server (Anfrage stellen, Zustand merken,
  Zugangsdaten uebernehmen) — inklusive der Faelle, in denen NICHTS in die
  Settings geschrieben werden darf.
"""

from __future__ import annotations

import json

import click
import pytest

from zodoo import lib_offsite as mod
from zodoo.click_config import Config


class FakeConfig(Config):
    """Wie in test_lib_backup: an Config vorbei, damit kein Projekt noetig ist."""

    def __init__(self, **kwargs):
        self._project_name = kwargs.pop("project_name", "zodoo_unit_test")
        self._verbose = False
        self._host_run_dir = None
        self._WORKING_DIR = None
        self.force = False
        self.quiet = False
        self.restrict = {}
        self.dirs = {}
        self.files = {}
        self.commands = {}
        defaults = {
            "OFFSITE_PASSPHRASE": "",
            "OFFSITE_ENROLL_URL": "https://backup.invalid:8443",
        }
        defaults.update(kwargs)
        self.__dict__.update(defaults)


# ---------------------------------------------------------------------------
# _area_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "projectname,expected",
    [
        ("hpnprod17", "hpnprod17"),
        # Grossbuchstaben und Punkte kommen in Projektnamen vor, im
        # Bereichsnamen aber nicht.
        ("Logiston_Main", "logiston_main"),
        ("odoo.kunde", "odoo-kunde"),
        # Ticketnamen fangen mit Buchstaben an, Zahlen-Praefixe nicht: dann
        # wird vorne ein Buchstabe angestellt, statt den Server abzulehnen.
        ("3dm", "p3dm"),
        # Doppelte und aeussere Trenner werden eingesammelt.
        ("ZO--05123 Kunde ", "zo-05123-kunde"),
    ],
)
def test_area_name_derives_valid_names(projectname, expected):
    assert mod._area_name(FakeConfig(), projectname) == expected


def test_area_name_aborts_when_nothing_usable_remains():
    # Nur Sonderzeichen: daraus laesst sich kein Name bilden. Lieber hier
    # abbrechen als eine kaputte Anfrage stellen.
    with pytest.raises(SystemExit):
        mod._area_name(FakeConfig(), "!!!")


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def _run_register(config, monkeypatch, answers, name=None, note=""):
    """Ruft die register-Logik mit vorgegebenen Serverantworten auf.

    answers: Liste von (methode, pfad-fragment, antwort) in Aufrufreihenfolge.
    """
    calls = []
    written = {}

    def fake_call(cfg, method, path, payload=None):
        calls.append((method, path, payload))
        expect_method, expect_fragment, answer = answers.pop(0)
        assert method == expect_method
        assert expect_fragment in path
        return answer

    monkeypatch.setattr(mod, "_enroll_call", fake_call)
    monkeypatch.setattr(
        "zodoo.tools.update_setting",
        lambda cfg, key, value, **kw: written.__setitem__(key, value),
    )
    # pass_config holt die Config aus dem click-Kontext (make_pass_decorator),
    # deshalb hier ein Kontext mit unserer FakeConfig als obj.
    ctx = click.Context(mod.offsite_register)
    ctx.obj = config
    with ctx:
        mod.offsite_register.callback(name=name, note=note)
    return calls, written


@pytest.fixture
def config_with_rundir(tmp_path):
    cfg = FakeConfig(project_name="testkunde")
    cfg._host_run_dir = tmp_path
    # Damit das Zertifikat nicht ueber das Netz geholt wird.
    (tmp_path / "offsite").mkdir()
    (tmp_path / "offsite" / "rest-server.crt").write_text("PEM")
    return cfg


def test_register_first_call_creates_request_and_stores_state(
    config_with_rundir, monkeypatch
):
    calls, written = _run_register(
        config_with_rundir,
        monkeypatch,
        [
            (
                "POST",
                "/api/request",
                {
                    "request_id": "abc123",
                    "pickup_token": "tok",
                    "status": "pending",
                },
            )
        ],
    )
    # Beim ersten Aufruf darf noch NICHTS in die Settings wandern.
    assert written == {}
    state = json.loads(
        (
            config_with_rundir._host_run_dir / "offsite" / "enroll.json"
        ).read_text()
    )
    assert state == {
        "area": "testkunde",
        "request_id": "abc123",
        "token": "tok",
    }
    assert calls[0][2]["area"] == "testkunde"
    # Ohne eigene Passphrase soll der Server einen Repo-Key erzeugen.
    assert calls[0][2]["own_repo_key"] is False


def test_register_passes_own_repo_key_when_passphrase_exists(
    config_with_rundir, monkeypatch
):
    # Shop/zCICD legen die Passphrase je Projekt selbst ab. Dann darf der
    # Server keinen zweiten Schluessel erfinden.
    config_with_rundir.__dict__["OFFSITE_PASSPHRASE"] = "vom-backend"
    calls, _ = _run_register(
        config_with_rundir,
        monkeypatch,
        [("POST", "/api/request", {"request_id": "x", "pickup_token": "t"})],
    )
    assert calls[0][2]["own_repo_key"] is True


def test_register_pending_writes_no_settings(config_with_rundir, monkeypatch):
    edir = config_with_rundir._host_run_dir / "offsite"
    (edir / "enroll.json").write_text(
        json.dumps({"area": "testkunde", "request_id": "abc", "token": "tok"})
    )
    _, written = _run_register(
        config_with_rundir,
        monkeypatch,
        [("GET", "/api/status", {"status": "pending"})],
    )
    assert written == {}


def test_register_approved_writes_settings_and_clears_state(
    config_with_rundir, monkeypatch
):
    edir = config_with_rundir._host_run_dir / "offsite"
    (edir / "enroll.json").write_text(
        json.dumps({"area": "testkunde", "request_id": "abc", "token": "tok"})
    )
    _, written = _run_register(
        config_with_rundir,
        monkeypatch,
        [
            (
                "GET",
                "/api/status",
                {
                    "status": "approved",
                    "user": "testkunde",
                    "password": "zugang",
                    "repo_key": "geheim",
                    "repo_url": "rest:https://10.222.0.106:8000/testkunde/",
                    "ca_cert": "PEM-NEU",
                },
            )
        ],
    )
    assert (
        written["OFFSITE_REPO"] == "rest:https://10.222.0.106:8000/testkunde/"
    )
    assert written["OFFSITE_REST_USER"] == "testkunde"
    assert written["OFFSITE_REST_PASSWORD"] == "zugang"
    assert written["OFFSITE_PASSPHRASE"] == "geheim"
    assert written["RUN_OFFSITE"] == "1"
    assert (edir / "rest-server.crt").read_text() == "PEM-NEU"
    # Die Anfrage ist erledigt und darf nicht als offen liegenbleiben.
    assert not (edir / "enroll.json").exists()


def test_register_keeps_own_passphrase_when_server_sends_none(
    config_with_rundir, monkeypatch
):
    config_with_rundir.__dict__["OFFSITE_PASSPHRASE"] = "vom-backend"
    edir = config_with_rundir._host_run_dir / "offsite"
    (edir / "enroll.json").write_text(
        json.dumps({"area": "testkunde", "request_id": "abc", "token": "tok"})
    )
    _, written = _run_register(
        config_with_rundir,
        monkeypatch,
        [
            (
                "GET",
                "/api/status",
                {
                    "status": "approved",
                    "user": "testkunde",
                    "password": "zugang",
                    "repo_key": "",
                    "repo_url": "rest:https://10.222.0.106:8000/testkunde/",
                },
            )
        ],
    )
    # Die Passphrase der Maschine bleibt stehen - sie ist die Wahrheit.
    assert "OFFSITE_PASSPHRASE" not in written


def test_register_rejected_aborts_and_drops_state(
    config_with_rundir, monkeypatch
):
    edir = config_with_rundir._host_run_dir / "offsite"
    (edir / "enroll.json").write_text(
        json.dumps({"area": "testkunde", "request_id": "abc", "token": "tok"})
    )
    with pytest.raises(SystemExit):
        _run_register(
            config_with_rundir,
            monkeypatch,
            [("GET", "/api/status", {"status": "rejected"})],
        )
    assert not (edir / "enroll.json").exists()


def test_register_delivered_does_not_overwrite_settings(
    config_with_rundir, monkeypatch
):
    # Der Server gibt die Daten nur einmal heraus. Ein zweiter Aufruf darf
    # nicht mit leeren Werten ueber die Settings gehen.
    edir = config_with_rundir._host_run_dir / "offsite"
    (edir / "enroll.json").write_text(
        json.dumps({"area": "testkunde", "request_id": "abc", "token": "tok"})
    )
    with pytest.raises(SystemExit):
        _run_register(
            config_with_rundir,
            monkeypatch,
            [("GET", "/api/status", {"status": "delivered"})],
        )
