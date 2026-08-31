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
    """Kein Wegwerf-Volume darf liegenbleiben - sonst laeuft die Platte voll.

    Geprueft wird der Fall, in dem waehrend der Probe etwas explodiert,
    NACHDEM Container und Volume angelegt wurden. Scheitert schon das
    Zusammenstellen der Umgebung, gibt es nichts aufzuraeumen - dann darf und
    soll nichts passieren.
    """
    aufgeraeumt = []
    monkeypatch.setattr(
        lp, "_verify_latest_backup", mock.Mock(side_effect=RuntimeError("boom"))
    )
    monkeypatch.setattr(
        lp, "_verify_cleanup", lambda c, v: aufgeraeumt.append((c, v))
    )
    erg = lp.run_verify(FakeConfig())
    assert erg["result"] == "failed"
    assert "boom" in erg["error"]
    assert len(aufgeraeumt) == 1
    container, volume = aufgeraeumt[0]
    assert container.startswith("verify-")
    assert volume.startswith("verify_")


def test_nothing_is_cleaned_up_when_nothing_was_created(monkeypatch, compose):
    """Scheitert schon die Umgebung, wird kein Aufraeumen vorgetaeuscht."""
    aufgeraeumt = []
    monkeypatch.setattr(
        lp, "_verify_images",
        mock.Mock(side_effect=lp.VerifyFailed("kein pgbackrest im Projekt")),
    )
    monkeypatch.setattr(
        lp, "_verify_cleanup", lambda c, v: aufgeraeumt.append((c, v))
    )
    erg = lp.run_verify(FakeConfig())
    assert erg["result"] == "failed"
    assert "kein pgbackrest" in erg["error"]
    assert aufgeraeumt == []


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


# --------------------------------------------------------------------------- #
# Der Pruefstand: dieselbe Probe, fremde Bereiche                              #
# --------------------------------------------------------------------------- #


BENCH = {
    "repo_host": "db.backup.zebroo.de",
    "repo_port": 443,
    "cipher_type": "aes-256-cbc",
    "cipher_pass": "geheim",
    "cert_dir": "/etc/pgbr-pruefstand/cert",
    "pgbackrest_image": "pgbr-pruefstand:2.59.1",
    "bench": "pgbr-pruefstand",
    "stanzas": {"kunde-a": {}, "kunde-b": {"cipher_pass": "anders"}},
}


def test_the_bench_config_reaches_the_repository_over_tls():
    text = lp.bench_conf_text(BENCH, "kunde-a")
    assert "repo1-host=db.backup.zebroo.de" in text
    assert "repo1-host-type=tls" in text
    assert "repo1-host-port=443" in text
    assert "repo1-cipher-pass=geheim" in text


def test_the_bench_restores_to_the_same_path_as_a_real_instance():
    """Derselbe Pfad wie in der echten Instanz - daran haengt archive-get.

    Zeigte pg1-path woandershin als dorthin, wo Postgres seine Daten sieht,
    scheitert jedes Nachladen von WAL waehrend der Wiederherstellung.
    """
    text = lp.bench_conf_text(BENCH, "kunde-a")
    assert f"pg1-path={lp.VERIFY_PGDATA}" in text
    assert "[kunde-a]" in text


def test_the_bench_writes_no_repo_path():
    """Der Bestand liegt anderswo - ein repo1-path waere schlicht falsch."""
    text = lp.bench_conf_text(BENCH, "kunde-a")
    assert "repo1-path" not in text


def test_a_stanza_can_carry_its_own_passphrase(monkeypatch, tmp_path):
    """Jeder Kunde hat eine eigene Passphrase - eine gemeinsame gibt es nicht."""
    gesehen = {}
    monkeypatch.setattr(
        lp, "_probe", lambda umgebung, stanza: {"result": "passed"}
    )
    monkeypatch.setattr(
        lp, "_bench_umgebung",
        lambda bench, stanza, ordner: gesehen.setdefault(stanza, bench) and {},
    )
    for b in ("kunde-a", "kunde-b"):
        lp.run_verify_bench(BENCH, b)
    assert gesehen["kunde-a"]["cipher_pass"] == "geheim"
    assert gesehen["kunde-b"]["cipher_pass"] == "anders"


def test_the_bench_config_must_be_complete(tmp_path):
    """Fehlt etwas, wird es benannt - nicht erst von pgbackrest gemeldet."""
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._bench_umgebung({"repo_host": "x"}, "kunde-a", str(tmp_path))
    assert "cert_dir" in str(ex.value)
    assert "pgbackrest_image" in str(ex.value)


def test_a_missing_certificate_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    bench = dict(BENCH, cert_dir=str(tmp_path / "gibtsnicht"))
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._bench_umgebung(bench, "kunde-a", str(tmp_path))
    assert "Zertifikat" in str(ex.value)


def test_the_bench_environment_carries_the_user_and_one_image(tmp_path,
                                                              monkeypatch):
    """Ein Abbild fuer beide Rollen, und ein Benutzer statt gosu.

    Im Pruefstand-Abbild (auf postgres:17 aufgesetzt) gibt es kein gosu - die
    Kennung wird direkt gesetzt, und sie ist dieselbe wie die von postgres.
    """
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    cert = tmp_path / "cert"
    cert.mkdir()
    for f in ("ca.crt", "client.crt", "client.key"):
        (cert / f).write_text("x")
    bench = dict(BENCH, cert_dir=str(cert))
    arbeit = tmp_path / "arbeit"
    arbeit.mkdir()

    u = lp._bench_umgebung(bench, "kunde-a", str(arbeit))
    assert u["run_user"] == "999:999"
    assert u["pgbackrest_image"] == u["postgres_image"] == "pgbr-pruefstand:2.59.1"
    assert u["mounts"] == [f"{arbeit}:/etc/pgbackrest:ro"]
    assert u["bench"] == "pgbr-pruefstand"
    # Die Passphrase steht in der Datei - sie darf nicht fuer alle lesbar sein.
    import stat
    modus = stat.S_IMODE((arbeit / "pgbackrest.conf").stat().st_mode)
    assert modus == 0o600, oct(modus)


def test_the_bench_never_mounts_a_data_volume(tmp_path, monkeypatch):
    """Der Pruefstand kennt keine laufende Instanz - und haengt auch keine ein."""
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    cert = tmp_path / "cert"
    cert.mkdir()
    for f in ("ca.crt", "client.crt", "client.key"):
        (cert / f).write_text("x")
    arbeit = tmp_path / "arbeit2"
    arbeit.mkdir()
    u = lp._bench_umgebung(dict(BENCH, cert_dir=str(cert)), "kunde-a",
                           str(arbeit))
    assert not any("postgresql/data" in m for m in u["mounts"]), u["mounts"]


# --------------------------------------------------------------------------- #
# Ein Ablauf, zwei Herkuenfte                                                  #
# --------------------------------------------------------------------------- #


def test_both_paths_run_the_very_same_probe(monkeypatch, compose, tmp_path):
    """Projekt und Pruefstand muessen DASSELBE tun.

    Zwei Umsetzungen derselben Sache laufen frueher oder spaeter auseinander -
    und dann prueft der Pruefstand etwas anderes als das, was getestet wurde.
    """
    gerufen = []
    monkeypatch.setattr(
        lp, "_probe",
        lambda umgebung, stanza: gerufen.append((umgebung, stanza)) or
        {"result": "passed"},
    )
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    cert = tmp_path / "cert"
    cert.mkdir()
    for f in ("ca.crt", "client.crt", "client.key"):
        (cert / f).write_text("x")

    lp.run_verify(FakeConfig())
    lp.run_verify_bench(dict(BENCH, cert_dir=str(cert)), "kunde-a")

    assert len(gerufen) == 2
    # Beide liefern dieselbe Art Umgebung - nur eben aus anderer Quelle.
    for umgebung, _ in gerufen:
        assert set(umgebung) >= {
            "pgbackrest_image", "postgres_image", "mounts", "run_user", "bench"
        }


def test_the_non_root_invocation_differs_per_image():
    """Projektabbild kennt gosu, Pruefstand-Abbild setzt die Kennung."""
    mit_gosu = lp._pgbr_als_benutzer("bild", None)
    assert "gosu" in " ".join(mit_gosu)
    assert "--user" not in mit_gosu

    mit_user = lp._pgbr_als_benutzer("bild", "999:999")
    assert mit_user[:2] == ["--user", "999:999"]
    assert "gosu" not in " ".join(mit_user)


# --------------------------------------------------------------------------- #
# Umschlaege: Passphrase UND Zertifikat kommen vom Anmeldedienst              #
# --------------------------------------------------------------------------- #


UMSCHLAG = {
    "area": "kunde-a",
    "stanza": "kunde-a",
    "repo_host": "db.backup.zebroo.de",
    "repo_port": 443,
    "cipher_type": "aes-256-cbc",
    "cipher_pass": "aus-dem-umschlag",
    "client_cert": "-----BEGIN CERTIFICATE-----\nkunde-a\n-----END CERTIFICATE-----\n",
    "client_key": "-----BEGIN PRIVATE KEY-----\nkunde-a\n-----END PRIVATE KEY-----\n",
}


def _umschlag_ordner(tmp_path, *namen):
    d = tmp_path / "umschlaege"
    d.mkdir(exist_ok=True)
    for n in namen:
        (d / n).write_text("age-chiffrat")
    return str(d)


def test_the_newest_envelope_wins(tmp_path):
    """Eine zweite Freigabe legt eine zweite Datei an, statt zu ueberschreiben.

    Es gilt der juengste Umschlag - er traegt die Zugangsdaten, die zuletzt
    ausgegeben wurden. Der aelteste wuerde ein abgeloestes Zertifikat liefern.
    """
    d = _umschlag_ordner(
        tmp_path,
        "kunde-a-20260101T000000Z.age",
        "kunde-a-20260815T000000Z.age",
        "kunde-b-20260901T000000Z.age",
    )
    assert lp.neuester_umschlag(d, "kunde-a").endswith(
        "kunde-a-20260815T000000Z.age"
    )


def test_areas_are_derived_from_the_envelopes(tmp_path):
    """Neue Kunden muessen nicht von Hand nachgetragen werden.

    Was nachgetragen werden muss, wird irgendwann vergessen - und ein Bereich,
    den niemand prueft, faellt nicht auf.
    """
    d = _umschlag_ordner(
        tmp_path, "kunde-a-20260101T000000Z.age", "kunde-b-20260101T000000Z.age"
    )
    assert lp.umschlag_bereiche(d) == ["kunde-a", "kunde-b"]


def test_no_envelope_directory_is_not_an_error(tmp_path):
    assert lp.umschlag_bereiche(None) == []
    assert lp.neuester_umschlag(str(tmp_path / "weg"), "kunde-a") is None


def test_the_envelope_supplies_passphrase_and_certificate(monkeypatch,
                                                          tmp_path):
    """Der eigentliche Gewinn: das Zertifikat des KUNDEN kommt mit.

    Damit braucht der Pruefstand kein eigenes, das auf alle Bereiche
    berechtigt waere - pgBackRest kennt kein Nur-Lese-Zertifikat, ein
    Sammelzertifikat duerfte also ueberall auch schreiben.
    """
    d = _umschlag_ordner(tmp_path, "kunde-a-20260101T000000Z.age")
    monkeypatch.setattr(lp, "umschlag_oeffnen", lambda i, p: UMSCHLAG)
    ergaenzt = lp._aus_umschlag(
        {"envelope_dir": d, "age_identity": "/etc/age.key"}, "kunde-a"
    )
    assert ergaenzt["cipher_pass"] == "aus-dem-umschlag"
    assert "kunde-a" in ergaenzt["client_cert"]
    assert "kunde-a" in ergaenzt["client_key"]
    assert ergaenzt["repo_host"] == "db.backup.zebroo.de"
    assert ergaenzt["umschlag"] == "kunde-a-20260101T000000Z.age"


def test_explicit_configuration_beats_the_envelope(monkeypatch, tmp_path):
    """Ein Wert von Hand laesst sich uebersteuern, ohne den Umschlag anzufassen."""
    d = _umschlag_ordner(tmp_path, "kunde-a-20260101T000000Z.age")
    monkeypatch.setattr(lp, "umschlag_oeffnen", lambda i, p: UMSCHLAG)
    ergaenzt = lp._aus_umschlag(
        {"envelope_dir": d, "age_identity": "/k", "cipher_pass": "von-hand"},
        "kunde-a",
    )
    assert ergaenzt["cipher_pass"] == "von-hand"


def test_a_missing_age_key_is_named_plainly(tmp_path):
    """Ohne privaten Schluessel geht es nicht - und das soll dastehen."""
    d = _umschlag_ordner(tmp_path, "kunde-a-20260101T000000Z.age")
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._aus_umschlag({"envelope_dir": d}, "kunde-a")
    assert "age_identity" in str(ex.value)

    with pytest.raises(lp.VerifyFailed) as ex:
        lp._aus_umschlag(
            {"envelope_dir": d, "age_identity": str(tmp_path / "weg.key")},
            "kunde-a",
        )
    assert "nicht da" in str(ex.value)


def test_an_unopenable_envelope_says_so(monkeypatch, tmp_path):
    """Falscher Schluessel ist etwas anderes als ein kaputtes Backup."""
    d = _umschlag_ordner(tmp_path, "kunde-a-20260101T000000Z.age")
    identity = tmp_path / "age.key"
    identity.write_text("x")
    monkeypatch.setattr(
        lp.subprocess, "run",
        lambda *a, **kw: mock.Mock(returncode=1, stderr="no identity matched",
                                   stdout=""),
    )
    with pytest.raises(lp.VerifyFailed) as ex:
        lp.umschlag_oeffnen(str(identity), str(tmp_path / "u.age"))
    assert "nicht oeffnen" in str(ex.value)
    assert "no identity matched" in str(ex.value)


def test_the_certificate_from_the_envelope_is_written_not_copied(monkeypatch,
                                                                 tmp_path):
    """Aus dem Umschlag kommt Text, kein Pfad - er wird abgelegt, nicht kopiert."""
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    arbeit = tmp_path / "arbeit"
    arbeit.mkdir()
    bench = {
        "repo_host": "db.backup.zebroo.de",
        "pgbackrest_image": "pgbr-pruefstand:2.59.1",
        "client_cert": UMSCHLAG["client_cert"],
        "client_key": UMSCHLAG["client_key"],
        "cipher_pass": "x",
        # ca.crt kommt weiter aus dem Ordner - sie ist fuer alle dieselbe.
        "cert_dir": str(tmp_path / "cert"),
    }
    (tmp_path / "cert").mkdir()
    (tmp_path / "cert" / "ca.crt").write_text("CA")

    lp._bench_umgebung(bench, "kunde-a", str(arbeit))
    assert "kunde-a" in (arbeit / "cert" / "client.crt").read_text()
    assert "kunde-a" in (arbeit / "cert" / "client.key").read_text()
    assert (arbeit / "cert" / "ca.crt").read_text() == "CA"


def test_the_private_age_key_is_never_mounted(monkeypatch, tmp_path):
    """Der Schluessel oeffnet JEDEN Umschlag - er hat im Container nichts zu suchen.

    Geoeffnet wird auf der Maschine, hinein geht nur das Ergebnis.
    """
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    arbeit = tmp_path / "arbeit2"
    arbeit.mkdir()
    (tmp_path / "cert").mkdir(exist_ok=True)
    (tmp_path / "cert" / "ca.crt").write_text("CA")
    bench = {
        "repo_host": "h", "pgbackrest_image": "b",
        "age_identity": "/etc/pgbr-pruefstand/age.key",
        "client_cert": "c", "client_key": "k", "cipher_pass": "x",
        "cert_dir": str(tmp_path / "cert"),
    }
    u = lp._bench_umgebung(bench, "kunde-a", str(arbeit))
    assert not any(bench["age_identity"] in m for m in u["mounts"]), u["mounts"]
    # Und auch sonst nichts aus /etc/pgbr-pruefstand - dort liegt der
    # Schluessel, und eingehaengt wird nur der Wegwerf-Ordner.
    assert all(m.startswith(str(arbeit)) for m in u["mounts"]), u["mounts"]


# --------------------------------------------------------------------------- #
# Zweite Bestandsart: Objektspeicher (S3 / MinIO)                              #
# --------------------------------------------------------------------------- #


BENCH_S3 = {
    "repo_type": "s3",
    "s3_endpoint": "192.168.77.44:9000",
    "s3_bucket": "pgbackrest",
    "s3_key": "pgbackrest",
    "s3_key_secret": "geheim",
    "pgbackrest_image": "pgbr-pruefstand:2.59.1",
    "cipher_pass": "passphrase",
    "bench": "pgbr-pruefstand",
}


def test_the_s3_form_addresses_the_bucket_by_path():
    """MinIO adressiert Buckets ueber den Pfad, nicht ueber den Hostnamen.

    Mit der Vorgabe 'host' laeuft jede Anfrage gegen einen Namen, den es im
    DNS nicht gibt - und der Fehler sieht aus wie ein Netzproblem.
    """
    text = lp.bench_conf_text(BENCH_S3, "kunde-a")
    assert "repo1-type=s3" in text
    assert "repo1-s3-uri-style=path" in text
    assert "repo1-s3-bucket=pgbackrest" in text
    assert "repo1-s3-endpoint=192.168.77.44:9000" in text


def test_the_s3_form_has_no_repo_host():
    """Ein Objektspeicher ist kein Repo-Host - beides zugleich waere Unsinn."""
    text = lp.bench_conf_text(BENCH_S3, "kunde-a")
    assert "repo1-host=" not in text
    assert "repo1-host-cert-file" not in text


def test_the_tls_form_has_no_s3_options():
    text = lp.bench_conf_text(BENCH, "kunde-a")
    assert "repo1-type=s3" not in text
    assert "repo1-host=db.backup.zebroo.de" in text


def test_the_storage_certificate_is_verified_not_trusted_blindly():
    """Sonst koennte sich zwischen Pruefstand und Bestand jemand setzen.

    Und die Probe wuerde ihn bestaetigen - eine Rueckspielprobe, die auf einen
    untergeschobenen Bestand hereinfaellt, ist schlimmer als keine.
    """
    text = lp.bench_conf_text(
        dict(BENCH_S3, storage_ca_file="/etc/pgbr-pruefstand/minio-ca.crt"),
        "kunde-a",
    )
    assert "repo1-storage-verify-tls=y" in text
    assert "repo1-storage-ca-file=/etc/pgbackrest/cert/storage-ca.crt" in text


def test_the_encryption_stays_ours_on_s3_too():
    """Der Speicher sieht Chiffrat - egal ob eigener MinIO oder fremder Anbieter."""
    text = lp.bench_conf_text(BENCH_S3, "kunde-a")
    assert "repo1-cipher-pass=passphrase" in text


def test_an_incomplete_s3_config_names_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    arbeit = tmp_path / "a"
    arbeit.mkdir()
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._bench_umgebung(
            {"repo_type": "s3", "s3_endpoint": "x"}, "kunde-a", str(arbeit)
        )
    fehlt = str(ex.value)
    assert "s3_bucket" in fehlt and "s3_key" in fehlt
    # Ein Zertifikatsordner ist bei S3 gerade NICHT noetig - er darf hier auch
    # nicht angemahnt werden, sonst sucht man an der falschen Stelle.
    assert "cert_dir" not in fehlt


def test_s3_needs_no_client_certificate(tmp_path, monkeypatch):
    """Ein Objektspeicher weist uns ueber ein Schluesselpaar aus."""
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    arbeit = tmp_path / "b"
    arbeit.mkdir()
    u = lp._bench_umgebung(BENCH_S3, "kunde-a", str(arbeit))
    assert u["mounts"] == [f"{arbeit}:/etc/pgbackrest:ro"]
    assert not (arbeit / "cert" / "client.crt").exists()


def test_the_storage_ca_is_copied_into_the_throwaway_folder(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    ca = tmp_path / "minio-ca.crt"
    ca.write_text("CA-INHALT")
    arbeit = tmp_path / "c"
    arbeit.mkdir()
    lp._bench_umgebung(
        dict(BENCH_S3, storage_ca_file=str(ca)), "kunde-a", str(arbeit)
    )
    assert (arbeit / "cert" / "storage-ca.crt").read_text() == "CA-INHALT"


def test_a_missing_storage_ca_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    arbeit = tmp_path / "d"
    arbeit.mkdir()
    with pytest.raises(lp.VerifyFailed) as ex:
        lp._bench_umgebung(
            dict(BENCH_S3, storage_ca_file=str(tmp_path / "weg.crt")),
            "kunde-a", str(arbeit),
        )
    assert "Speicher-CA" in str(ex.value)


def test_both_repository_kinds_produce_the_same_shape_of_environment(
    tmp_path, monkeypatch
):
    """Danach ist der Ablauf identisch - nur die Herkunft unterscheidet sich."""
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    cert = tmp_path / "cert"
    cert.mkdir()
    for f in ("ca.crt", "client.crt", "client.key"):
        (cert / f).write_text("x")
    a, b = tmp_path / "ea", tmp_path / "eb"
    a.mkdir(); b.mkdir()

    tls = lp._bench_umgebung(dict(BENCH, cert_dir=str(cert)), "k", str(a))
    s3 = lp._bench_umgebung(BENCH_S3, "k", str(b))
    assert set(tls) == set(s3)


def test_the_working_folder_belongs_to_the_container_user_in_both_shapes(
    tmp_path, monkeypatch
):
    """Der Ordner kommt von mkdtemp und gehoert root mit 0700.

    Wird er nicht uebertragen, kann der Container die Konfiguration nicht
    lesen - "Permission denied" auf die eigene pgbackrest.conf. Ein Zweig, der
    frueher zurueckkehrt, darf das nicht verlieren koennen.
    """
    gesehen = []
    monkeypatch.setattr(
        lp.os, "chown", lambda pfad, u, g: gesehen.append(str(pfad))
    )
    cert = tmp_path / "cert"
    cert.mkdir()
    for f in ("ca.crt", "client.crt", "client.key"):
        (cert / f).write_text("x")

    for name, bench in (
        ("tls", dict(BENCH, cert_dir=str(cert))),
        ("s3", BENCH_S3),
    ):
        gesehen.clear()
        arbeit = tmp_path / name
        arbeit.mkdir()
        lp._bench_umgebung(bench, "k", str(arbeit))
        assert str(arbeit) in gesehen, (name, gesehen)


# --------------------------------------------------------------------------- #
# Welcher Bestand geprueft wurde                                               #
# --------------------------------------------------------------------------- #
#
# Seit es zwei Bestaende gibt (Repo-Host und gespiegelter Objektspeicher),
# entstehen je Bereich ZWEI Nachweise. Sehen die gleich aus, nimmt die
# Ueberwachung den juengsten bestandenen - und ein durchgefallener
# Zweitbestand verschwindet hinter dem bestandenen Erstbestand. Die Probe
# waere dann genau das, was sie aufdecken soll: eine Vermutung.


def test_the_name_of_the_store_comes_from_the_configuration():
    """Ein eigener Name schlaegt die Art - 's3' unterscheidet zwei S3 nicht."""
    assert lp._bestandsname({"repo_type": "s3", "store": "zweitbestand"}) == \
        "zweitbestand"
    assert lp._bestandsname({"repo_type": "s3"}) == "s3"
    assert lp._bestandsname({"repo_host": "db.backup"}) == "tls"
    # Leerraum ist keine Benennung.
    assert lp._bestandsname({"store": "  ", "repo_type": "s3"}) == "s3"


def test_every_result_says_which_store_it_came_from(monkeypatch, compose,
                                                    tmp_path):
    """Auch der Fehlerfall - gerade der.

    Ein Nachweis ohne Bestand ist im Ablageordner nicht zuzuordnen, und
    'gescheitert' ohne die Angabe WO ist keine brauchbare Nachricht.
    """
    monkeypatch.setattr(lp.os, "chown", lambda *a, **kw: None)
    # Ohne Zertifikatsordner scheitert die Vorbereitung - genau der Pfad, der
    # frueher gar kein 'store' getragen hat.
    kaputt = lp.run_verify_bench(
        dict(BENCH_S3, store="zweitbestand", s3_bucket=""), "kunde-a"
    )
    assert kaputt["result"] == "failed"
    assert kaputt["store"] == "zweitbestand"

    gerufen = []
    monkeypatch.setattr(
        lp, "_probe",
        lambda umgebung, stanza: gerufen.append(umgebung) or
        {"result": "passed"},
    )
    lp.run_verify(FakeConfig())
    assert gerufen[0]["store"] == "projekt"


def test_the_two_stores_do_not_share_a_file_name(tmp_path, monkeypatch):
    """Zwei Nachweise desselben Bereichs muessen nebeneinander liegen koennen.

    Gleicher Name hiesse: der zweite ueberschreibt den ersten, und die
    Ueberwachung sieht nur noch einen der beiden Bestaende.
    """
    from click.testing import CliRunner

    ergebnisse = [
        {"area": "kunde-a", "store": "erstbestand", "result": "passed",
         "backup": "b", "rows": 1, "table": "t", "seconds": 1},
        {"area": "kunde-a", "store": "zweitbestand", "result": "passed",
         "backup": "b", "rows": 1, "table": "t", "seconds": 1},
    ]
    monkeypatch.setattr(lp, "run_verify_bench",
                        lambda bench, stanza: ergebnisse.pop(0))
    conf = tmp_path / "bench.json"
    conf.write_text(json.dumps({"stanzas": {"kunde-a": {}}}))
    ziel = tmp_path / "ergebnisse"

    # Zweimal aufrufen, wie es der Laeufer je Konfiguration tut.
    runner = CliRunner()
    for _ in range(2):
        runner.invoke(
            lp.pgbackrest_verify,
            ["--bench-config", str(conf), "--report-to", str(ziel)],
            obj=FakeConfig(), standalone_mode=False,
        )

    namen = sorted(p.name for p in ziel.glob("*.json"))
    assert len(namen) == 2, namen
    assert any("-erstbestand-" in n for n in namen), namen
    assert any("-zweitbestand-" in n for n in namen), namen
