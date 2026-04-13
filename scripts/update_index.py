"""
Regenerate the "最近の記事" table in knowledge/index.md from wiki/*.md frontmatter.

Usage:
    uv run python update_index.py           # update index.md in place
    uv run python update_index.py --dry-run  # print what would be written
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from config import INDEX_FILE, WIKI_DIR


def parse_frontmatter(content: str) -> dict[str, str]:
    """Extract YAML frontmatter key/value pairs (simple string fields only)."""
    m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = re.match(r'^(\w+):\s*"?([^"]*)"?\s*$', line)
        if kv:
            result[kv.group(1)] = kv.group(2).strip()
    return result


def extract_summary(content: str) -> str:
    """Return first non-empty, non-heading paragraph after the H1 heading."""
    body = re.sub(r"^---\n.*?\n---\n", "", content, count=1, flags=re.DOTALL)
    in_h1 = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not in_h1:
            in_h1 = True
            continue
        if in_h1 and stripped and not stripped.startswith("#") and not stripped.startswith("|"):
            # Strip markdown link syntax and truncate
            text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", stripped)
            text = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", text)
            return text[:80]
    return ""


def build_wiki_rows() -> list[tuple[str, str, str]]:
    """Return list of (slug, title, summary) sorted by updated date descending."""
    rows: list[tuple[str, str, str, str]] = []
    for md_file in sorted(WIKI_DIR.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        title = fm.get("title", md_file.stem)
        updated = fm.get("updated", "")
        summary = extract_summary(content)
        rows.append((md_file.stem, title, summary, updated))
    rows.sort(key=lambda r: r[3], reverse=True)
    return [(slug, title, summary) for slug, title, summary, _ in rows]


def build_table(rows: list[tuple[str, str, str]]) -> str:
    lines = ["## 最近の記事", "", "| 記事 | 概要 |", "|-----|------|"]
    for slug, title, summary in rows:
        lines.append(f"| [[wiki/{slug}\\|{title}]] | {summary} |")
    lines.append("")  # blank line before the following --- separator
    return "\n".join(lines)


def update_index(dry_run: bool = False) -> None:
    if not INDEX_FILE.exists():
        print(f"Error: {INDEX_FILE} not found", file=sys.stderr)
        sys.exit(1)

    content = INDEX_FILE.read_text(encoding="utf-8")

    # Replace the 最近の記事 section (from header to next --- or next ## section)
    pattern = re.compile(
        r"(## 最近の記事\n.*?)(?=\n---\n|\n## )",
        re.DOTALL,
    )

    rows = build_wiki_rows()
    new_table = build_table(rows)

    updated, count = pattern.subn(new_table, content)
    if count == 0:
        print("Warning: '## 最近の記事' section not found in index.md", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print(new_table)
        print(f"\n({len(rows)} wiki articles)")
        return

    INDEX_FILE.write_text(updated, encoding="utf-8")
    print(f"Updated index.md — {len(rows)} wiki articles listed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate knowledge/index.md wiki table")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing")
    args = parser.parse_args()
    update_index(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
