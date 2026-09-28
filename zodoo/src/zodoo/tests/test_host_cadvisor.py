"""Tests fuer den gemeinsamen cadvisor der Maschine.

Schnell und ohne Docker: der Docker-Aufruf ist der einzige Ausgang des
Moduls, und genau der wird hier ersetzt. Geprueft wird, WAS zodoo mit dem
Behaelter macht -- anlegen, neu anlegen, nur starten, in Ruhe lassen.

Das Zusammenspiel mit einem echten cadvisor (Abruf ueber das gemeinsame
Netz) deckt der bake-Test ab, nicht diese Datei.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from zodoo import lib_host_cadvisor as mod

REPO_ROOT = Path(__file__).resolve().parents[4]
AFTER_COMPOSE = REPO_ROOT / "dashboard" / "__after_compose.py"


class FakeDocker:
    """Nimmt die Aufrufe auf und antwortet nach Vorgabe."""

    def __init__(self, antworten):
        self.antworten = antworten
        self.aufrufe = []

    def __call__(self, *args, check=True):
        self.aufrufe.append(list(args))
        for muster, (rc, out) in self.antworten.items():
            if list(muster) == list(args[: len(muster)]):
                if rc and check:
                    raise subprocess.CalledProcessError(rc, args, output=out)
                return SimpleNamespace(returncode=rc, stdout=out)
        return SimpleNamespace(returncode=0, stdout="")

    def hat(self, *anfang):
        return any(a[: len(anfang)] == list(anfang) for a in self.aufrufe)


def _patch(monkeypatch, antworten):
    fake = FakeDocker(antworten)
    monkeypatch.setattr(mod, "_docker", fake)
    return fake


def test_fingerabdruck_haengt_an_der_beschreibung(monkeypatch):
    vorher = mod.fingerabdruck()
    assert vorher == mod.fingerabdruck()
    monkeypatch.setattr(mod, "ARGUMENTE", mod.ARGUMENTE + ["--neu"])
    assert mod.fingerabdruck() != vorher


def test_legt_an_wenn_es_ihn_nicht_gibt(monkeypatch):
    fake = _patch(
        monkeypatch,
        {
            ("network", "inspect"): (0, ""),
            ("inspect",): (1, "No such object"),
        },
    )
    mod.ensure()
    assert fake.hat("run", "-d", "--name", mod.CONTAINER)
    lauf = [a for a in fake.aufrufe if a[0] == "run"][0]
    assert "--network" in lauf and mod.NETZ in lauf
    assert f"{mod.LABEL}={mod.fingerabdruck()}" in lauf
    assert lauf[-len(mod.ARGUMENTE) :] == mod.ARGUMENTE


def test_legt_neu_an_wenn_die_beschreibung_sich_geaendert_hat(monkeypatch):
    fake = _patch(
        monkeypatch,
        {
            ("network", "inspect"): (0, ""),
            ("inspect",): (0, "true\taltmodisch"),
        },
    )
    mod.ensure()
    assert fake.hat("rm", "-f", mod.CONTAINER)
    assert fake.hat("run", "-d", "--name", mod.CONTAINER)


def test_startet_nur_wenn_er_gestoppt_ist(monkeypatch):
    fake = _patch(
        monkeypatch,
        {
            ("network", "inspect"): (0, ""),
            ("inspect",): (0, f"false\t{mod.fingerabdruck()}"),
        },
    )
    mod.ensure()
    assert fake.hat("start", mod.CONTAINER)
    assert not fake.hat("run", "-d", "--name", mod.CONTAINER)


def test_laesst_ihn_in_ruhe_wenn_alles_stimmt(monkeypatch):
    fake = _patch(
        monkeypatch,
        {
            ("network", "inspect"): (0, ""),
            ("inspect",): (0, f"true\t{mod.fingerabdruck()}"),
        },
    )
    mod.ensure()
    assert not fake.hat("run", "-d", "--name", mod.CONTAINER)
    assert not fake.hat("start", mod.CONTAINER)
    assert not fake.hat("rm", "-f", mod.CONTAINER)


def test_netz_wird_angelegt_wenn_es_fehlt(monkeypatch):
    fake = _patch(
        monkeypatch,
        {
            ("network", "inspect"): (1, "No such network"),
            ("network", "create"): (0, ""),
            ("inspect",): (0, f"true\t{mod.fingerabdruck()}"),
        },
    )
    mod.ensure()
    assert fake.hat("network", "create", mod.NETZ)


def test_fehlendes_netz_bricht_ab(monkeypatch):
    """Ohne das Netz faehrt die ganze Instanz nicht hoch -- also laut sein."""
    _patch(
        monkeypatch,
        {
            ("network", "inspect"): (1, "No such network"),
            ("network", "create"): (1, "permission denied"),
        },
    )
    with pytest.raises(SystemExit):
        mod.ensure()


def test_behaelter_fehler_stoppt_die_instanz_nicht(monkeypatch):
    """Fehlende Messwerte sind schlimm; eine Instanz, die nicht hochfaehrt,
    ist schlimmer."""
    _patch(
        monkeypatch,
        {
            ("network", "inspect"): (0, ""),
            ("inspect",): (1, "No such object"),
            ("run",): (125, "port is already allocated"),
        },
    )
    mod.ensure()  # darf nicht werfen


# ---------------------------------------------------------------------------
# Der Filter in der prometheus.yml: der gemeinsame cadvisor liefert die
# Container ALLER Instanzen, jede Instanz behaelt nur die eigenen.
# ---------------------------------------------------------------------------


def _after_compose():
    spec = importlib.util.spec_from_file_location(
        "dash_after_compose", AFTER_COMPOSE
    )
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _cadvisor_auftrag(daten):
    for auftrag in daten["scrape_configs"]:
        if auftrag["job_name"] == "cadvisor":
            return auftrag
    raise AssertionError("cadvisor-Auftrag fehlt")


def test_prometheus_behaelt_nur_die_eigenen_container(tmp_path):
    import yaml

    ac = _after_compose()
    datei = ac._rendern({"PROJECT_NAME": "kunde_prod"}, tmp_path)
    daten = yaml.safe_load(datei.read_text())

    auftrag = _cadvisor_auftrag(daten)
    assert auftrag["static_configs"][0]["targets"] == ["zodoo_cadvisor:8080"]
    filter_ = auftrag["metric_relabel_configs"][0]
    assert filter_ == {
        "source_labels": ["name"],
        "regex": "(kunde_prod.*)?",
        "action": "keep",
    }
    # Ohne remote_write-Einstellungen geht nichts nach draussen.
    assert "remote_write" not in daten


def test_ohne_projektnamen_wird_nicht_gefiltert(tmp_path):
    """Lieber zu viele Messwerte als ein Dashboard, das tot aussieht."""
    import yaml

    ac = _after_compose()
    datei = ac._rendern({}, tmp_path)
    daten = yaml.safe_load(datei.read_text())
    assert "metric_relabel_configs" not in _cadvisor_auftrag(daten)


def test_netzwerkname_als_rueckfall(tmp_path):
    import yaml

    ac = _after_compose()
    datei = ac._rendern({"NETWORK_NAME": "kunde_stage"}, tmp_path)
    daten = yaml.safe_load(datei.read_text())
    filter_ = _cadvisor_auftrag(daten)["metric_relabel_configs"][0]
    assert filter_["regex"] == "(kunde_stage.*)?"


def test_remote_write_bleibt_erhalten(tmp_path):
    import yaml

    ac = _after_compose()
    datei = ac._rendern(
        {
            "PROJECT_NAME": "kunde_prod",
            "DASHBOARD_REMOTE_WRITE_URL": "https://ablage/api/v1/write",
            "DASHBOARD_REMOTE_WRITE_INSTANZ": "maschine7",
            "DASHBOARD_REMOTE_WRITE_USER": "u",
            "DASHBOARD_REMOTE_WRITE_PASSWORD": "p",
        },
        tmp_path,
    )
    daten = yaml.safe_load(datei.read_text())
    assert daten["remote_write"][0]["url"] == "https://ablage/api/v1/write"
    assert daten["global"]["external_labels"]["instanz"] == "maschine7"
    assert _cadvisor_auftrag(daten)["metric_relabel_configs"]


def test_dashboard_compose_definiert_keinen_cadvisor_mehr():
    import yaml

    yml = yaml.safe_load(
        (REPO_ROOT / "dashboard" / "docker-compose.yml").read_text()
    )
    assert "cadvisor" not in yml["services"]
    assert yml["networks"]["zodoo_monitoring"]["external"] is True
    assert "zodoo_monitoring" in yml["services"]["prometheus"]["networks"]


def test_ohne_docker_passiert_nichts(monkeypatch):
    """Die CLI laeuft auch im Container -- dort gibt es kein docker."""
    fake = _patch(monkeypatch, {})
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    mod.ensure()
    assert fake.aufrufe == []


# ---------------------------------------------------------------------------
# alloy: jede Instanz schreibt nur noch ihre eigenen Container-Logs mit.
# ---------------------------------------------------------------------------


def _yml_mit_alloy():
    return {"services": {"alloy": {"image": "grafana/alloy"}}}


def _regex(yml):
    return yml["services"]["alloy"]["environment"][
        "DASHBOARD_LOGS_PROJECT_REGEX"
    ]


def test_alloy_bekommt_den_eigenen_projektnamen():
    ac = _after_compose()
    yml = _yml_mit_alloy()
    ac._alloy_projektfilter(
        yml, SimpleNamespace(project_name="kunde_prod"), {}
    )
    assert _regex(yml) == "kunde_prod"


def test_alloy_schalter_fuer_alle_container():
    ac = _after_compose()
    yml = _yml_mit_alloy()
    ac._alloy_projektfilter(
        yml,
        SimpleNamespace(project_name="kunde_prod"),
        {"DASHBOARD_LOGS_ALL_CONTAINERS": "1"},
    )
    assert _regex(yml) == ".*"


def test_alloy_ohne_projektnamen_filtert_nicht():
    """Ein zu enger Filter hiesse: keine Logs, und zwar lautlos."""
    ac = _after_compose()
    yml = _yml_mit_alloy()
    ac._alloy_projektfilter(yml, SimpleNamespace(project_name=None), {})
    assert _regex(yml) == ".*"


def test_alloy_projektname_wird_maskiert():
    """Projektnamen duerfen Punkte enthalten -- als Regex waeren das Joker."""
    ac = _after_compose()
    yml = _yml_mit_alloy()
    ac._alloy_projektfilter(
        yml, SimpleNamespace(project_name="zsync-ehem.-zync"), {}
    )
    assert _regex(yml) == re.escape("zsync-ehem.-zync")


def test_alloy_config_filtert_und_faellt_zurueck():
    """Die Regel muss die Ziele aussortieren (output), nicht nur umbenennen.

    Und ohne die Variable bleibt es beim alten Verhalten: die Datei liegt im
    gemeinsamen images-Verzeichnis und ist nach einem `git pull` sofort
    aktiv, die Compose-Datei einer Instanz erst nach `odoo reload`.
    """
    text = (REPO_ROOT / "dashboard" / "config" / "config.alloy").read_text()
    assert (
        'regex         = coalesce(sys.env("DASHBOARD_LOGS_PROJECT_REGEX"), ".*")'
        in text
    )
    assert "__meta_docker_container_label_com_docker_compose_project" in text
    assert "targets       = discovery.relabel.containers.output" in text
