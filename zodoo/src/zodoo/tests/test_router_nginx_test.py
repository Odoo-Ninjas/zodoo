"""Tests fuer die Syntaxpruefung vor dem nginx-Reload.

Hintergrund: sync_configs.py kopiert die gerenderten Dateien direkt nach
sites-enabled. Ein "nginx -s reload" mit kaputter Konfiguration laesst nginx
mit der alten weiterlaufen - beim naechsten Neustart des Containers kommt er
dann aber nicht mehr hoch, und damit sind ALLE Domains weg. Der Fehler faellt
also erst Stunden spaeter auf, und dann richtig.
"""

from __future__ import annotations


import pytest

from .. import lib_router


class _Res:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_dc(monkeypatch, res):
    aufrufe = []

    def _dc(install_dir, *args, **kwargs):
        aufrufe.append(list(args))
        return res

    monkeypatch.setattr(lib_router, "_dc", _dc)
    return aufrufe


def test_ok_configuration(monkeypatch):
    aufrufe = _fake_dc(
        monkeypatch, _Res(0, stderr="syntax is ok\ntest is successful\n")
    )
    assert lib_router._nginx_test("/opt/proxy") is True
    assert aufrufe == [["exec", "-T", "router", "nginx", "-t"]]


def test_broken_configuration_is_rejected(monkeypatch, capsys):
    """Der Fall, der zaehlt: nginx findet das Zertifikat nicht."""
    _fake_dc(
        monkeypatch,
        _Res(
            1,
            stderr=(
                "nginx: [emerg] cannot load certificate "
                '"/etc/ssl/custom_ssl/lan.internal/server.crt": '
                "BIO_new_file() failed\nnginx: configuration file test failed\n"
            ),
        ),
    )
    assert lib_router._nginx_test("/opt/proxy") is False
    assert "cannot load certificate" in capsys.readouterr().out


def test_router_not_running_is_not_a_rejection(monkeypatch, capsys):
    """Ohne laufenden Router haben wir nichts geprueft - das darf nicht als
    'Konfiguration kaputt' durchgehen, sonst blockiert das erste Setup."""
    _fake_dc(
        monkeypatch,
        _Res(1, stderr='service "router" is not running\n'),
    )
    assert lib_router._nginx_test("/opt/proxy") is None
    assert "without a syntax check" in capsys.readouterr().out


def test_snapshot_and_restore_roundtrip(tmp_path):
    """Alle drei Verzeichnisse muessen zurueckkommen - bliebe
    sites-last-deployed auf dem neuen Stand, sieht der naechste Lauf
    'keine Aenderung' und schreibt sites-enabled nie wieder."""
    for name in lib_router._SYNCED_DIRS:
        d = tmp_path / name
        d.mkdir()
        (d / "kunde.zebroo.de").write_text("alt\n")

    snapshot = lib_router._snapshot_configs(tmp_path)

    # der "kaputte" Deploy
    for name in lib_router._SYNCED_DIRS:
        (tmp_path / name / "kunde.zebroo.de").write_text("neu und kaputt\n")
        (tmp_path / name / "dazugekommen.zebroo.de").write_text("neu\n")

    lib_router._restore_configs(tmp_path, snapshot)

    for name in lib_router._SYNCED_DIRS:
        assert (tmp_path / name / "kunde.zebroo.de").read_text() == "alt\n"
        assert not (
            tmp_path / name / "dazugekommen.zebroo.de"
        ).exists(), (
            f"{name}: neu angelegte Datei muss beim Zurueckrollen weg sein"
        )


def test_snapshot_survives_missing_directories(tmp_path):
    """Beim ersten Setup existieren die Verzeichnisse noch nicht."""
    snapshot = lib_router._snapshot_configs(tmp_path)
    lib_router._restore_configs(tmp_path, snapshot)  # darf nicht werfen


def test_restore_recreates_a_deleted_directory(tmp_path):
    d = tmp_path / "sites-enabled"
    d.mkdir()
    (d / "kunde.zebroo.de").write_text("alt\n")
    snapshot = lib_router._snapshot_configs(tmp_path)

    import shutil

    shutil.rmtree(d)
    lib_router._restore_configs(tmp_path, snapshot)
    assert (d / "kunde.zebroo.de").read_text() == "alt\n"


# ---------------------------------------------------------------------------
# der echte Pfad: _render_and_sync_vhosts
# ---------------------------------------------------------------------------


def _wire_up(monkeypatch, tmp_path, nginx_rc, nginx_msg):
    """Alles ausser der zu testenden Logik durch Attrappen ersetzen."""
    monkeypatch.setattr(
        lib_router, "_router_files_dir", lambda config: tmp_path
    )
    monkeypatch.setattr(
        lib_router, "_generate_self_signed_certs", lambda d, v: None
    )
    monkeypatch.setattr(
        lib_router, "_check_exclusive_tls_flags", lambda v: None
    )

    def fake_run(cmd, **kwargs):
        # render_configs schreibt nichts, sync_configs meldet "reload noetig"
        # und tut so, als haette es deployt (macht der Test unten selbst).
        if any("sync_configs" in str(c) for c in cmd):
            return _Res(10, stdout="requires restart")
        return _Res(0)

    monkeypatch.setattr(lib_router.subprocess, "run", fake_run)
    monkeypatch.setattr(
        lib_router, "_dc", lambda d, *a, **kw: _Res(nginx_rc, stderr=nginx_msg)
    )


def test_broken_config_rolls_back_and_aborts(monkeypatch, tmp_path):
    for name in lib_router._SYNCED_DIRS:
        d = tmp_path / name
        d.mkdir()
        (d / "kunde.zebroo.de").write_text("der gute Stand\n")

    _wire_up(
        monkeypatch,
        tmp_path,
        1,
        'nginx: [emerg] cannot load certificate "..."\n',
    )

    # sync_configs ist eine Attrappe - den kaputten Deploy legen wir selbst
    original = lib_router._snapshot_configs

    def snapshot_then_break(install_dir):
        snap = original(install_dir)
        for name in lib_router._SYNCED_DIRS:
            (install_dir / name / "kunde.zebroo.de").write_text("kaputt\n")
        return snap

    monkeypatch.setattr(lib_router, "_snapshot_configs", snapshot_then_break)

    with pytest.raises(SystemExit):
        lib_router._render_and_sync_vhosts(
            object(), tmp_path, [{"server_name": "kunde.zebroo.de"}]
        )

    for name in lib_router._SYNCED_DIRS:
        assert (
            tmp_path / name / "kunde.zebroo.de"
        ).read_text() == "der gute Stand\n", (
            f"{name} wurde nicht zurueckgerollt"
        )


def test_good_config_is_kept(monkeypatch, tmp_path):
    for name in lib_router._SYNCED_DIRS:
        (tmp_path / name).mkdir()
    _wire_up(monkeypatch, tmp_path, 0, "test is successful\n")

    reload_required = lib_router._render_and_sync_vhosts(
        object(), tmp_path, [{"server_name": "kunde.zebroo.de"}]
    )
    assert reload_required is True


def test_unreachable_router_still_deploys(monkeypatch, tmp_path):
    """Beim ersten Setup laeuft noch kein Router - das darf nicht blockieren."""
    for name in lib_router._SYNCED_DIRS:
        (tmp_path / name).mkdir()
    _wire_up(monkeypatch, tmp_path, 1, 'service "router" is not running\n')
    assert (
        lib_router._render_and_sync_vhosts(
            object(), tmp_path, [{"server_name": "kunde.zebroo.de"}]
        )
        is True
    )
