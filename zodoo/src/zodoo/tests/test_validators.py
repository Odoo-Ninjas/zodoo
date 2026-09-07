"""Tests for the shared inquirer validators in `tools`.

The point of these helpers is a trap in inquirer: a `validate` callable that
*returns* an error message accepts every wrong answer, because the message is
truthy. The first test nails that behaviour down so nobody "simplifies" the
helpers back into a one-liner.
"""

from __future__ import annotations

import inquirer
import inquirer.errors
import pytest

from ..tools import validate_nonempty, validate_port, validation_error


def test_a_returned_error_string_is_accepted_by_inquirer():
    """Why the helpers exist: this is the tempting one-liner, and it lets
    'abc' through as a valid port."""
    question = inquirer.Text(
        "port",
        validate=lambda _, x: x.isdigit()
        and 1 <= int(x) <= 65535
        or "Must be a valid port number",
    )
    # validate() returns None when it considers the input fine - so "abc"
    # passes, and the message is never shown.
    assert question.validate("abc") is None


@pytest.mark.parametrize("value", ["1", "80", "8069", "65535", " 6000 "])
def test_validate_port_accepts_real_ports(value):
    assert validate_port(None, value) is True


@pytest.mark.parametrize(
    "value", ["0", "65536", "abc", "", "  ", "80.5", "-1"]
)
def test_validate_port_rejects_the_rest(value):
    with pytest.raises(inquirer.errors.ValidationError):
        validate_port(None, value)


def test_validate_port_rejects_through_inquirer():
    """End to end: as a `validate=` on a real question, a bad port raises."""
    question = inquirer.Text("port", validate=validate_port)
    with pytest.raises(inquirer.errors.ValidationError):
        question.validate("abc")
    assert question.validate("8069") is None


@pytest.mark.parametrize("value", ["x", "kunde.zebroo.de", " a "])
def test_validate_nonempty_accepts_content(value):
    assert validate_nonempty(None, value) is True


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_validate_nonempty_rejects_blanks(value):
    with pytest.raises(inquirer.errors.ValidationError):
        validate_nonempty(None, value)


def test_validation_error_carries_the_reason():
    with pytest.raises(inquirer.errors.ValidationError) as caught:
        validation_error("something specific")
    assert caught.value.reason == "something specific"
