"""Tests for scripts/lint_fix.py."""

from __future__ import annotations

from pathlib import Path

import pytest

import lint_fix
import utils


class TestMigrateLink:
    """Pure-function tests for the legacy-prefix → new-prefix mapping."""

    def test_concepts_to_wiki(self, kb_dir: Path):
        (kb_dir / "knowledge" / "wiki" / "foo.md").write_text("x", encoding="utf-8")
        assert lint_fix._migrate_link("concepts/foo") == "wiki/foo"

    def test_connections_to_wiki(self, kb_dir: Path):
        (kb_dir / "knowledge" / "wiki" / "bar.md").write_text("x", encoding="utf-8")
        assert lint_fix._migrate_link("connections/bar") == "wiki/bar"

    def test_inbox_concepts_to_inbox_wiki(self, kb_dir: Path):
        target = kb_dir / "knowledge" / "inbox" / "wiki" / "baz.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        assert lint_fix._migrate_link("inbox/concepts/baz") == "inbox/wiki/baz"

    def test_returns_none_when_target_missing(self, kb_dir: Path):
        # No file created; migration would point at non-existent article.
        assert lint_fix._migrate_link("concepts/missing") is None

    def test_returns_none_for_non_legacy_links(self, kb_dir: Path):
        assert lint_fix._migrate_link("wiki/foo") is None
        assert lint_fix._migrate_link("daily/2026-01-01") is None

    def test_inbox_concepts_does_not_collide_with_concepts(self, kb_dir: Path):
        """`inbox/concepts/X` must rewrite to `inbox/wiki/X`, NOT just strip 'concepts/'."""
        # Create the inbox/wiki target so the migration can succeed.
        target = kb_dir / "knowledge" / "inbox" / "wiki" / "x.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        # Also create a wiki/x.md to make sure we don't accidentally pick it.
        (kb_dir / "knowledge" / "wiki" / "x.md").write_text("y", encoding="utf-8")
        assert lint_fix._migrate_link("inbox/concepts/x") == "inbox/wiki/x"


class TestAddBacklink:
    def test_creates_related_section_when_missing(self, kb_dir: Path):
        target = kb_dir / "knowledge" / "wiki" / "target.md"
        target.write_text("# Target\n\nbody", encoding="utf-8")

        modified = lint_fix._add_backlink(target, "wiki/source")
        assert modified is True
        content = target.read_text(encoding="utf-8")
        assert "## Related" in content
        assert "[[wiki/source]]" in content
        assert "<!-- backlinks: auto-added by lint_fix.py -->" in content

    def test_idempotent(self, kb_dir: Path):
        target = kb_dir / "knowledge" / "wiki" / "target.md"
        target.write_text("# Target\n\nbody", encoding="utf-8")

        first = lint_fix._add_backlink(target, "wiki/source")
        second = lint_fix._add_backlink(target, "wiki/source")
        assert first is True
        assert second is False  # already present

    def test_appends_to_existing_auto_block(self, kb_dir: Path):
        target = kb_dir / "knowledge" / "wiki" / "target.md"
        target.write_text("# Target\n\nbody", encoding="utf-8")

        lint_fix._add_backlink(target, "wiki/a")
        lint_fix._add_backlink(target, "wiki/b")
        content = target.read_text(encoding="utf-8")
        assert content.count("## Related") == 1  # not duplicated
        assert "[[wiki/a]]" in content
        assert "[[wiki/b]]" in content

    def test_skips_when_link_already_in_body(self, kb_dir: Path):
        target = kb_dir / "knowledge" / "wiki" / "target.md"
        target.write_text("# Target\n\nlinks to [[wiki/source]] inline.", encoding="utf-8")

        modified = lint_fix._add_backlink(target, "wiki/source")
        assert modified is False


class TestFixStaleLinks:
    def test_dry_run_does_not_modify(self, kb_dir: Path):
        wiki = kb_dir / "knowledge" / "wiki"
        (wiki / "foo.md").write_text("# foo", encoding="utf-8")
        article = wiki / "src.md"
        original = "see [[concepts/foo]]"
        article.write_text(original, encoding="utf-8")

        count = lint_fix.fix_stale_links(apply=False)
        assert count == 1
        # Content unchanged.
        assert article.read_text(encoding="utf-8") == original

    def test_apply_rewrites(self, kb_dir: Path):
        wiki = kb_dir / "knowledge" / "wiki"
        (wiki / "foo.md").write_text("# foo", encoding="utf-8")
        article = wiki / "src.md"
        article.write_text("see [[concepts/foo]] and [[concepts/foo]]", encoding="utf-8")

        count = lint_fix.fix_stale_links(apply=True)
        assert count == 2  # two occurrences in one file
        assert "[[wiki/foo]]" in article.read_text(encoding="utf-8")
        assert "[[concepts/foo]]" not in article.read_text(encoding="utf-8")

    def test_skips_when_target_missing(self, kb_dir: Path):
        wiki = kb_dir / "knowledge" / "wiki"
        article = wiki / "src.md"
        article.write_text("see [[concepts/missing]]", encoding="utf-8")

        count = lint_fix.fix_stale_links(apply=True)
        assert count == 0
        # Original preserved.
        assert "[[concepts/missing]]" in article.read_text(encoding="utf-8")
