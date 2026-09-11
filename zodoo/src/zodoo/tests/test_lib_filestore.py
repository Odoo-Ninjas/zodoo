"""Tests for zodoo.lib_filestore.

The point of the module is a filesystem property - "shared content, private
checklist" - so the tests assert on inode identity and on what survives an
unlink, not on return values alone.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from zodoo import lib_filestore as mod


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _inode(path: Path) -> int:
    return path.stat().st_ino


@pytest.fixture
def filestore(tmp_path):
    (tmp_path / mod.COMMON_DIR_NAME).mkdir()
    return tmp_path


def test_dedupe_adopts_new_files_into_the_pool(filestore):
    db_dir = filestore / "db1"
    attachment = _write(db_dir / "ab" / "abcdef", "payload")

    stats = mod.dedupe_into_common(db_dir, filestore / mod.COMMON_DIR_NAME)

    pooled = filestore / mod.COMMON_DIR_NAME / "ab" / "abcdef"
    assert stats["adopted"] == 1
    assert _inode(pooled) == _inode(attachment)


def test_dedupe_collapses_equal_names_of_two_databases(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    first = _write(filestore / "db1" / "ab" / "abcdef", "payload")
    second = _write(filestore / "db2" / "ab" / "abcdef", "payload")
    assert _inode(first) != _inode(second)

    mod.dedupe_into_common(filestore / "db1", common)
    stats = mod.dedupe_into_common(filestore / "db2", common)

    assert stats["linked"] == 1
    assert _inode(first) == _inode(second)
    assert second.read_text() == "payload"


def test_dedupe_is_idempotent(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    db_dir = filestore / "db1"
    _write(db_dir / "ab" / "abcdef", "payload")

    mod.dedupe_into_common(db_dir, common)
    stats = mod.dedupe_into_common(db_dir, common)

    assert stats == {"adopted": 0, "linked": 0, "shared": 1, "failed": 0}


def test_dedupe_leaves_the_checklist_private(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    db_dir = filestore / "db1"
    _write(db_dir / mod.CHECKLIST_DIR / "ab" / "abcdef", "marker")

    mod.dedupe_into_common(db_dir, common)

    assert not (common / mod.CHECKLIST_DIR).exists()


def test_gc_of_one_database_does_not_hit_the_other(filestore):
    """The regression this module exists for.

    Odoo's GC unlinks ``<filestore>/<db>/<hash>``. With hardlinks that only
    drops this database's link; the other instance keeps its file.
    """
    common = filestore / mod.COMMON_DIR_NAME
    shared_a = _write(filestore / "db1" / "ab" / "abcdef", "payload")
    shared_b = _write(filestore / "db2" / "ab" / "abcdef", "payload")
    mod.dedupe_into_common(filestore / "db1", common)
    mod.dedupe_into_common(filestore / "db2", common)

    os.unlink(shared_a)  # what _gc_file_store does

    assert shared_b.exists()
    assert shared_b.read_text() == "payload"


def test_materialize_from_common_replaces_symlink_by_hardlinks(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    pooled = _write(common / "ab" / "abcdef", "payload")
    _write(common / "cd" / "cdefgh", "other instance's file")
    db_dir = filestore / "db1"
    db_dir.symlink_to(mod.COMMON_DIR_NAME)

    stats = mod.materialize_from_common(db_dir, common, ["ab/abcdef"])

    assert stats == {"linked": 1, "missing": 0, "failed": 0}
    assert not db_dir.is_symlink()
    assert db_dir.is_dir()
    assert _inode(db_dir / "ab" / "abcdef") == _inode(pooled)
    # only what this database references, and its own checklist
    assert not (db_dir / "cd" / "cdefgh").exists()
    assert (db_dir / mod.CHECKLIST_DIR).is_dir()


def test_materialize_from_common_counts_files_lost_before_the_run(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    db_dir = filestore / "db1"
    db_dir.symlink_to(mod.COMMON_DIR_NAME)

    stats = mod.materialize_from_common(db_dir, common, ["ab/gone"])

    assert stats["missing"] == 1
    assert stats["linked"] == 0


def test_materialize_from_common_rejects_a_real_directory(filestore):
    db_dir = filestore / "db1"
    db_dir.mkdir()

    with pytest.raises(ValueError):
        mod.materialize_from_common(
            db_dir, filestore / mod.COMMON_DIR_NAME, []
        )


def test_store_fnames_wraps_an_unreachable_server(monkeypatch):
    """A host where every instance has its own postgres: the current
    project's connection cannot reach the other databases. That must be a
    skippable condition, not a traceback out of the middle of a sweep.
    """
    import psycopg2

    def refuse(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(mod, "table_exists", refuse)
    config = SimpleNamespace(
        get_odoo_conn=lambda: SimpleNamespace(clone=lambda dbname: None)
    )

    with pytest.raises(mod.DatabaseUnreachable):
        mod._store_fnames(config, "some_other_instance")


def test_materialize_from_common_ignores_escaping_store_fnames(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    _write(filestore / "secret", "not an attachment")
    db_dir = filestore / "db1"
    db_dir.symlink_to(mod.COMMON_DIR_NAME)

    stats = mod.materialize_from_common(
        db_dir, common, ["../secret", "/etc/hostname"]
    )

    assert stats["linked"] == 0
    assert not (db_dir / "secret").exists()


def test_heal_links_a_missing_reference_back_out_of_the_pool(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    pooled = _write(common / "ab" / "abcdef", "payload")
    db_dir = filestore / "db1"
    db_dir.mkdir()

    stats = mod.heal_from_common(db_dir, common, ["ab/abcdef"])

    assert stats == {"linked": 1, "present": 0, "lost": 0, "failed": 0}
    restored = db_dir / "ab" / "abcdef"
    assert restored.read_text() == "payload"
    # Shared content, not a copy.
    assert _inode(restored) == _inode(pooled)


def test_heal_never_touches_a_file_the_instance_already_has(filestore):
    """Additive by construction: an instance must never be without its file,
    so an existing entry keeps its inode even if the pool holds another one."""
    common = filestore / mod.COMMON_DIR_NAME
    _write(common / "ab" / "abcdef", "from pool")
    db_dir = filestore / "db1"
    own = _write(db_dir / "ab" / "abcdef", "from pool")
    own_inode = _inode(own)

    stats = mod.heal_from_common(db_dir, common, ["ab/abcdef"])

    assert stats["present"] == 1
    assert stats["linked"] == 0
    assert _inode(own) == own_inode


def test_heal_reports_files_gone_from_pool_and_instance(filestore):
    db_dir = filestore / "db1"
    db_dir.mkdir()

    stats = mod.heal_from_common(
        db_dir, filestore / mod.COMMON_DIR_NAME, ["ab/gone"]
    )

    assert stats["lost"] == 1
    assert not (db_dir / "ab" / "gone").exists()


def test_heal_ignores_absolute_and_traversing_store_fnames(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    db_dir = filestore / "db1"
    db_dir.mkdir()

    stats = mod.heal_from_common(
        db_dir, common, ["/etc/passwd", "../outside", "", None]
    )

    assert stats == {"linked": 0, "present": 0, "lost": 0, "failed": 0}


def test_heal_is_idempotent(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    _write(common / "ab" / "abcdef", "payload")
    db_dir = filestore / "db1"
    db_dir.mkdir()

    first = mod.heal_from_common(db_dir, common, ["ab/abcdef"])
    second = mod.heal_from_common(db_dir, common, ["ab/abcdef"])

    assert first["linked"] == 1
    assert second == {"linked": 0, "present": 1, "lost": 0, "failed": 0}


def test_heal_survives_a_gc_that_dropped_only_this_instances_link(filestore):
    """The whole point of hardlinks: another instance's GC unlinks its own
    entry, the content stays in the pool, and healing brings it back."""
    common = filestore / mod.COMMON_DIR_NAME
    db_dir = filestore / "db1"
    attachment = _write(db_dir / "ab" / "abcdef", "payload")
    mod.dedupe_into_common(db_dir, common)

    attachment.unlink()  # simulate the shared-GC damage
    assert (common / "ab" / "abcdef").exists()

    stats = mod.heal_from_common(db_dir, common, ["ab/abcdef"])

    assert stats["linked"] == 1
    assert (db_dir / "ab" / "abcdef").read_text() == "payload"
