"""Die TLS-Einbindung wird als Textbaustein zurueckgetragen, nicht per certbot.

Hintergrund: `listen 443 ssl` und die Zertifikatspfade stehen nur in der
ausgelieferten Datei (von certbot geschrieben). Ein Render, der die Datei
ueberschreibt, nimmt sie mit - und weil eine Konfiguration ohne TLS gueltig
ist, faellt es nicht auf.

Sie wieder einzusetzen ging bisher ueber `certbot install`. Das ist durch das
certbot-Lock serialisiert: bei einer Template-Aenderung, die die ganze Flotte
neu rendert, laeuft das stundenlang, und solange sind die noch nicht
abgearbeiteten Domains ohne TLS. Die Zeilen stehen aber im Schnappschuss und
galten bis vor Sekunden - zurueckschreiben ist eine Textoperation.
"""

from __future__ import annotations

import pytest

from .. import lib_router
from ..lib_router import (
    _certbot_directive_lines,
    _reinsert_certbot_lines,
)

MIT_TLS = """\
server {
        server_name  kunde.zebroo.de;
        location / {
                proxy_pass http://$var_kunde;
        }

        # SSL_CERTIFICATE_ANSIBLE
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/kunde.zebroo.de/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/kunde.zebroo.de/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}
"""

OHNE_TLS = """\
server {
        server_name  kunde.zebroo.de;
        location / {
                proxy_pass http://$var_kunde;
        }

        # SSL_CERTIFICATE_ANSIBLE
}
"""


def test_die_fuenf_tls_zeilen_werden_erkannt():
    zeilen = _certbot_directive_lines(MIT_TLS)
    assert len(zeilen) == 5
    assert any("listen 443 ssl" in z for z in zeilen)
    assert any("fullchain.pem" in z for z in zeilen)


def test_ein_redirect_serverblock_wird_nicht_mitgenommen():
    """certbot kann mit --redirect einen eigenen server-Block hinterlassen.
    Der darf nicht mitten in einen anderen server-Block geraten."""
    mit_redirect = MIT_TLS + """
server {
    if ($host = kunde.zebroo.de) {
        return 301 https://$host$request_uri;
    } # managed by Certbot
    listen 80;
    return 404; # managed by Certbot
}
"""
    zeilen = _certbot_directive_lines(mit_redirect)
    assert not any("return 301" in z for z in zeilen)
    assert not any("return 404" in z for z in zeilen)
    assert all(
        any(d in z for d in lib_router._CERTBOT_DIRECTIVES) for z in zeilen
    )


def test_zeilen_landen_am_platzhalter():
    neu = _reinsert_certbot_lines(OHNE_TLS, _certbot_directive_lines(MIT_TLS))
    assert "listen 443 ssl" in neu
    # innerhalb des server-Blocks, also vor der letzten Klammer
    assert neu.rstrip().endswith("}")
    assert neu.index("listen 443") < neu.rstrip().rfind("}")


def test_ohne_platzhalter_vor_die_letzte_klammer():
    ohne_platzhalter = OHNE_TLS.replace(
        "        # SSL_CERTIFICATE_ANSIBLE\n", ""
    )
    neu = _reinsert_certbot_lines(
        ohne_platzhalter, _certbot_directive_lines(MIT_TLS)
    )
    assert "listen 443 ssl" in neu
    assert neu.index("listen 443") < neu.rstrip().rfind("}")


def test_kaputte_datei_ohne_klammer_gibt_none():
    assert (
        _reinsert_certbot_lines("kein server block", ["listen 443 ssl;"])
        is None
    )


# ---------------------------------------------------------------------------
# der Weg durch _reinstall_certbot_tls
# ---------------------------------------------------------------------------


def _lage(tmp_path, vorher, nachher, name="kunde.zebroo.de"):
    snapshot = tmp_path / "snap" / "sites-enabled"
    snapshot.mkdir(parents=True)
    (snapshot / name).write_text(vorher)
    enabled = tmp_path / "install" / "sites-enabled"
    enabled.mkdir(parents=True)
    (enabled / name).write_text(nachher)
    return tmp_path / "install", tmp_path / "snap"


def test_restore_ohne_certbot(tmp_path, monkeypatch):
    """Der Kern: kein subprocess, keine Aufreihung hinter dem certbot-Lock."""
    install_dir, snapshot = _lage(tmp_path, MIT_TLS, OHNE_TLS)

    def kein_subprocess(*a, **kw):
        raise AssertionError("certbot haette nicht laufen duerfen")

    monkeypatch.setattr(lib_router.subprocess, "run", kein_subprocess)

    restored, failed = lib_router._reinstall_certbot_tls(
        install_dir, [{"server_name": "kunde.zebroo.de"}], snapshot
    )
    assert restored == ["kunde.zebroo.de"]
    assert failed == []
    assert (
        "listen 443 ssl"
        in (install_dir / "sites-enabled" / "kunde.zebroo.de").read_text()
    )


def test_vhost_ohne_use_certbot_wird_auch_gerettet(tmp_path, monkeypatch):
    """Auf hy-router tragen 154 vhosts eine certbot-Einbindung, aber nur 147
    das Flag - die sieben ohne (kraeuterblume.de und Umlaut-Varianten) waren
    vorher ungeschuetzt."""
    install_dir, snapshot = _lage(tmp_path, MIT_TLS, OHNE_TLS)
    monkeypatch.setattr(
        lib_router.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("kein certbot"),
    )
    restored, _ = lib_router._reinstall_certbot_tls(
        install_dir,
        [{"server_name": "kunde.zebroo.de"}],  # kein use_certbot!
        snapshot,
    )
    assert restored == ["kunde.zebroo.de"]


def test_unveraenderte_einbindung_wird_nicht_angefasst(tmp_path, monkeypatch):
    install_dir, snapshot = _lage(tmp_path, MIT_TLS, MIT_TLS)
    monkeypatch.setattr(
        lib_router.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("nichts zu tun"),
    )
    restored, failed = lib_router._reinstall_certbot_tls(
        install_dir, [{"server_name": "kunde.zebroo.de"}], snapshot
    )
    assert (restored, failed) == ([], [])


def test_certbot_als_rueckfallebene(tmp_path, monkeypatch):
    """Steht im Schnappschuss ein Marker, aber keine verwertbare Direktive,
    muss certbot ran."""
    kaputt = MIT_TLS.replace(
        "listen 443 ssl; # managed by Certbot", "# managed by Certbot"
    )
    for d in ("ssl_certificate", "options-ssl-nginx.conf", "ssl_dhparam"):
        kaputt = "\n".join(l for l in kaputt.splitlines() if d not in l)
    install_dir, snapshot = _lage(tmp_path, kaputt, OHNE_TLS)

    gerufen = []

    class _Res:
        returncode = 0
        stdout = stderr = ""

    def fake_run(cmd, **kw):
        gerufen.append(cmd)
        return _Res()

    monkeypatch.setattr(lib_router.subprocess, "run", fake_run)
    restored, failed = lib_router._reinstall_certbot_tls(
        install_dir, [{"server_name": "kunde.zebroo.de"}], snapshot
    )
    assert gerufen, "certbot haette laufen muessen"
    assert "setup_ssl.py" in " ".join(str(x) for x in gerufen[0])
    assert restored == ["kunde.zebroo.de"]
