"""
Import Claude Code release notes and articles from claude_code_feed into the knowledge base.

Reads data/releases.json from claude_code_feed and generates:
  knowledge/projects/claude-code/<version>.md  — per-version release notes
  knowledge/projects/claude-code/index.md      — version list (latest first)

Usage:
    uv run python import_cc_feed.py              # import new/changed releases only
    uv run python import_cc_feed.py --all        # reimport all releases
    uv run python import_cc_feed.py --dry-run    # show what would be imported
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from config import PROJECTS_DIR

CC_FEED_DIR = Path("/Users/takemi/Projects/app/claude_code_feed")
RELEASES_JSON = CC_FEED_DIR / "data" / "releases.json"
IMPORT_STATE_FILE = SCRIPTS_DIR / "cc_feed_import_state.json"

CLAUDE_CODE_KB_DIR = PROJECTS_DIR / "claude-code"
RELEASES_DIR = CLAUDE_CODE_KB_DIR / "releases"
DOCS_DIR = CLAUDE_CODE_KB_DIR / "docs"


# ── state helpers ─────────────────────────────────────────────────────

def load_import_state() -> dict:
    if IMPORT_STATE_FILE.exists():
        try:
            return json.loads(IMPORT_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"imported": {}}


def save_import_state(state: dict) -> None:
    IMPORT_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def release_hash(release: dict) -> str:
    key = json.dumps({
        "tag": release.get("tag"),
        "summary_ja": release.get("summary_ja", ""),
        "importance": release.get("importance", ""),
    }, ensure_ascii=False)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ── article generation ────────────────────────────────────────────────

def importance_badge(importance: str) -> str:
    return {"high": "🔴 必読", "medium": "🟡 注目", "low": "🟢 参考"}.get(importance, importance)


def make_release_article(release: dict) -> str:
    tag = release["tag"]
    published = release.get("published_at", "")[:10]
    importance = release.get("importance", "")
    tags = release.get("tags", [])
    summary_ja = release.get("summary_ja", "")
    body_ja = release.get("body_ja", "")
    usage_ja = release.get("usage_ja", "")
    url = release.get("url", "")

    tags_yaml = "\n".join(f'  - "{t}"' for t in tags) if tags else '  - "release"'

    usage_section = f"\n## 使い方・実践ガイド\n\n{usage_ja}\n" if usage_ja else ""

    return f"""---
title: "Claude Code {tag}"
version: "{tag}"
published: {published}
importance: "{importance}"
tags:
  - "claude-code"
  - "release"
{tags_yaml}
source: "{url}"
---

# Claude Code {tag}

> {importance_badge(importance)} — {published}

## サマリ

{summary_ja}

## 変更内容

{body_ja}
{usage_section}
## リンク

- [GitHub Release]({url})
- [[projects/claude-code/releases/index]] — バージョン一覧に戻る
"""


def make_index_article(releases: list[dict]) -> str:
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    rows = []
    for r in releases:
        if r.get("prerelease"):
            continue
        tag = r["tag"]
        published = r.get("published_at", "")[:10]
        importance = r.get("importance", "")
        badge = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(importance, "")
        summary = r.get("summary_ja", "").split("。")[0] + "。" if r.get("summary_ja") else ""
        rows.append(f"| [[projects/claude-code/releases/{tag}\\|{tag}]] | {badge} | {published} | {summary} |")

    table = "\n".join(rows)
    latest = next((r for r in releases if not r.get("prerelease")), {})
    latest_tag = latest.get("tag", "不明")
    latest_date = latest.get("published_at", "")[:10]

    return f"""---
title: "Claude Code バージョン一覧"
tags: ["claude-code", "release", "index"]
updated: {today}
---

# Claude Code バージョン一覧

最終更新: {today} / 最新版: **{latest_tag}** ({latest_date})

## リリース一覧

| バージョン | 重要度 | リリース日 | サマリ |
|---|---|---|---|
{table}
"""


# ── main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import Claude Code feed into knowledge base")
    parser.add_argument("--all", action="store_true", help="Reimport all releases")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be imported")
    args = parser.parse_args()

    if not RELEASES_JSON.exists():
        print(f"releases.json not found: {RELEASES_JSON}")
        sys.exit(1)

    data = json.loads(RELEASES_JSON.read_text(encoding="utf-8"))
    releases = data.get("releases", [])
    stable = [r for r in releases if not r.get("prerelease", False)]

    CLAUDE_CODE_KB_DIR.mkdir(parents=True, exist_ok=True)
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    state = load_import_state()
    imported = state.get("imported", {})

    to_import = []
    for release in stable:
        tag = release["tag"]
        h = release_hash(release)
        if args.all or imported.get(tag) != h:
            to_import.append(release)

    if not to_import:
        print("Nothing to import — all releases up to date.")
        return

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Releases to import ({len(to_import)}):")
    for r in to_import:
        print(f"  - {r['tag']} ({r.get('importance', '?')})")

    if args.dry_run:
        return

    # Write per-version articles
    for release in to_import:
        tag = release["tag"]
        article = make_release_article(release)
        out_path = RELEASES_DIR / f"{tag}.md"
        out_path.write_text(article, encoding="utf-8")
        imported[tag] = release_hash(release)
        print(f"  Written: {out_path.name}")

    # Always regenerate index
    index_content = make_index_article(stable)
    index_path = RELEASES_DIR / "index.md"
    index_path.write_text(index_content, encoding="utf-8")
    print(f"  Updated: {index_path.name}")

    state["imported"] = imported
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_import_state(state)
    print(f"\nDone. {len(to_import)} releases imported.")


if __name__ == "__main__":
    main()
