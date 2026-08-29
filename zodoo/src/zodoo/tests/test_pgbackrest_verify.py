"""Tests der Rueckspielprobe (`odoo pgbackrest verify`).

Die Probe ist die einzige Pruefung, die etwas ueber den INHALT der Sicherungen
sagt. Entsprechend ist hier zweierlei wichtig, und das eine ist nicht das
offensichtliche:

* dass sie erkennt, wenn etwas nicht stimmt - und den richtigen Grund nennt,
* dass sie die PRODUKTION nicht anfasst. Eine Rueckspielprobe, die im Zweifel
  das Datenverzeichnis der laufenden Instanz ueberschreibt, waere schlimmer
  als gar keine Probe.
"""

import json
from unittest import mock

import pytest

from zodoo import lib_pgbackrest as lp


class FakeConfig:
    project_name = "kunde"
    pgbr_stanza = None
    HOST_RUN_DIR = "/tmp/run-kunde"


COMPOSE = {
    "services": {
        "pgbackrest": {
            "image": "kunde-pgbackrest",
            "volumes": [
                {"source": "kunde_odoo_postgres_volume", "target":
                 "/var/lib/postgresql/data", "type": "volume"},
                {"source": "kunde_pgbackrest_data", "target":
                 "/var/lib/pgbackrest", "type": "volume"},
            ],
        },
        "postgres": {
            "image": "kunde-postgres",
            "volumes": [
                {"source": "kunde_odoo_postgres_volume", "target":
                 "/var/lib/postgresql/data", "type": "volume"},
            ],
        },
    }
}


# Die kurze Schreibweise - so liefert es manche compose-Version.
COMPOSE_KURZ = {
    "services": {
        "pgbackrest": {
            "image": "kunde-pgbackrest",
            "volumes": [
                "odoo_postgres_volume:/var/lib/postgresql/data",
                "pgbackrest_data:/var/lib/pgbackrest",
            ],
        },
        "postgres": {"image": "kunde-postgres", "volumes": []},
    }
}


@pytest.fixture
def compose(monkeypatch):
    monkeypatch.setattr(lp, "_compose_config", lambda config: COMPOSE)
    monkeypatch.setattr(lp, "_verify_repo_is_local", lambda config: True)
    monkeypatch.setattr(lp, "_repo_volume_from_container", lambda config: None)
    return COMPOSE


# --------------------------------------------------------------------------- #
# Die Sicherheitseigenschaft                                                   #
# --------------------------------------------------------------------------- #


def test_the_live_data_volume_is_never_mounted(compose):
    """Das Datenvolume des Projekts darf in der Probe NICHT vorkommen.

    Nicht "wir schreiben da nichts hinein", sondern: es ist nicht erreichbar.
    Was nicht eingehaengt ist, kann auch ein Fehler in diesem Code nicht
    ueberschreiben.
    """
    mounts = lp._verify_mounts(FakeConfig())
    assert not any("odoo_postgres_volume" in m for m in mounts), mounts


def test_the_repository_is_mounted_read_only(compose):
    """Eine Probe hat im Bestand nichts zu schreiben."""
    mounts = lp._verify_mounts(FakeConfig())
    repo = [m for m in mounts if "/var/lib/pgbackrest" in m]
    assert repo, mounts
    for m in repo:
        assert m.endswith(":ro"), m


def test_the_projects_own_config_is_mounted(compose):
    """Repo-Adresse, Zertifikat und Passphrase kommen aus dem Projekt.

    Sonst muesste die Probe dieselben Angaben ein zweites Mal fuehren - und
    zwei Wahrheiten ueber dieselbe Sache laufen frueher oder spaeter
    auseinander.
    """
    mounts = lp._verify_mounts(FakeConfig())
    assert any(m.endswith("/pgbackrest:/etc/pgbackrest:ro") for m in mounts), mounts


def test_the_scratch_volume_lands_where_postgres_expects_its_data(compose):
    """Der Wegwerf-Pfad ist derselbe wie in der echten Instanz.

    Genau deshalb passt die Projektkonfiguration unveraendert: pg1-path zeigt
    auf einen Pfad IM Container, und darunter liegt hier ein anderes Volume.
    """
    assert lp.VERIFY_PGDATA == "/var/lib/postgresql/data/pgdata"


# --------------------------------------------------------------------------- #
# leer oder unlesbar - der Unterschied, der die Suche lenkt                    #
# --------------------------------------------------------------------------- #


def _info(monkeypatch, payload):
    monkeypatch.setattr(
        lp, "_docker",
        lambda *a, **kw: mock.Mock(stdout=json.dumps(payload), returncode=0),
    )


def test_an_unreadable_repository_is_not_reported_as_empty(monkeypatch):
    """Falsche Passphrase sieht aus wie "keine Sicherung" - ist es aber nicht.

    pgbackrest kann das Manifest nicht entschluesseln und meldet null
    Sicherungen. Wer das "noch nie gesichert" nennt, schickt den Suchenden zur
    Instanz, obwohl der Fehler beim Schluessel liegt.
    """
    _info(monkeypatch, [{"status": {"code": 99, "message": "other"},
                         "backup": []}])
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._verify_latest_backup(FakeConfig(), "kunde", "img", [])
    assert "nicht lesbar" in str(ex.value)
    assert "Passphrase" in str(ex.value)


def test_a_genuinely_empty_stanza_says_so(monkeypatch):
    _info(monkeypatch, [{"status": {"code": 2, "message": "no valid backups"},
                         "backup": []}])
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._verify_latest_backup(FakeConfig(), "kunde", "img", [])
    assert "nie gesichert" in str(ex.value)


def test_an_unknown_stanza_says_so(monkeypatch):
    _info(monkeypatch, [])
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._verify_latest_backup(FakeConfig(), "kunde", "img", [])
    assert "kennt die Stanza" in str(ex.value)


def test_the_newest_backup_is_the_one_that_gets_tested(monkeypatch):
    """Die juengste, nicht irgendeine - sonst prueft man alte Bestaende."""
    _info(monkeypatch, [{
        "status": {"code": 0},
        "backup": [{"label": "alt"}, {"label": "mittel"}, {"label": "neu"}],
    }])
    assert lp._verify_latest_backup(
        FakeConfig(), "kunde", "img", []
    ) == "neu"


# --------------------------------------------------------------------------- #
# Mindestwerte aus pg_control                                                  #
# --------------------------------------------------------------------------- #


PG_CONTROL = """
pg_control version number:            1300
Database cluster state:               shut down in recovery
Current max_connections setting:      2000
Current max_worker_processes setting: 8
Current max_wal_senders setting:      10
Current max_prepared_xacts setting:   0
Current max_locks_per_xact setting:   64
Maximum data alignment:               8
"""


def test_the_source_settings_are_read_not_guessed(monkeypatch):
    """Diese Werte stehen NICHT in der zurueckgespielten postgresql.conf.

    zodoo reicht sie als Startparameter (-c) an Postgres; in pg_control stehen
    sie aber immer. Ohne sie bricht die Wiederherstellung ab mit
    "recovery aborted because of insufficient parameter settings".
    """
    monkeypatch.setattr(
        lp, "_docker", lambda *a, **kw: mock.Mock(stdout=PG_CONTROL, returncode=0)
    )
    werte = lp._verify_minimums("img", "vol", [])
    assert werte["max_connections"] == "2000"
    assert werte["max_worker_processes"] == "8"
    assert werte["max_locks_per_transaction"] == "64"
    # Nichts Fremdes einsammeln - "Maximum data alignment" ist kein Parameter.
    assert set(werte) == set(lp.VERIFY_MINIMUMS.values())


def test_unreadable_pg_control_yields_no_settings(monkeypatch):
    monkeypatch.setattr(
        lp, "_docker", lambda *a, **kw: mock.Mock(stdout="", returncode=1)
    )
    assert lp._verify_minimums("img", "vol", []) == {}


# --------------------------------------------------------------------------- #
# Die Frage geht an Nutzdaten                                                  #
# --------------------------------------------------------------------------- #


def test_a_cluster_without_user_tables_does_not_pass(monkeypatch):
    """Lesbar, aber leer, ist kein bestandener Nachweis.

    Sonst wuerde eine versehentlich leere Sicherung als "geprueft" gelten -
    genau der Fall, den diese Probe finden soll.
    """
    antworten = ["meinedb", ""]
    monkeypatch.setattr(
        lp, "_verify_query",
        lambda *a, **kw: mock.Mock(stdout=antworten.pop(0), returncode=0),
    )
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._verify_read_user_data("c")
    assert "keine einzige Nutztabelle" in str(ex.value)


def test_a_read_error_on_user_data_fails_the_probe(monkeypatch):
    """Hochgefahren ist nicht bestanden - es muss auch lesbar sein."""
    antworten = [
        mock.Mock(stdout="meinedb", returncode=0),
        mock.Mock(stdout="public.grosse_tabelle", returncode=0),
        mock.Mock(stdout="", stderr="invalid page in block 42", returncode=1),
    ]
    monkeypatch.setattr(lp, "_verify_query", lambda *a, **kw: antworten.pop(0))
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._verify_read_user_data("c")
    assert "invalid page" in str(ex.value)


def test_the_largest_user_table_is_the_one_read(monkeypatch):
    antworten = [
        mock.Mock(stdout="meinedb", returncode=0),
        mock.Mock(stdout="public.grosse_tabelle", returncode=0),
        mock.Mock(stdout="70000", returncode=0),
    ]
    monkeypatch.setattr(lp, "_verify_query", lambda *a, **kw: antworten.pop(0))
    assert lp._verify_read_user_data("c") == {
        "database": "meinedb",
        "table": "public.grosse_tabelle",
        "rows": 70000,
    }


# --------------------------------------------------------------------------- #
# Das Ergebnis                                                                 #
# --------------------------------------------------------------------------- #


def test_a_failure_is_reported_not_raised(monkeypatch, compose):
    """Ein Fehlschlag ist ein ERGEBNIS, kein Absturz.

    Der Prueflauf soll auch dann eine Datei hinterlassen, wenn es schiefging -
    sonst sieht die Ueberwachung "keine Probe gelaufen" statt "Probe
    gescheitert", und das sind sehr verschiedene Nachrichten.
    """
    monkeypatch.setattr(
        lp, "_verify_images",
        mock.Mock(side_effect=lp.VerifyFailed("kein pgbackrest im Projekt")),
    )
    monkeypatch.setattr(lp, "_verify_cleanup", lambda *a: None)
    erg = lp.run_verify(FakeConfig())
    assert erg["result"] == "failed"
    assert "kein pgbackrest" in erg["error"]
    assert erg["area"] == "kunde"
    assert "seconds" in erg and "checked_at" in erg


def test_cleanup_runs_even_when_the_probe_blows_up(monkeypatch, compose):
    """Kein Wegwerf-Volume darf liegenbleiben - sonst laeuft die Platte voll."""
    aufgeraeumt = []
    monkeypatch.setattr(
        lp, "_verify_images", mock.Mock(side_effect=RuntimeError("boom"))
    )
    monkeypatch.setattr(
        lp, "_verify_cleanup", lambda c, v: aufgeraeumt.append((c, v))
    )
    erg = lp.run_verify(FakeConfig())
    assert erg["result"] == "failed"
    assert "boom" in erg["error"]
    assert len(aufgeraeumt) == 1


def test_the_stanza_can_be_overridden(monkeypatch, compose):
    """Der Pruefstand prueft fremde Bereiche, nicht seinen eigenen."""
    monkeypatch.setattr(
        lp, "_verify_images", mock.Mock(side_effect=lp.VerifyFailed("x"))
    )
    monkeypatch.setattr(lp, "_verify_cleanup", lambda *a: None)
    assert lp.run_verify(FakeConfig(), stanza="fremder-kunde")["area"] == (
        "fremder-kunde"
    )


# --------------------------------------------------------------------------- #
# Abbilder                                                                     #
# --------------------------------------------------------------------------- #


def test_explicit_image_names_are_used(compose):
    assert lp._verify_images(FakeConfig()) == (
        "kunde-pgbackrest",
        "kunde-postgres",
    )


def test_built_services_fall_back_to_composes_own_naming(monkeypatch):
    """Gebaute Dienste haben in `compose config` kein `image`.

    Ohne diesen Rueckfall landet ein None in der docker-Zeile und der Fehler
    zeigt sich erst tief in subprocess - weit weg von der Ursache.
    """
    monkeypatch.setattr(
        lp, "_compose_config",
        lambda config: {"services": {"pgbackrest": {"build": {}},
                                     "postgres": {"build": {}}}},
    )
    assert lp._verify_images(FakeConfig()) == (
        "kunde-pgbackrest",
        "kunde-postgres",
    )


def test_a_project_without_the_services_says_which_are_missing(monkeypatch):
    monkeypatch.setattr(
        lp, "_compose_config", lambda config: {"services": {"postgres": {}}}
    )
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._verify_images(FakeConfig())
    assert "pgbackrest" in str(ex.value)


# --------------------------------------------------------------------------- #
# Die beiden Schreibweisen von compose                                         #
# --------------------------------------------------------------------------- #


def test_the_short_volume_notation_is_understood_too(monkeypatch):
    """`compose config` liefert je nach Version Abbildung oder "quelle:ziel".

    Wer nur eine Form kennt, findet auf der anderen Maschine das Repository
    nicht - und pgbackrest meldet dann "missing stanza path", was nach einem
    kaputten Bestand aussieht statt nach einer fehlenden Einhaengung.
    """
    monkeypatch.setattr(lp, "_compose_config", lambda config: COMPOSE_KURZ)
    monkeypatch.setattr(lp, "_verify_repo_is_local", lambda config: True)
    monkeypatch.setattr(lp, "_repo_volume_from_container", lambda config: None)
    mounts = lp._verify_mounts(FakeConfig())
    assert any(m == "kunde_pgbackrest_data:/var/lib/pgbackrest:ro"
               for m in mounts), mounts
    assert not any("odoo_postgres_volume" in m for m in mounts), mounts


def test_a_local_repository_without_its_volume_fails_clearly(monkeypatch):
    """Fehlende Einhaengung wird benannt, statt sie pgbackrest melden zu lassen."""
    monkeypatch.setattr(
        lp, "_compose_config",
        lambda config: {"services": {"pgbackrest": {"volumes": []}}},
    )
    monkeypatch.setattr(lp, "_verify_repo_is_local", lambda config: True)
    monkeypatch.setattr(lp, "_repo_volume_from_container", lambda config: None)
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._verify_mounts(FakeConfig())
    assert "Volume" in str(ex.value)


def test_a_remote_repository_needs_no_volume(monkeypatch):
    """Liegt der Bestand auf dem Backup-Server, gibt es hier nichts einzuhaengen."""
    monkeypatch.setattr(
        lp, "_compose_config",
        lambda config: {"services": {"pgbackrest": {"volumes": []}}},
    )
    monkeypatch.setattr(lp, "_verify_repo_is_local", lambda config: False)
    monkeypatch.setattr(lp, "_repo_volume_from_container", lambda config: None)
    assert lp._verify_mounts(FakeConfig()) == [
        "/tmp/run-kunde/pgbackrest:/etc/pgbackrest:ro"
    ]


def test_a_missing_stanza_is_not_called_unreadable(monkeypatch):
    """Status 1 heisst: Bestand da, dieser Bereich nicht. Andere Suche."""
    _info(monkeypatch, [{"status": {"code": 1, "message": "missing stanza path"},
                         "backup": []}])
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._verify_latest_backup(FakeConfig(), "kunde", "img", [])
    assert "keinen Bereich" in str(ex.value)
    assert "Passphrase" not in str(ex.value)


def test_the_local_repo_detection_reads_the_projects_config(tmp_path):
    """repo1-path = hier, repo1-host = anderswo."""
    class C:
        project_name = "kunde"
        pgbr_stanza = None
        HOST_RUN_DIR = str(tmp_path)

    d = tmp_path / "pgbackrest"
    d.mkdir()
    conf = d / "pgbackrest.conf"

    conf.write_text("[global]\nrepo1-path=/var/lib/pgbackrest\n")
    assert lp._verify_repo_is_local(C()) is True

    conf.write_text("[global]\nrepo1-host=db.backup.zebroo.de\n")
    assert lp._verify_repo_is_local(C()) is False


# --------------------------------------------------------------------------- #
# Der wirkliche Name des Repository-Volumes                                    #
# --------------------------------------------------------------------------- #


def test_a_named_volume_gets_the_project_prefix(monkeypatch):
    """compose nennt 'pgbackrest_data', angelegt wird 'kunde_pgbackrest_data'.

    Der kurze Name an `docker run` gibt KEINEN Fehler - er erzeugt ein frisches
    leeres Volume. Die Probe meldet dann 'missing stanza path', als waere der
    Bestand kaputt. Genau diese falsche Faehrte verhindert dieser Test.
    """
    monkeypatch.setattr(lp, "_repo_volume_from_container", lambda config: None)
    sidecar = {"volumes": [{"source": "pgbackrest_data",
                            "target": "/var/lib/pgbackrest"}]}
    assert lp._repo_volume(FakeConfig(), sidecar) == "kunde_pgbackrest_data"


def test_a_path_mount_is_used_unchanged(monkeypatch):
    """Ein Pfad aus dem Dateisystem bekommt kein Projekt davor."""
    monkeypatch.setattr(lp, "_repo_volume_from_container", lambda config: None)
    sidecar = {"volumes": [{"source": "/srv/repo",
                            "target": "/var/lib/pgbackrest"}]}
    assert lp._repo_volume(FakeConfig(), sidecar) == "/srv/repo"


def test_the_running_container_wins_over_the_derived_name(monkeypatch):
    """Was tatsaechlich eingehaengt ist, schlaegt jede Herleitung."""
    monkeypatch.setattr(
        lp, "_repo_volume_from_container", lambda config: "ganz_anders"
    )
    sidecar = {"volumes": [{"source": "pgbackrest_data",
                            "target": "/var/lib/pgbackrest"}]}
    assert lp._repo_volume(FakeConfig(), sidecar) == "ganz_anders"


def test_an_already_prefixed_name_is_not_prefixed_twice(monkeypatch):
    """Manche compose-Version nennt den Namen schon mit Projekt.

    Zweimal davor waere ein Volume, das es nicht gibt - und das faellt wieder
    nur als "leerer Bestand" auf, also als falsche Faehrte.
    """
    monkeypatch.setattr(lp, "_repo_volume_from_container", lambda config: None)
    sidecar = {"volumes": [{"source": "kunde_pgbackrest_data",
                            "target": "/var/lib/pgbackrest"}]}
    assert lp._repo_volume(FakeConfig(), sidecar) == "kunde_pgbackrest_data"
