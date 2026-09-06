"""Der Cronjob-Daemon der Instanzen (cronjobs/bin/run.py).

Anlass: am 04./05.09.2026 lief auf einer Instanz ZWEI NAECHTE lang kein
einziger Cronjob mehr - keine Sicherung, kein check, kein Offsite, kein Dump.
Im Protokoll stand nur "Execution took 0.04 seconds", weil os.system()
aufgerufen und sein Rueckgabewert weggeworfen wurde.

Ursache war eine Datei `inspect.py` im Projektverzeichnis: der Daemon macht
`cd /opt/src`, damit steht das Verzeichnis vorn in sys.path, und Pythons
`import inspect` erwischte den Schnipsel statt der Standardbibliothek.
"""
import importlib.machinery
import importlib.util
import logging
import os
import sys
from pathlib import Path

import pytest

RUN_PY = Path(__file__).resolve().parents[4] / "cronjobs" / "bin" / "run.py"


@pytest.fixture(scope="module")
def modul():
    """run.py laden, ohne croniter/arrow zu verlangen.

    Beides braucht nur der Zeitplaner. Wuerde der Test sie voraussetzen,
    wuerde er dort uebersprungen, wo keine Instanz-Abhaengigkeiten liegen -
    und ein uebersprungener Test bewacht nichts.
    """
    import types

    for name in ("croniter", "arrow"):
        if name not in sys.modules:
            ersatz = types.ModuleType(name)
            setattr(ersatz, name, object)
            sys.modules[name] = ersatz

    spec = importlib.util.spec_from_loader(
        "cronrun", importlib.machinery.SourceFileLoader("cronrun", str(RUN_PY))
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_gescheiterter_job_wird_protokolliert(modul, caplog):
    """Ein Cronjob, der scheitert, muss laut sein."""
    with caplog.at_level(logging.ERROR):
        code = modul._lauf("exit 3", "TESTJOB")
    assert code == 3
    assert any("TESTJOB" in r.message and "3" in r.message for r in caplog.records)


def test_gelungener_job_meldet_nichts(modul, caplog):
    with caplog.at_level(logging.ERROR):
        assert modul._lauf("true", "TESTJOB") == 0
    assert not caplog.records


def test_odoo_aufruf_haelt_das_projektverzeichnis_aus_sys_path(modul, monkeypatch):
    """Der Fall, der zwei Naechte gekostet hat.

    Ohne PYTHONSAFEPATH beschattet eine Datei im Projektverzeichnis das
    gleichnamige Standardmodul, und zodoo stirbt beim Start.
    """
    gesehen = []
    monkeypatch.setattr(modul, "_lauf", lambda cmd, name=None: gesehen.append(cmd) or 0)
    monkeypatch.setenv("PROJECT_NAME", "kunde")
    modul.execute("odoo pgbackrest backup --type full")
    assert len(gesehen) == 1
    befehl = gesehen[0]
    assert "PYTHONSAFEPATH=1" in befehl
    assert "-p kunde" in befehl
    assert "pgbackrest backup --type full" in befehl


def test_beschattung_wird_durch_safepath_verhindert(tmp_path):
    """Gegenprobe am echten Python, nicht am Kommentar."""
    (tmp_path / "inspect.py").write_text('raise RuntimeError("beschattet")\n')
    prog = "import inspect, sys; print('ok')"

    ohne = os.system(f"cd {tmp_path} && python3 -c {prog!r} >/dev/null 2>&1")
    mit = os.system(f"cd {tmp_path} && PYTHONSAFEPATH=1 python3 -c {prog!r} >/dev/null 2>&1")

    assert os.waitstatus_to_exitcode(ohne) != 0, "ohne SAFEPATH muesste es krachen"
    assert os.waitstatus_to_exitcode(mit) == 0, "mit SAFEPATH muss es laufen"
