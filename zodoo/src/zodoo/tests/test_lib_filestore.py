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
    attachment = _write(db_dir / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "payload")

    stats = mod.dedupe_into_common(db_dir, filestore / mod.COMMON_DIR_NAME)

    pooled = filestore / mod.COMMON_DIR_NAME / "ab" / "abcccccccccccccccccccccccccccccccccccccc"
    assert stats["adopted"] == 1
    assert _inode(pooled) == _inode(attachment)


def test_dedupe_collapses_equal_names_of_two_databases(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    first = _write(filestore / "db1" / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "payload")
    second = _write(filestore / "db2" / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "payload")
    assert _inode(first) != _inode(second)

    mod.dedupe_into_common(filestore / "db1", common)
    stats = mod.dedupe_into_common(filestore / "db2", common)

    assert stats["linked"] == 1
    assert _inode(first) == _inode(second)
    assert second.read_text() == "payload"


def test_dedupe_is_idempotent(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    db_dir = filestore / "db1"
    _write(db_dir / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "payload")

    mod.dedupe_into_common(db_dir, common)
    stats = mod.dedupe_into_common(db_dir, common)

    assert stats == {
        "adopted": 0,
        "linked": 0,
        "shared": 1,
        "failed": 0,
        "foreign": 0,
    }


def test_dedupe_leaves_the_checklist_private(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    db_dir = filestore / "db1"
    _write(db_dir / mod.CHECKLIST_DIR / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "marker")

    mod.dedupe_into_common(db_dir, common)

    assert not (common / mod.CHECKLIST_DIR).exists()


def test_gc_of_one_database_does_not_hit_the_other(filestore):
    """The regression this module exists for.

    Odoo's GC unlinks ``<filestore>/<db>/<hash>``. With hardlinks that only
    drops this database's link; the other instance keeps its file.
    """
    common = filestore / mod.COMMON_DIR_NAME
    shared_a = _write(filestore / "db1" / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "payload")
    shared_b = _write(filestore / "db2" / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "payload")
    mod.dedupe_into_common(filestore / "db1", common)
    mod.dedupe_into_common(filestore / "db2", common)

    os.unlink(shared_a)  # what _gc_file_store does

    assert shared_b.exists()
    assert shared_b.read_text() == "payload"


def test_materialize_from_common_replaces_symlink_by_hardlinks(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    pooled = _write(common / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "payload")
    _write(common / "cd" / "cdeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "other instance's file")
    db_dir = filestore / "db1"
    db_dir.symlink_to(mod.COMMON_DIR_NAME)

    stats = mod.materialize_from_common(db_dir, common, ["ab/abcccccccccccccccccccccccccccccccccccccc"])

    assert stats == {"linked": 1, "missing": 0, "failed": 0}
    assert not db_dir.is_symlink()
    assert db_dir.is_dir()
    assert _inode(db_dir / "ab" / "abcccccccccccccccccccccccccccccccccccccc") == _inode(pooled)
    # only what this database references, and its own checklist
    assert not (db_dir / "cd" / "cdeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee").exists()
    assert (db_dir / mod.CHECKLIST_DIR).is_dir()


def test_materialize_from_common_counts_files_lost_before_the_run(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    db_dir = filestore / "db1"
    db_dir.symlink_to(mod.COMMON_DIR_NAME)

    stats = mod.materialize_from_common(db_dir, common, ["ab/abffffffffffffffffffffffffffffffffffffff"])

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
    pooled = _write(common / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "payload")
    db_dir = filestore / "db1"
    db_dir.mkdir()

    stats = mod.heal_from_common(db_dir, common, ["ab/abcccccccccccccccccccccccccccccccccccccc"])

    assert stats == {"linked": 1, "present": 0, "lost": 0, "failed": 0}
    restored = db_dir / "ab" / "abcccccccccccccccccccccccccccccccccccccc"
    assert restored.read_text() == "payload"
    # Shared content, not a copy.
    assert _inode(restored) == _inode(pooled)


def test_heal_never_touches_a_file_the_instance_already_has(filestore):
    """Additive by construction: an instance must never be without its file,
    so an existing entry keeps its inode even if the pool holds another one."""
    common = filestore / mod.COMMON_DIR_NAME
    _write(common / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "from pool")
    db_dir = filestore / "db1"
    own = _write(db_dir / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "from pool")
    own_inode = _inode(own)

    stats = mod.heal_from_common(db_dir, common, ["ab/abcccccccccccccccccccccccccccccccccccccc"])

    assert stats["present"] == 1
    assert stats["linked"] == 0
    assert _inode(own) == own_inode


def test_heal_reports_files_gone_from_pool_and_instance(filestore):
    db_dir = filestore / "db1"
    db_dir.mkdir()

    stats = mod.heal_from_common(
        db_dir, filestore / mod.COMMON_DIR_NAME, ["ab/abffffffffffffffffffffffffffffffffffffff"]
    )

    assert stats["lost"] == 1
    assert not (db_dir / "ab" / "abffffffffffffffffffffffffffffffffffffff").exists()


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
    _write(common / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "payload")
    db_dir = filestore / "db1"
    db_dir.mkdir()

    first = mod.heal_from_common(db_dir, common, ["ab/abcccccccccccccccccccccccccccccccccccccc"])
    second = mod.heal_from_common(db_dir, common, ["ab/abcccccccccccccccccccccccccccccccccccccc"])

    assert first["linked"] == 1
    assert second == {"linked": 0, "present": 1, "lost": 0, "failed": 0}


def test_heal_survives_a_gc_that_dropped_only_this_instances_link(filestore):
    """The whole point of hardlinks: another instance's GC unlinks its own
    entry, the content stays in the pool, and healing brings it back."""
    common = filestore / mod.COMMON_DIR_NAME
    db_dir = filestore / "db1"
    attachment = _write(db_dir / "ab" / "abcccccccccccccccccccccccccccccccccccccc", "payload")
    mod.dedupe_into_common(db_dir, common)

    attachment.unlink()  # simulate the shared-GC damage
    assert (common / "ab" / "abcccccccccccccccccccccccccccccccccccccc").exists()

    stats = mod.heal_from_common(db_dir, common, ["ab/abcccccccccccccccccccccccccccccccccccccc"])

    assert stats["linked"] == 1
    assert (db_dir / "ab" / "abcccccccccccccccccccccccccccccccccccccc").read_text() == "payload"


def test_dedupe_leaves_files_without_an_attachment_name_alone(filestore):
    """A name that is not a content hash proves nothing about the content.

    Two databases can hold the same such name with different bytes. Adopting
    it would hardlink both to one inode and one instance would start reading
    the other's data -- silently, because nothing errors. So it stays put.
    """
    common = filestore / mod.COMMON_DIR_NAME
    eins = _write(filestore / "db1" / "ab" / "notizen.txt", "von db1")
    zwei = _write(filestore / "db2" / "ab" / "notizen.txt", "von db2")

    erste = mod.dedupe_into_common(filestore / "db1", common)
    zweite = mod.dedupe_into_common(filestore / "db2", common)

    assert erste["foreign"] == 1 and erste["adopted"] == 0
    assert zweite["foreign"] == 1 and zweite["adopted"] == 0
    assert not (common / "ab" / "notizen.txt").exists()
    # Der Punkt der Sache: die Inhalte bleiben getrennt.
    assert _inode(eins) != _inode(zwei)
    assert eins.read_text() == "von db1"
    assert zwei.read_text() == "von db2"


def test_dedupe_still_pools_real_attachments_next_to_a_foreign_file(filestore):
    common = filestore / mod.COMMON_DIR_NAME
    db_dir = filestore / "db1"
    anhang = _write(db_dir / "ab" / ("ab" + "c" * 38), "nutzlast")
    _write(db_dir / "ab" / "README", "kein anhang")

    stats = mod.dedupe_into_common(db_dir, common)

    assert stats["adopted"] == 1
    assert stats["foreign"] == 1
    assert _inode(common / "ab" / ("ab" + "c" * 38)) == _inode(anhang)


def test_attachment_name_accepts_sha1_and_sha256_only():
    from pathlib import PurePosixPath as P

    assert mod._is_attachment(P("ab") / ("ab" + "c" * 38))
    assert mod._is_attachment(P("ab") / ("ab" + "c" * 62))
    assert not mod._is_attachment(P("ab") / "abcdef")
    assert not mod._is_attachment(P("ab") / ("AB" + "C" * 38))   # Grossbuchstaben
    assert not mod._is_attachment(P("abc") / ("ab" + "c" * 38))  # falsches Praefix
    assert not mod._is_attachment(P("ab") / "cd" / ("ab" + "c" * 38))
