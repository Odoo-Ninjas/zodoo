"""Tests for per-service image tag computation in lib_zodoo_registry."""

from __future__ import annotations

import textwrap

import pytest

from zodoo import lib_zodoo_registry as mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeConfig:
    """Minimal stand-in for click_config.Config."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _write(path, content=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# _get_directory_content_hash
# ---------------------------------------------------------------------------


class TestGetDirectoryContentHash:
    def test_returns_none_for_missing_dir(self, tmp_path):
        assert mod._get_directory_content_hash(tmp_path / "nope") is None

    def test_deterministic(self, tmp_path):
        _write(tmp_path / "a.txt", "hello")
        _write(tmp_path / "b.txt", "world")
        h1 = mod._get_directory_content_hash(tmp_path)
        h2 = mod._get_directory_content_hash(tmp_path)
        assert h1 == h2

    def test_changes_when_content_changes(self, tmp_path):
        _write(tmp_path / "a.txt", "v1")
        h1 = mod._get_directory_content_hash(tmp_path)
        _write(tmp_path / "a.txt", "v2")
        h2 = mod._get_directory_content_hash(tmp_path)
        assert h1 != h2

    def test_excludes_pycache(self, tmp_path):
        _write(tmp_path / "a.txt", "hello")
        h1 = mod._get_directory_content_hash(tmp_path)
        _write(tmp_path / "__pycache__" / "mod.pyc", "bytecode")
        h2 = mod._get_directory_content_hash(tmp_path)
        assert h1 == h2

    def test_excludes_buildsettings_env(self, tmp_path):
        _write(tmp_path / "Dockerfile", "FROM ubuntu")
        h1 = mod._get_directory_content_hash(tmp_path)
        _write(tmp_path / "buildsettings.env", "FOO=bar")
        h2 = mod._get_directory_content_hash(tmp_path)
        assert h1 == h2

    def test_excludes_zodoo_src_dir(self, tmp_path):
        _write(tmp_path / "Dockerfile", "FROM ubuntu")
        h1 = mod._get_directory_content_hash(tmp_path)
        _write(tmp_path / "zodoo_src" / "setup.py", "install")
        h2 = mod._get_directory_content_hash(tmp_path)
        assert h1 == h2


# ---------------------------------------------------------------------------
# _get_snippets_used
# ---------------------------------------------------------------------------


class TestGetSnippetsUsed:
    def test_finds_snippets(self, tmp_path):
        _write(
            tmp_path / "Dockerfile",
            "#___SNIPPET_ZODOO___\n#___SNIPPET_APT_INSTALL___\n",
        )
        result = mod._get_snippets_used(tmp_path)
        assert result == {"ZODOO", "APT_INSTALL"}

    def test_empty_when_no_snippets(self, tmp_path):
        _write(tmp_path / "Dockerfile", "FROM ubuntu\nRUN echo hi\n")
        assert mod._get_snippets_used(tmp_path) == set()

    def test_no_dockerfiles(self, tmp_path):
        _write(tmp_path / "readme.md", "nothing")
        assert mod._get_snippets_used(tmp_path) == set()


# ---------------------------------------------------------------------------
# _get_snippet_hashes
# ---------------------------------------------------------------------------


class TestGetSnippetHashes:
    def test_hash_changes_with_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "IMAGES_DIR", tmp_path)
        snippets_dir = tmp_path / "common_snippets"
        _write(snippets_dir / "zodoo", "v1")
        h1 = mod._get_snippet_hashes({"ZODOO"})
        _write(snippets_dir / "zodoo", "v2")
        h2 = mod._get_snippet_hashes({"ZODOO"})
        assert h1 != h2

    def test_missing_snippet_ignored(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "IMAGES_DIR", tmp_path)
        (tmp_path / "common_snippets").mkdir()
        # Should not raise
        mod._get_snippet_hashes({"NONEXISTENT"})


# ---------------------------------------------------------------------------
# _load_registry_tag_config
# ---------------------------------------------------------------------------


class TestLoadRegistryTagConfig:
    def test_returns_none_when_missing(self, tmp_path):
        assert mod._load_registry_tag_config(tmp_path) is None

    def test_loads_yaml(self, tmp_path):
        _write(
            tmp_path / "registry_tag.yml",
            textwrap.dedent("""\
                settings:
                  - POSTGRES_VERSION
                tag_prefix:
                  - POSTGRES_VERSION
            """),
        )
        cfg = mod._load_registry_tag_config(tmp_path)
        assert cfg["settings"] == ["POSTGRES_VERSION"]
        assert cfg["tag_prefix"] == ["POSTGRES_VERSION"]


# ---------------------------------------------------------------------------
# _resolve_image_dir
# ---------------------------------------------------------------------------


class TestResolveImageDir:
    def test_direct_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "IMAGES_DIR", tmp_path)
        (tmp_path / "postgres").mkdir()
        assert mod._resolve_image_dir("postgres") == tmp_path / "postgres"

    def test_alias_cronjobshell(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "IMAGES_DIR", tmp_path)
        (tmp_path / "cronjobs").mkdir()
        assert mod._resolve_image_dir("cronjobshell") == tmp_path / "cronjobs"

    def test_returns_none_for_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "IMAGES_DIR", tmp_path)
        assert mod._resolve_image_dir("nonexistent") is None


# ---------------------------------------------------------------------------
# _resolve_extra_path
# ---------------------------------------------------------------------------


class TestResolveExtraPath:
    def test_substitutes_variables(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "IMAGES_DIR", tmp_path)
        config = FakeConfig(odoo_version_int="18")
        result = mod._resolve_extra_path(
            "odoo/config/${odoo_version_int}/Dockerfile", config
        )
        assert result == tmp_path / "odoo" / "config" / "18" / "Dockerfile"


# ---------------------------------------------------------------------------
# get_zodoo_image_tag_for_service — integration-style
# ---------------------------------------------------------------------------


class TestGetZodooImageTagForService:
    @pytest.fixture()
    def images_dir(self, tmp_path, monkeypatch):
        """Set up a minimal images dir with common_snippets and one image."""
        monkeypatch.setattr(mod, "IMAGES_DIR", tmp_path)
        (tmp_path / "common_snippets").mkdir()
        # Clear the lru_cache between tests
        mod._get_zodoo_src_hash.cache_clear()
        return tmp_path

    def test_fallback_when_no_registry_tag_yml(self, images_dir, monkeypatch):
        (images_dir / "myimg").mkdir()
        config = FakeConfig(
            odoo_version="18",
            ODOO_PYTHON_VERSION="3.12.11",
            WORKING_DIR=images_dir,
        )
        # Patch the global tag to return a known value
        monkeypatch.setattr(mod, "get_zodoo_image_tag", lambda c: "global-tag")
        tag = mod.get_zodoo_image_tag_for_service(config, "myimg")
        assert tag == "global-tag"

    def test_postgres_tag_uses_version(self, images_dir):
        pg = images_dir / "postgres"
        pg.mkdir()
        _write(pg / "Dockerfile.17", "FROM postgres:17")
        _write(
            pg / "registry_tag.yml",
            textwrap.dedent("""\
                settings:
                  - POSTGRES_VERSION
                tag_prefix:
                  - POSTGRES_VERSION
            """),
        )
        config = FakeConfig(POSTGRES_VERSION="17", WORKING_DIR=images_dir)
        tag = mod.get_zodoo_image_tag_for_service(config, "postgres")
        assert tag.startswith("17-")
        assert len(tag) == 11  # "17-" + 8 hex chars

    def test_postgres_tag_changes_with_version(self, images_dir):
        pg = images_dir / "postgres"
        pg.mkdir()
        _write(pg / "Dockerfile.17", "FROM postgres:17")
        _write(
            pg / "registry_tag.yml",
            textwrap.dedent("""\
                settings:
                  - POSTGRES_VERSION
                tag_prefix:
                  - POSTGRES_VERSION
            """),
        )
        cfg17 = FakeConfig(POSTGRES_VERSION="17", WORKING_DIR=images_dir)
        cfg16 = FakeConfig(POSTGRES_VERSION="16", WORKING_DIR=images_dir)
        tag17 = mod.get_zodoo_image_tag_for_service(cfg17, "postgres")
        tag16 = mod.get_zodoo_image_tag_for_service(cfg16, "postgres")
        assert tag17 != tag16
        assert tag17.startswith("17-")
        assert tag16.startswith("16-")

    def test_tag_changes_when_dir_content_changes(self, images_dir):
        img = images_dir / "proxy"
        img.mkdir()
        _write(img / "Dockerfile", "FROM nginx:v1")
        _write(
            img / "registry_tag.yml",
            "settings: []\ntag_prefix: []\n",
        )
        config = FakeConfig(WORKING_DIR=images_dir)
        tag1 = mod.get_zodoo_image_tag_for_service(config, "proxy")
        _write(img / "Dockerfile", "FROM nginx:v2")
        tag2 = mod.get_zodoo_image_tag_for_service(config, "proxy")
        assert tag1 != tag2

    def test_zodoo_snippet_detected_and_hashed(self, images_dir):
        img = images_dir / "cronjobs"
        img.mkdir()
        _write(img / "Dockerfile", "#___SNIPPET_ZODOO___\nRUN echo hi\n")
        _write(
            img / "registry_tag.yml",
            "settings: []\ntag_prefix: []\n",
        )
        # Create zodoo src
        zodoo_src = images_dir / "zodoo" / "src"
        _write(zodoo_src / "setup.py", "v1")
        _write(images_dir / "common_snippets" / "zodoo", "snippet-v1")

        config = FakeConfig(WORKING_DIR=images_dir)
        tag1 = mod.get_zodoo_image_tag_for_service(config, "cronjobs")

        # Change zodoo source
        _write(zodoo_src / "setup.py", "v2")
        mod._get_zodoo_src_hash.cache_clear()
        tag2 = mod.get_zodoo_image_tag_for_service(config, "cronjobs")
        assert tag1 != tag2

    def test_no_prefix_gives_hash_only(self, images_dir):
        img = images_dir / "proxy"
        img.mkdir()
        _write(img / "Dockerfile", "FROM nginx")
        _write(
            img / "registry_tag.yml",
            "settings: []\ntag_prefix: []\n",
        )
        config = FakeConfig(WORKING_DIR=images_dir)
        tag = mod.get_zodoo_image_tag_for_service(config, "proxy")
        # No prefix → just the 8-char hash
        assert len(tag) == 8

    def test_project_files_hashed(self, images_dir):
        img = images_dir / "odoo"
        img.mkdir()
        _write(img / "Dockerfile", "FROM ubuntu")
        _write(
            img / "registry_tag.yml",
            textwrap.dedent("""\
                settings: []
                tag_prefix: []
                project_files:
                  - requirements.txt.all
            """),
        )
        working = images_dir / "project"
        working.mkdir()
        _write(working / "requirements.txt.all", "pkg==1.0")

        config = FakeConfig(WORKING_DIR=working)
        tag1 = mod.get_zodoo_image_tag_for_service(config, "odoo")

        _write(working / "requirements.txt.all", "pkg==2.0")
        tag2 = mod.get_zodoo_image_tag_for_service(config, "odoo")
        assert tag1 != tag2

    def test_project_globs_hashed(self, images_dir):
        img = images_dir / "odoo"
        img.mkdir()
        _write(img / "Dockerfile", "FROM ubuntu")
        _write(
            img / "registry_tag.yml",
            textwrap.dedent("""\
                settings: []
                tag_prefix: []
                project_globs:
                  - "**/Dockerfile.appendix"
            """),
        )
        working = images_dir / "project"
        working.mkdir()

        config = FakeConfig(WORKING_DIR=working)
        tag1 = mod.get_zodoo_image_tag_for_service(config, "odoo")

        _write(
            working / "mymod" / "Dockerfile.appendix", "RUN apt install foo"
        )
        tag2 = mod.get_zodoo_image_tag_for_service(config, "odoo")
        assert tag1 != tag2
