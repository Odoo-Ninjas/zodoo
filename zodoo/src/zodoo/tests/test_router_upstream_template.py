"""The nginx vhost template, rendered.

Worth its own tests because this one file renders every vhost on the router.
A mistake here is not a broken feature, it is 146 customer sites at once - so
the tests that matter are the ones asserting that a vhost which does NOT ask
for the new options comes out exactly as before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_TEMPLATES = (
    Path(__file__).resolve().parents[4] / "router_global" / "templates"
)


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
    assert "proxy_request_buffering" not in _render(
        proxy_request_buffering=True
    )


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


# ---------------------------------------------------------------------------
# self-signed TLS
#
# A vhost on a protected LAN can never verify with Let's Encrypt, so it must be
# able to listen on 443 with a self-signed certificate that needs no ACME
# at all. ssl_self_signed must do that WITHOUT use_certbot, and the certificate
# directory must default to the server_name so the vhost works with zero extra
# configuration.
# ---------------------------------------------------------------------------


def _render_template(name, **over):
    from jinja2 import Environment, FileSystemLoader

    item = {
        "server_name": "example.zebroo.de",
        "upstream_name": "upstream_1",
        "upstream_server": "192.168.77.42",
        "upstream_port": 8444,
        "timeout": 600,
    }
    item.update(over)
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        keep_trailing_newline=False,
        trim_blocks=True,
        lstrip_blocks=False,
    )
    return env.get_template(name).render(item=item)


@pytest.mark.parametrize(
    "template",
    ["upstream", "upstream_direct_odoo", "static_files"],
)
def test_self_signed_renders_tls_without_certbot(template):
    """ssl_self_signed must give a 443 listener + 80->https redirect on its own.

    No use_certbot, no ssl_key_is_on_destination: only the self-signed flag.
    """
    fields = {
        "upstream_name": "upstream_1",
        "upstream_server": "192.168.77.42",
        "upstream_port": 8069,
        "timeout": 600,
        "folder": "/var/www/example",
    }
    out = _render_template(template, ssl_self_signed=True, **fields)
    assert "listen 443 ssl;" in out
    # plain HTTP must bounce to https instead of hitting the 444 catch-all
    assert "return 301 https://$host$request_uri;" in out
    # certificate directory defaults to the server_name
    assert (
        "ssl_certificate /etc/ssl/custom_ssl/example.zebroo.de/server.crt;"
        in out
    )
    assert (
        "ssl_certificate_key /etc/ssl/custom_ssl/example.zebroo.de/server.key;"
        in out
    )
    # the ACME location must be correctly spelled (it was "accme" before)
    assert "/.well-known/acme-challenge/" in out
    assert "accme-challenge" not in out


def test_self_signed_uses_explicit_certificate_name():
    out = _render_template(
        "upstream",
        upstream_name="upstream_1",
        upstream_server="192.168.77.42",
        upstream_port=8069,
        timeout=600,
        ssl_self_signed=True,
        certificate_name="example-shared",
    )
    assert (
        "ssl_certificate /etc/ssl/custom_ssl/example-shared/server.crt;" in out
    )
    assert (
        "ssl_certificate /etc/ssl/custom_ssl/example.zebroo.de/server.crt;"
        not in out
    )


def test_null_certificate_name_defaults_to_server_name():
    """An explicit YAML null (certificate_name: ~) must behave like omission.

    Jinja's default() only substitutes Undefined, not None - without the
    `true` (default=) argument a null would render custom_ssl/None/ and the
    host-side generator (which uses Python's `or`) would write
    custom_ssl/<server_name>/, so nginx -t fails on the first reload.
    """
    out = _render_template(
        "upstream",
        upstream_name="upstream_1",
        upstream_server="192.168.77.42",
        upstream_port=8069,
        timeout=600,
        ssl_server_cert=True,
        certificate_name=None,
    )
    assert "custom_ssl/None/" not in out
    assert (
        "ssl_certificate /etc/ssl/custom_ssl/example.zebroo.de/server.crt;"
        in out
    )


def test_tls_off_renders_no_tls_at_all():
    """A vhost with none of the tls flags stays exactly as before."""
    out = _render_template(
        "upstream",
        upstream_name="upstream_1",
        upstream_server="192.168.77.42",
        upstream_port=8069,
        timeout=600,
    )
    assert "listen 443 ssl;" not in out
    assert "return 301 https://" not in out


def test_custom_cert_vhost_gets_http_redirect_too():
    """The 80->https redirect is not only for self-signed.

    Before this feature, a vhost with a custom certificate had no per-vhost
    port-80 listener, so plain HTTP hit the 444 catch-all. It now gets the same
    301 redirect as the TLS vhosts - that is the intentional behavior change.
    """
    for flag in ("ssl_key_is_on_destination", "ssl_server_cert"):
        out = _render_template(
            "upstream",
            upstream_name="upstream_1",
            upstream_server="192.168.77.42",
            upstream_port=8069,
            timeout=600,
            **{flag: True},
            certificate_name="example.zebroo.de",
        )
        assert "listen 443 ssl;" in out
        assert "return 301 https://$host$request_uri;" in out
