"""Tests for scripts/utils.py."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import utils


class TestSlugify:
    def test_simple(self):
        assert utils.slugify("Hello World") == "hello-world"

    def test_collapses_spaces_and_underscores(self):
        assert utils.slugify("foo  __  bar") == "foo-bar"

    def test_strips_leading_trailing_dashes(self):
        assert utils.slugify("---foo---") == "foo"

    def test_strips_punctuation(self):
        assert utils.slugify("A/B! Test?") == "ab-test"

    def test_lowercases(self):
        assert utils.slugify("CamelCase") == "camelcase"


class TestExtractWikilinks:
    def test_finds_links(self):
        content = "see [[wiki/foo]] and [[wiki/bar]]"
        assert utils.extract_wikilinks(content) == ["wiki/foo", "wiki/bar"]

    def test_handles_no_links(self):
        assert utils.extract_wikilinks("just text") == []

    def test_includes_duplicates(self):
        content = "[[a]] [[a]] [[b]]"
        assert utils.extract_wikilinks(content) == ["a", "a", "b"]

    def test_does_not_match_single_brackets(self):
        assert utils.extract_wikilinks("[not a link]") == []


class TestFileHash:
    def test_deterministic(self, tmp_path: Path):
        f = tmp_path / "x.txt"
        f.write_bytes(b"hello")
        h1 = utils.file_hash(f)
        h2 = utils.file_hash(f)
        assert h1 == h2

    def test_matches_sha256_prefix(self, tmp_path: Path):
        f = tmp_path / "x.txt"
        f.write_bytes(b"hello")
        expected = hashlib.sha256(b"hello").hexdigest()[:16]
        assert utils.file_hash(f) == expected

    def test_different_content(self, tmp_path: Path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_bytes(b"foo")
        b.write_bytes(b"bar")
        assert utils.file_hash(a) != utils.file_hash(b)


class TestListRawFiles:
    """Regression: index.md and README.md must NOT appear in the daily-log list."""

    def test_excludes_index_md(self, kb_dir: Path):
        daily = kb_dir / "knowledge" / "daily"
        (daily / "2026-01-01.md").write_text("log", encoding="utf-8")
        (daily / "index.md").write_text("idx", encoding="utf-8")

        names = [p.name for p in utils.list_raw_files()]
        assert "index.md" not in names
        assert "2026-01-01.md" in names

    def test_excludes_readme_md(self, kb_dir: Path):
        daily = kb_dir / "knowledge" / "daily"
        (daily / "2026-01-01.md").write_text("log", encoding="utf-8")
        (daily / "README.md").write_text("readme", encoding="utf-8")

        names = [p.name for p in utils.list_raw_files()]
        assert "README.md" not in names

    def test_returns_sorted(self, kb_dir: Path):
        daily = kb_dir / "knowledge" / "daily"
        for name in ("2026-03-05.md", "2026-01-12.md", "2026-02-08.md"):
            (daily / name).write_text("x", encoding="utf-8")

        names = [p.name for p in utils.list_raw_files()]
        assert names == sorted(names)

    def test_empty_when_dir_missing(self, kb_dir: Path, monkeypatch):
        monkeypatch.setattr(utils, "DAILY_DIR", kb_dir / "does-not-exist")
        assert utils.list_raw_files() == []


class TestStateLoad:
    def test_returns_default_when_missing(self, kb_dir: Path):
        # Remove the state.json the fixture created.
        (kb_dir / "scripts" / "state.json").unlink()
        state = utils.load_state()
        assert state == {"ingested": {}, "query_count": 0, "last_lint": None, "total_cost": 0.0}

    def test_round_trip(self, kb_dir: Path):
        utils.save_state({"ingested": {"x.md": {"hash": "abc"}}, "query_count": 7})
        loaded = utils.load_state()
        assert loaded["query_count"] == 7
        assert loaded["ingested"]["x.md"]["hash"] == "abc"


class TestWikiArticleExists:
    def test_true_for_existing(self, kb_dir: Path):
        wiki = kb_dir / "knowledge" / "wiki"
        (wiki / "foo.md").write_text("# foo", encoding="utf-8")
        assert utils.wiki_article_exists("wiki/foo")

    def test_false_for_missing(self, kb_dir: Path):
        assert not utils.wiki_article_exists("wiki/nope")

    def test_excludes_extension(self, kb_dir: Path):
        # The function expects no .md suffix in the link.
        wiki = kb_dir / "knowledge" / "wiki"
        (wiki / "bar.md").write_text("# bar", encoding="utf-8")
        # Link with .md should NOT match (function appends .md itself).
        assert not utils.wiki_article_exists("wiki/bar.md")
