"""Freigabe von der eigenen Konsole (`odoo pgbackrest register --approve`).

Der Weg existiert, weil zodoo oeffentlich ist: anfragen darf jeder, freigeben
nur, wer das Anmeldegeheimnis UND das Abhol-Token dieser Anfrage hat. Geprueft
wird hier beides - dass das Geheimnis nicht im Klartext durch die Gegend geht,
und dass ohne Token gar nicht erst gefragt wird.
"""

from unittest import mock

import pytest

from zodoo import lib_pgbackrest as lp


class FakeConfig:
    project_name = "kunde"
    PGBR_ENROLL_URL = "https://enroll.example"


def test_ohne_token_wird_nicht_gefragt():
    """Ohne Abhol-Token kann die Freigabe nicht gelingen - also gar nicht erst
    hinschicken. Der Dienst zaehlt Fehlversuche und sperrt die Adresse."""
    with mock.patch.object(lp.click, "prompt") as prompt, mock.patch.object(
        lp, "_enroll_call"
    ) as ruf:
        with pytest.raises(SystemExit):
            lp._selbst_freigeben(FakeConfig(), {"request_id": "abc", "token": ""})
    prompt.assert_not_called()
    ruf.assert_not_called()


def test_geheimnis_wird_verdeckt_abgefragt_und_mitgeschickt():
    with mock.patch.object(
        lp.click, "prompt", return_value="  geheim  "
    ) as prompt, mock.patch.object(
        lp, "_enroll_call", return_value={"status": "approved", "note": "Projekt 42"}
    ) as ruf:
        assert lp._selbst_freigeben(
            FakeConfig(), {"request_id": "abc", "token": "tok"}
        )
    assert prompt.call_args.kwargs["hide_input"] is True
    pfad, nutzlast = ruf.call_args[0][2], ruf.call_args[0][3]
    assert pfad == "/api/approve"
    assert nutzlast == {"request_id": "abc", "token": "tok", "secret": "geheim"}


def test_ohne_ablage_bleibt_es_bei_einem_hinweis():
    """Der Bereich kann angelegt sein, ohne dass es Zugangsdaten gibt: solange
    der Umschlag nicht am Projekt liegt, fehlt die Zweitschrift. Dann soll der
    Befehl das sagen und NICHT so tun, als waere er fertig."""
    antwort = {"status": "pending", "note": "kein Projekt zugeordnet"}
    with mock.patch.object(lp.click, "prompt", return_value="geheim"), mock.patch.object(
        lp, "_enroll_call", return_value=antwort
    ):
        assert not lp._selbst_freigeben(
            FakeConfig(), {"request_id": "abc", "token": "tok"}
        )


def test_register_kennt_die_option():
    namen = [p.name for p in lp.pgbackrest_register.params]
    assert "approve" in namen
