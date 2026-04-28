"""
Auto-fix mechanically resolvable lint issues.

Handles two categories that lint.py marks as auto-fixable or trivially
mechanical:

  1. Stale link migration:
     [[concepts/X]] → [[wiki/X]]                     (if wiki/X.md exists)
     [[connections/X]] → [[wiki/X]]                  (same)
     [[inbox/concepts/X]] → [[inbox/wiki/X]]         (same)
     [[inbox/connections/X]] → [[inbox/wiki/X]]      (same)

  2. Missing backlinks:
     If A links to B but B doesn't link to A, append a "## Related" section
     entry on B pointing to A.

The fixer is conservative — it never deletes, only rewrites/appends, and
ALWAYS skips changes when the target referenced doesn't exist on disk
(ambiguous fix is left for the human).

Usage:
    uv run python lint_fix.py            # dry-run, prints planned changes
    uv run python lint_fix.py --apply    # actually write changes
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from config import KNOWLEDGE_DIR
from utils import extract_wikilinks, list_wiki_articles, wiki_article_exists


# ── Stale link migration ─────────────────────────────────────────────────

# Map: deprecated prefix → preferred prefix. Order matters — longer prefixes
# first so "inbox/concepts/X" is rewritten to "inbox/wiki/X" rather than
# "concepts/X" being mistakenly stripped.
LEGACY_PREFIX_MAP: list[tuple[str, str]] = [
    ("inbox/concepts/", "inbox/wiki/"),
    ("inbox/connections/", "inbox/wiki/"),
    ("concepts/", "wiki/"),
    ("connections/", "wiki/"),
]


def _migrate_link(link: str) -> str | None:
    """Return rewritten link if it should migrate AND the target exists.

    Returns None if no migration applies or the target doesn't exist.
    """
    for old, new in LEGACY_PREFIX_MAP:
        if link.startswith(old):
            candidate = new + link[len(old):]
            if wiki_article_exists(candidate):
                return candidate
            return None
    return None


def fix_stale_links(apply: bool) -> int:
    """Rewrite legacy [[concepts/X]] etc. into [[wiki/X]] where possible."""
    changes = 0
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        new_content = content
        replaced_in_file = 0

        # Find each unique legacy link in this file.
        for link in set(extract_wikilinks(content)):
            new_link = _migrate_link(link)
            if new_link is None or new_link == link:
                continue
            old_token = f"[[{link}]]"
            new_token = f"[[{new_link}]]"
            count = new_content.count(old_token)
            if count == 0:
                continue
            new_content = new_content.replace(old_token, new_token)
            replaced_in_file += count
            print(f"  {article.relative_to(KNOWLEDGE_DIR)}: [[{link}]] → [[{new_link}]] ({count}×)")

        if replaced_in_file and apply:
            article.write_text(new_content, encoding="utf-8")
        changes += replaced_in_file
    return changes


# ── Missing backlinks ────────────────────────────────────────────────────

RELATED_HEADER = "## Related"
RELATED_AUTO_MARKER = "<!-- backlinks: auto-added by lint_fix.py -->"


def _add_backlink(target_path: Path, source_link: str) -> bool:
    """Append a backlink to target. Returns True if file content was modified.

    Adds a fenced auto-managed block under "## Related" so subsequent runs
    are idempotent.
    """
    content = target_path.read_text(encoding="utf-8")
    backlink_token = f"[[{source_link}]]"

    # Already linked? Skip (defensive — the lint check should have caught this,
    # but a dirty edit could have desynced things).
    if backlink_token in content:
        return False

    # Locate or create the auto-managed block.
    auto_block_re = re.compile(
        rf"({re.escape(RELATED_AUTO_MARKER)}\n)(.*?)(\n<!-- /backlinks -->)",
        re.DOTALL,
    )
    m = auto_block_re.search(content)
    if m:
        existing = m.group(2)
        if backlink_token in existing:
            return False
        new_block = m.group(1) + (existing + f"\n- {backlink_token}").lstrip("\n") + m.group(3)
        new_content = content[:m.start()] + new_block + content[m.end():]
    else:
        # Append a new auto-managed block at end of file.
        new_block = (
            f"\n\n{RELATED_HEADER}\n\n"
            f"{RELATED_AUTO_MARKER}\n"
            f"- {backlink_token}\n"
            f"<!-- /backlinks -->\n"
        )
        # Avoid duplicate "## Related" if one already exists; merge instead.
        if RELATED_HEADER in content:
            new_block = (
                f"\n{RELATED_AUTO_MARKER}\n"
                f"- {backlink_token}\n"
                f"<!-- /backlinks -->\n"
            )
            # Insert just after the first "## Related" header line.
            related_idx = content.find(RELATED_HEADER)
            insert_at = content.find("\n", related_idx) + 1
            new_content = content[:insert_at] + new_block + content[insert_at:]
        else:
            new_content = content.rstrip() + new_block

    target_path.write_text(new_content, encoding="utf-8")
    return True


def fix_missing_backlinks(apply: bool) -> int:
    """For every A→B asymmetric link, add reciprocal entry on B."""
    changes = 0
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(KNOWLEDGE_DIR)
        source_link = str(rel).replace(".md", "").replace("\\", "/")

        for link in set(extract_wikilinks(content)):
            if link.startswith("daily/"):
                continue
            target_path = KNOWLEDGE_DIR / f"{link}.md"
            if not target_path.exists():
                continue  # broken link, not our problem
            target_content = target_path.read_text(encoding="utf-8")
            if f"[[{source_link}]]" in target_content:
                continue
            print(f"  {link}.md ← backlink to [[{source_link}]]")
            if apply:
                if _add_backlink(target_path, source_link):
                    changes += 1
            else:
                changes += 1
    return changes


# ── CLI ──────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually write changes (default: dry-run)")
    parser.add_argument("--only", choices=["links", "backlinks"], help="Run only one fixer")
    args = parser.parse_args()

    print(f"[lint_fix] mode = {'APPLY' if args.apply else 'DRY-RUN'}")

    total = 0
    if args.only in (None, "links"):
        print("\n== Stale link migration ==")
        total += fix_stale_links(args.apply)
    if args.only in (None, "backlinks"):
        print("\n== Missing backlinks ==")
        total += fix_missing_backlinks(args.apply)

    print(f"\nTotal {'applied' if args.apply else 'planned'}: {total} change(s)")
    if not args.apply and total:
        print("Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
