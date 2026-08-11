"""Round trip of ADDITIONAL_ODOO_CONFIG, host side to container side.

The bug this pins down: the host joined the config lines with a separator so
they fit into an environment variable, and the container passed that joined
line straight to configparser. configparser reads
``[options]___|||___dbfilter = .*`` as a section header and throws the rest
of the line away - no error, no warning, and ~/.odoo/odoo.config did nothing.

The two sides live in different processes (host composer vs. container), so
nothing but a test like this connects them.
"""

import configparser

from .. import additional_odoo_config as aoc


def _parse(raw_env_value):
    """What the container does with the variable."""
    cfg = configparser.ConfigParser()
    cfg.read_string(aoc.decode(raw_env_value))
    return cfg


def test_the_raw_joined_line_is_indeed_unusable():
    """Guards the premise - if configparser ever learns this, we can simplify."""
    cfg = configparser.ConfigParser()
    cfg.read_string("[options]" + aoc.SEPARATOR + "dbfilter = .*")
    assert cfg.sections() == ["options"]
    assert dict(cfg["options"]) == {}


def test_option_survives_the_round_trip():
    written_by_the_user = "[options]\ndbfilter = .*\n"
    env_value = aoc.encode(written_by_the_user)

    assert "\n" not in env_value, "must survive an env variable"

    cfg = _parse(env_value)
    assert cfg["options"]["dbfilter"] == ".*"


def test_several_sections_survive():
    text = "[options]\nworkers = 4\n\n[queue_job]\nchannels = root:2\n"
    cfg = _parse(aoc.encode(text))
    assert cfg["options"]["workers"] == "4"
    assert cfg["queue_job"]["channels"] == "root:2"


def test_comments_and_blank_lines_do_not_break_it():
    text = "# my machine\n[options]\n\n; another comment\nlist_db = True\n"
    cfg = _parse(aoc.encode(text))
    assert cfg["options"]["list_db"] == "True"


class TestCarriesOptions:
    """Tells "nothing configured" apart from "configuration lost"."""

    def test_header_only_carries_nothing(self):
        assert aoc.carries_options("[options]\n") is False

    def test_blank_and_comments_carry_nothing(self):
        assert aoc.carries_options("[options]\n\n# hi\n; ho\n") is False

    def test_empty_carries_nothing(self):
        assert aoc.carries_options("") is False

    def test_an_option_carries(self):
        assert aoc.carries_options("[options]\ndbfilter = .*\n") is True

    def test_an_option_without_a_section_carries(self):
        """Invalid for configparser, but the user clearly meant something -
        exactly the case that deserves the warning."""
        assert aoc.carries_options("dbfilter = .*\n") is True
