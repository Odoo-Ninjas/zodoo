"""Tests fuer die Wiederherstellung der certbot-Einbindung nach einem Render.

Hintergrund: bei `use_certbot`-vhosts stehen `listen 443 ssl` und die
Zertifikatspfade nicht in unseren Templates, sondern schreibt certbot in die
ausgelieferte Datei (`# managed by Certbot`). Diese Datei ist die einzige
Stelle, an der sie existieren. sync_configs.py laesst eine Datei in Ruhe,
solange der Render bitgleich zum letzten Stand ist - aendert sich am Template
etwas, wird sie ueberschrieben und der vhost verliert TLS. Ohne Fehler, denn
eine Konfiguration ohne TLS ist gueltig.

Am 09.09.2026 hat das eine ganze Flotte getroffen: 149 Domains nur noch auf
Port 80, mit HSTS also gar nicht erreichbar.
"""

from __future__ import annotations

from .. import lib_router

MIT_TLS = """server {
    server_name example.com;
    listen 80;
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem; # managed by Certbot
}
"""

OHNE_TLS = """server {
    server_name example.com;
    listen 80;
}
"""


def _install_dir(tmp_path, deployed):
    """Anlage wie auf der Maschine: install_dir + Snapshot des Vorzustands."""
    install = tmp_path / "proxy"
    (install / "sites-enabled").mkdir(parents=True)
    snapshot = tmp_path / "snap"
    (snapshot / "sites-enabled").mkdir(parents=True)
    for name, content in deployed.items():
        (install / "sites-enabled" / name).write_text(content["jetzt"])
        (snapshot / "sites-enabled" / name).write_text(content["vorher"])
    return install, snapshot


def _fake_setup_ssl(monkeypatch, install, fehlschlaege=()):
    """Simuliert `bin/setup_ssl.py`: haengt die certbot-Zeilen wieder an."""
    aufrufe = []

    class _Res:
        def __init__(self, returncode):
            self.returncode = returncode
            self.stdout = "certbot output"
            self.stderr = ""

    def _run(cmd, cwd=None, capture_output=None, text=None, **kwargs):
        name = cmd[-1]
        aufrufe.append(name)
        if name in fehlschlaege:
            return _Res(1)
        pfad = install / "sites-enabled" / name
        pfad.write_text(
            pfad.read_text() + "    listen 443 ssl; # managed by Certbot\n"
        )
        return _Res(0)

    monkeypatch.setattr(lib_router.subprocess, "run", _run)
    return aufrufe


def test_verlorene_einbindung_wird_wiederhergestellt(tmp_path, monkeypatch):
    install, snapshot = _install_dir(
        tmp_path, {"example.com": {"vorher": MIT_TLS, "jetzt": OHNE_TLS}}
    )
    aufrufe = _fake_setup_ssl(monkeypatch, install)

    restored, failed = lib_router._reinstall_certbot_tls(
        install,
        [{"server_name": "example.com", "use_certbot": True}],
        snapshot,
    )

    # Seit dem Schnellrestore laeuft dafuer KEIN certbot mehr: die Zeilen
    # stehen im Schnappschuss und werden als Text zurueckgetragen. certbot
    # bleibt die Rueckfallebene (siehe test_certbot_als_rueckfallebene in
    # test_router_tls_schnellrestore.py).
    assert aufrufe == []
    assert restored == ["example.com"]
    assert failed == []
    inhalt = (install / "sites-enabled" / "example.com").read_text()
    assert "managed by Certbot" in inhalt
    assert "listen 443 ssl" in inhalt


def test_unveraenderte_datei_wird_nicht_angefasst(tmp_path, monkeypatch):
    """Der Normalfall: sync_configs hat die Datei gar nicht ueberschrieben."""
    install, snapshot = _install_dir(
        tmp_path, {"example.com": {"vorher": MIT_TLS, "jetzt": MIT_TLS}}
    )
    aufrufe = _fake_setup_ssl(monkeypatch, install)

    restored, failed = lib_router._reinstall_certbot_tls(
        install,
        [{"server_name": "example.com", "use_certbot": True}],
        snapshot,
    )

    assert aufrufe == []  # kein certbot-Lauf, kein Zeitverlust
    assert (restored, failed) == ([], [])


def test_vhost_ohne_certbot_bleibt_unberuehrt(tmp_path, monkeypatch):
    install, snapshot = _install_dir(
        tmp_path, {"intern.lan": {"vorher": MIT_TLS, "jetzt": OHNE_TLS}}
    )
    aufrufe = _fake_setup_ssl(monkeypatch, install)

    restored, failed = lib_router._reinstall_certbot_tls(
        install,
        [{"server_name": "intern.lan", "ssl_self_signed": True}],
        snapshot,
    )

    assert aufrufe == []
    assert (restored, failed) == ([], [])


def test_ein_fehlschlag_stoppt_die_uebrigen_nicht(
    tmp_path, monkeypatch, capsys
):
    """Der Fall aus dem Vorfall: ein Host ohne DNS darf den Rest nicht mitnehmen."""
    # Marker im Schnappschuss, aber keine verwertbare TLS-Zeile: damit greift
    # der Schnellrestore nicht und der certbot-Weg wird benutzt - nur dort
    # kann ueberhaupt ein einzelner Host fehlschlagen.
    nur_marker = OHNE_TLS.replace(
        "server {", "server {\n    # managed by Certbot", 1
    )
    install, snapshot = _install_dir(
        tmp_path,
        {
            "kaputt.de": {"vorher": nur_marker, "jetzt": OHNE_TLS},
            "gut.de": {"vorher": nur_marker, "jetzt": OHNE_TLS},
        },
    )
    aufrufe = _fake_setup_ssl(monkeypatch, install, fehlschlaege={"kaputt.de"})

    restored, failed = lib_router._reinstall_certbot_tls(
        install,
        [
            {"server_name": "kaputt.de", "use_certbot": True},
            {"server_name": "gut.de", "use_certbot": True},
        ],
        snapshot,
    )

    assert aufrufe == ["kaputt.de", "gut.de"]
    assert restored == ["gut.de"]
    assert failed == ["kaputt.de"]
    # Der Betreiber muss erfahren, welche Domain ohne TLS zurueckbleibt.
    ausgabe = capsys.readouterr().out
    assert "STILL WITHOUT TLS" in ausgabe
    assert "kaputt.de" in ausgabe
