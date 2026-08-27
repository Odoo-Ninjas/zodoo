"""The nginx vhost template, rendered.

Worth its own tests because this one file renders every vhost on the router.
A mistake here is not a broken feature, it is 146 customer sites at once - so
the tests that matter are the ones asserting that a vhost which does NOT ask
for the new options comes out exactly as before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_TEMPLATES = Path(__file__).resolve().parents[4] / "router_global" / "templates"


def _render(**over):
    from jinja2 import Environment, FileSystemLoader

    item = {
        "template": "upstream",
        "server_name": "example.zebroo.de",
        "upstream_name": "upstream_1",
        "upstream_server": "192.168.77.42",
        "upstream_port": 8444,
        "use_certbot": True,
        "timeout": 600,
    }
    item.update(over)
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        keep_trailing_newline=False,
        trim_blocks=True,
        lstrip_blocks=False,
    )
    return env.get_template("upstream").render(item=item)


def test_plain_vhost_is_unchanged_by_the_new_options():
    """The default must stay exactly what it was: http, 1024M, buffering on.

    Every existing vhost renders through this path without setting any of the
    new keys. If a default ever shifts, it shifts for all of them at once.
    """
    out = _render()
    assert "proxy_pass http://$var_upstream_1;" in out
    assert "proxy_pass https://" not in out
    assert "client_max_body_size 1024M;" in out
    assert "proxy_request_buffering" not in out


def test_https_upstream():
    """Some backends speak TLS themselves and cannot be terminated for.

    The write-only receiver is one: it is reached over HTTPS and nothing in
    front of it may re-encrypt on its behalf.
    """
    out = _render(upstream_scheme="https")
    assert "proxy_pass https://$var_upstream_1;" in out
    assert "proxy_pass http://$var_upstream_1;" not in out


def test_unlimited_body_and_streaming_for_large_uploads():
    """A filestore bundle has no size known in advance.

    Without both of these nginx first refuses anything over 1024M and then,
    once allowed, spools the whole request to disk before the backend sees a
    single byte.
    """
    out = _render(client_max_body_size="0", proxy_request_buffering=False)
    assert "client_max_body_size 0;" in out
    assert "client_max_body_size 1024M;" not in out
    assert "proxy_request_buffering off;" in out


def test_buffering_stays_on_unless_explicitly_turned_off():
    """True must not emit the directive - only an explicit False may."""
    assert "proxy_request_buffering" not in _render(proxy_request_buffering=True)


@pytest.mark.parametrize("scheme", ["http", None])
def test_http_is_the_default_however_it_is_spelled(scheme):
    out = _render(**({} if scheme is None else {"upstream_scheme": scheme}))
    assert "proxy_pass http://$var_upstream_1;" in out

def test_no_rate_limit_by_default():
    """A vhost that does not ask for it must render exactly as before.

    This template renders every vhost on the router. A limit that appears
    where nobody asked for one throttles customer sites.
    """
    out = _render()
    assert "limit_req" not in out
    assert "limit_req_zone" not in out


def test_rate_limit_declares_zone_and_applies_it():
    """Zone in the http context, application in the server block.

    nginx refuses limit_req_zone anywhere but http, and a limit_req naming a
    zone that was never declared fails the config test - so the two halves
    have to appear together or not at all.
    """
    out = _render(rate_limit="10r/s")
    assert (
        "limit_req_zone $binary_remote_addr zone=upstream_1_rl:10m rate=10r/s;"
        in out
    )
    assert "limit_req zone=upstream_1_rl burst=20 nodelay;" in out
    assert "limit_req_status 429;" in out
    # The zone must come before the server block that uses it.
    assert out.index("limit_req_zone") < out.index("server {")


def test_rate_limit_burst_is_configurable():
    out = _render(rate_limit="5r/s", rate_limit_burst=100)
    assert "burst=100" in out
