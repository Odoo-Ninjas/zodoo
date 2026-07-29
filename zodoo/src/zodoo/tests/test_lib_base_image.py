"""Unit tests for the yanked-pin override in lib_base_image.

Guards that a version pinned in Odoo's upstream ``requirements.txt`` which
later disappears from PyPI (yanked) is transparently rewritten to a safe
replacement, so the base image build does not break — while leaving every
other line, marker and comment untouched.

``lib_base_image`` is loaded by path (like test_postgres_maxconn) so the
pure-function assertions don't drag in the whole ``zodoo`` package import
chain and its runtime dependencies.
"""

import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "lib_base_image.py"
_spec = importlib.util.spec_from_file_location("_lbi_under_test", _MODULE_PATH)
lbi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lbi)


def test_rewrites_exact_yanked_cbor2_pin():
    src = "cbor2==5.4.2 ; python_version < '3.12'  # (Jammy)\n"
    out = lbi._apply_yanked_pin_overrides(src)
    assert out == "cbor2==5.4.6 ; python_version < '3.12'  # (Jammy)\n"


def test_does_not_touch_postfixed_version():
    # `5.4.2.post1` is a distinct, non-yanked release and must survive.
    src = "cbor2==5.4.2.post1 ; python_version < '3.11'\n"
    assert lbi._apply_yanked_pin_overrides(src) == src


def test_leaves_other_versions_and_packages_untouched():
    src = (
        "cbor2==5.6.2 ; python_version >= '3.12'\n"
        "requests==2.31.0\n"
        "somecbor2lib==5.4.2\n"  # different package name, must not match
    )
    assert lbi._apply_yanked_pin_overrides(src) == src


def test_rewrite_is_idempotent():
    src = "cbor2==5.4.2\n"
    once = lbi._apply_yanked_pin_overrides(src)
    assert lbi._apply_yanked_pin_overrides(once) == once == "cbor2==5.4.6\n"


def test_multiple_occurrences_all_rewritten():
    src = "cbor2==5.4.2 ; a\ncbor2==5.4.2 ; b\n"
    out = lbi._apply_yanked_pin_overrides(src)
    assert out == "cbor2==5.4.6 ; a\ncbor2==5.4.6 ; b\n"
    assert "5.4.2" not in out
