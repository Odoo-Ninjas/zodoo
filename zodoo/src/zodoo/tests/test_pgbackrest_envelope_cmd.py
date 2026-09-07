"""Tests des Oeffnen-Befehls (`odoo pgbackrest envelope`).

Der Befehl ist der Weg, eine Passphrase zurueckzubekommen. Wichtig ist dabei
zweierlei, und das zweite ist das eigentliche:

* dass er OHNE Pruefstand geht - im Ernstfall ist der Pruefstand vielleicht
  genau das, was fehlt,
* dass er bei fehlenden Angaben SAGT, was fehlt, statt unverstaendlich zu
  scheitern. Wer diesen Befehl braucht, hat einen schlechten Tag.
"""

import json
from unittest import mock

from click.testing import CliRunner

from zodoo import lib_pgbackrest as lp


class FakeConfig:
    project_name = "kunde"
    pgbr_stanza = None
    HOST_RUN_DIR = "/tmp/run-kunde"
    dirs = {}


INHALT = {
    "cipher_pass": "GEHEIME-PASSPHRASE",
    "client_cert": "-----BEGIN CERTIFICATE-----",
    "repo_host": "db.backup.zebroo.de",
    "stanza": "kunde-a",
}


def _lauf(args, inhalt=INHALT, seiteneffekt=None):
    with mock.patch.object(
        lp, "open_envelope",
        side_effect=seiteneffekt or (lambda i, p: inhalt),
    ):
        return CliRunner().invoke(
            lp.pgbackrest_envelope, args, obj=FakeConfig(),
            standalone_mode=False,
        )


def test_a_single_field_comes_out_raw(tmp_path):
    """Roh auf stdout, damit sich der Wert weiterverwenden laesst."""
    umschlag = tmp_path / "kunde-a-20260101T000000Z.age"
    umschlag.write_text("x")
    key = tmp_path / "age.key"
    key.write_text("x")

    r = _lauf(["--file", str(umschlag), "--age-key", str(key)])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "GEHEIME-PASSPHRASE"


def test_the_newest_envelope_of_an_area_is_used(tmp_path):
    key = tmp_path / "age.key"
    key.write_text("x")
    for name in ("kunde-a-20260101T000000Z.age",
                 "kunde-a-20260601T000000Z.age"):
        (tmp_path / name).write_text("x")

    gesehen = {}

    def merken(identity, pfad):
        gesehen["pfad"] = pfad
        return INHALT

    r = _lauf(["--area", "kunde-a", "--envelope-dir", str(tmp_path),
               "--age-key", str(key)], seiteneffekt=merken)
    assert r.exit_code == 0, r.output
    assert gesehen["pfad"].endswith("20260601T000000Z.age")


def test_list_fields_shows_names_and_no_values(tmp_path):
    """Wer wissen will was drin ist, muss nicht alles ausgeben lassen."""
    umschlag = tmp_path / "kunde-a-20260101T000000Z.age"
    umschlag.write_text("x")
    key = tmp_path / "age.key"
    key.write_text("x")

    r = _lauf(["--file", str(umschlag), "--age-key", str(key),
               "--list-fields"])
    assert r.exit_code == 0, r.output
    assert "cipher_pass" in r.output
    assert "GEHEIME-PASSPHRASE" not in r.output


def test_a_missing_key_says_where_to_get_it(tmp_path):
    umschlag = tmp_path / "kunde-a-20260101T000000Z.age"
    umschlag.write_text("x")
    r = _lauf(["--file", str(umschlag)])
    assert r.exit_code != 0
    text = str(r.output) + str(r.exception)
    assert "age-key" in text
    assert "1Password" in text


def test_an_unknown_field_lists_what_is_there(tmp_path):
    """Und nennt die NAMEN, nicht die Werte."""
    umschlag = tmp_path / "kunde-a-20260101T000000Z.age"
    umschlag.write_text("x")
    key = tmp_path / "age.key"
    key.write_text("x")

    r = _lauf(["--file", str(umschlag), "--age-key", str(key),
               "--field", "gibtsnicht"])
    assert r.exit_code != 0
    text = str(r.output) + str(r.exception)
    assert "cipher_pass" in text
    assert "GEHEIME-PASSPHRASE" not in text


def test_an_area_without_a_directory_is_named_plainly(tmp_path):
    key = tmp_path / "age.key"
    key.write_text("x")
    r = _lauf(["--area", "kunde-a", "--age-key", str(key)])
    assert r.exit_code != 0
    text = str(r.output) + str(r.exception)
    assert "envelope-dir" in text


def test_the_bench_config_brings_key_and_directory(tmp_path):
    """Auf dem Pruefstand soll ein Argument genuegen."""
    key = tmp_path / "age.key"
    key.write_text("x")
    (tmp_path / "kunde-a-20260101T000000Z.age").write_text("x")
    conf = tmp_path / "bench.json"
    conf.write_text(json.dumps({
        "age_identity": str(key), "envelope_dir": str(tmp_path)}))

    r = _lauf(["--area", "kunde-a", "--bench-config", str(conf)])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "GEHEIME-PASSPHRASE"
