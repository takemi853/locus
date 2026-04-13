"""
Generate weekly report from daily logs.
Week runs Saturday through Friday.

Usage:
    uv run python weekly.py              # generate report for the most recently completed Sat-Fri week
    uv run python weekly.py 2026-04-11  # generate report for the week containing this date
    uv run python weekly.py --force     # regenerate even if report already exists
"""

from __future__ import annotations

import os
os.environ["CLAUDE_INVOKED_BY"] = "weekly_report"

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import re

from config import DAILY_DIR, WIKI_DIR, WEEKLY_DIR, PROJECTS_DIR
from backends import load_backend

STALE_DAYS = 30  # この日数以上更新されていない記事を「陳腐化」とみなす

CC_DOCS_DIR = PROJECTS_DIR / "claude-code" / "docs"

logging.basicConfig(
    filename=str(SCRIPTS_DIR / "weekly.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def week_range(anchor: date) -> tuple[date, date]:
    """Return (saturday, friday) for the Sat-Fri week containing anchor.

    If anchor is Saturday, returns that week (anchor to anchor+6).
    Otherwise returns the most recent Saturday before anchor.
    """
    # weekday(): Mon=0, Tue=1, ..., Sat=5, Sun=6
    days_since_saturday = (anchor.weekday() - 5) % 7
    saturday = anchor - timedelta(days=days_since_saturday)
    friday = saturday + timedelta(days=6)
    return saturday, friday


def week_id(saturday: date) -> str:
    """Return a unique week identifier like '2026-W15-sat' for the week starting on saturday."""
    # Use ISO week number but note our week starts Saturday, not Monday
    return f"{saturday.strftime('%Y')}-W{saturday.isocalendar()[1]:02d}-sat{saturday.strftime('%m%d')}"


def report_path(saturday: date) -> Path:
    """Return the output path for a weekly report."""
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    return WEEKLY_DIR / f"{saturday.strftime('%Y-%m-%d')}.md"


def collect_stale_articles(today: date | None = None) -> list[dict]:
    """wiki/ と inbox/wiki/ から STALE_DAYS 以上更新されていない記事を返す。"""
    if today is None:
        today = datetime.now(timezone.utc).astimezone().date()
    if not WIKI_DIR.exists():
        return []

    stale = []
    dirs_to_check = [WIKI_DIR]
    inbox_wiki = WIKI_DIR.parent / "inbox" / "wiki"
    if inbox_wiki.exists():
        dirs_to_check.append(inbox_wiki)

    for wiki_dir in dirs_to_check:
        for md_file in sorted(wiki_dir.glob("*.md")):
            try:
                header = md_file.read_bytes()[:512].decode("utf-8", errors="replace")
            except OSError:
                continue
            # frontmatter の updated: フィールドを抽出
            updated_match = re.search(r"^updated:\s*(\d{4}-\d{2}-\d{2})", header, re.MULTILINE)
            if not updated_match:
                continue
            try:
                updated = date.fromisoformat(updated_match.group(1))
            except ValueError:
                continue
            days_old = (today - updated).days
            if days_old >= STALE_DAYS:
                title_match = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', header, re.MULTILINE)
                title = title_match.group(1) if title_match else md_file.stem
                stale.append({
                    "slug": md_file.stem,
                    "title": title,
                    "updated": updated.isoformat(),
                    "days_old": days_old,
                    "in_inbox": wiki_dir == inbox_wiki,
                })

    stale.sort(key=lambda x: x["days_old"], reverse=True)
    return stale


def collect_cc_docs(saturday: date, friday: date) -> list[dict]:
    """Collect Claude Code study docs created during the week."""
    if not CC_DOCS_DIR.exists():
        return []

    docs = []
    for md_file in sorted(CC_DOCS_DIR.glob("*.md")):
        try:
            mtime = date.fromtimestamp(md_file.stat().st_mtime)
        except OSError:
            continue
        if saturday <= mtime <= friday:
            content = md_file.read_text(encoding="utf-8").strip()
            # Extract version and one-line summary from frontmatter/content
            version = md_file.stem
            summary = ""
            for line in content.splitlines():
                if line.startswith("## 一言サマリ"):
                    continue
                if summary == "" and line.strip() and not line.startswith("#") and not line.startswith("---") and ":" not in line[:20]:
                    summary = line.strip()
                    break
            docs.append({"version": version, "summary": summary, "path": str(md_file)})
    return docs


def collect_daily_logs(saturday: date, friday: date) -> dict[date, str]:
    """Read daily logs for the week range. Returns {date: content}."""
    logs = {}
    current = saturday
    while current <= friday:
        log_path = DAILY_DIR / f"{current.strftime('%Y-%m-%d')}.md"
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8").strip()
            if content:
                logs[current] = content
        current += timedelta(days=1)
    return logs


async def generate_weekly_report(
    saturday: date,
    friday: date,
    logs: dict[date, str],
    cc_docs: list[dict],
    stale_articles: list[dict] | None = None,
) -> str:
    """Use LLM to generate a weekly report from daily logs."""
    backend = load_backend()

    logs_text = "\n\n---\n\n".join(
        f"### {d.strftime('%Y-%m-%d (%A)')}\n\n{content}"
        for d, content in sorted(logs.items())
    )

    cc_section_format = ""
    cc_section_data = ""
    if cc_docs:
        cc_links = "\n".join(
            f"- [[projects/claude-code/docs/{d['version']}|{d['version']}]]: {d['summary']}"
            for d in cc_docs
        )
        cc_section_format = """
## Claude Code 今週の学び
（今週 /study で学んだバージョンとその要点。学んだことが自分のワークフローにどう影響するかを1〜2文で）
"""
        cc_section_data = f"""
## 今週学んだ Claude Code リリース

{cc_links}
"""

    # 陳腐化記事セクション
    stale_section_format = ""
    stale_section_data = ""
    if stale_articles:
        stale_list = "\n".join(
            f"- `{a['slug']}` — {a['title']}（最終更新: {a['updated']}, {a['days_old']}日前）"
            + (" [inbox]" if a["in_inbox"] else "")
            for a in stale_articles[:20]  # 最大20件
        )
        stale_section_format = f"""
## 要見直し記事（{STALE_DAYS}日以上未更新）
（以下の記事が古くなっています。内容が今も有効か、削除・更新すべきか一言コメントを）
"""
        stale_section_data = f"""
## 陳腐化記事リスト（{len(stale_articles)} 件）

{stale_list}
"""

    prompt = f"""以下は {saturday.strftime('%Y-%m-%d')}（土）〜 {friday.strftime('%Y-%m-%d')}（金）の1週間のdailyログです。

これを読んで、週次レポートを日本語で作成してください。

## 出力フォーマット

```markdown
---
title: "Weekly Report {saturday.strftime('%Y-%m-%d')} 〜 {friday.strftime('%Y-%m-%d')}"
period: "{saturday.strftime('%Y-%m-%d')} / {friday.strftime('%Y-%m-%d')}"
tags: [weekly]
created: {date.today().isoformat()}
---

# 週次レポート: {saturday.strftime('%Y-%m-%d')} 〜 {friday.strftime('%Y-%m-%d')}

## 今週のサマリ
（2〜3文で今週を一言で表す）

## プロジェクト別の進捗
（作業したプロジェクトごとに箇条書き）

### `プロジェクト名`
- 何をしたか
- 何を決めたか
{cc_section_format}
## 今週の学び
- 発見・気づき・ハマったポイント

## 来週やること
- 具体的なネクストアクション

## 振り返り
（良かった点・改善点を率直に）
{stale_section_format}
```

## dailyログ

{logs_text}
{cc_section_data}{stale_section_data}"""

    try:
        response = await backend.text(prompt)
        return response
    except Exception as e:
        logging.error("LLM error: %s", e)
        return f"ERROR: {e}"


def main():
    parser = argparse.ArgumentParser(description="Generate weekly report from daily logs")
    parser.add_argument("date", nargs="?", help="Any date in the target week (YYYY-MM-DD). Default: last completed week.")
    parser.add_argument("--force", action="store_true", help="Regenerate even if report already exists")
    args = parser.parse_args()

    if args.date:
        anchor = date.fromisoformat(args.date)
    else:
        # Default: most recently completed Sat-Fri week (i.e., last Friday or earlier)
        today = datetime.now(timezone.utc).astimezone().date()
        # Go back to last Friday
        days_since_friday = (today.weekday() - 4) % 7
        if days_since_friday == 0:
            anchor = today  # today is Friday
        else:
            anchor = today - timedelta(days=days_since_friday)

    saturday, friday = week_range(anchor)
    out_path = report_path(saturday)

    if out_path.exists() and not args.force:
        logging.info("Report already exists: %s (use --force to regenerate)", out_path)
        print(f"Report already exists: {out_path}")
        return

    logs = collect_daily_logs(saturday, friday)
    if not logs:
        logging.info("No daily logs found for %s to %s", saturday, friday)
        print(f"No daily logs found for {saturday} to {friday}")
        return

    cc_docs = collect_cc_docs(saturday, friday)
    stale_articles = collect_stale_articles()

    logging.info(
        "Generating weekly report: %s to %s (%d days of logs, %d CC docs, %d stale articles)",
        saturday, friday, len(logs), len(cc_docs), len(stale_articles),
    )
    print(f"Generating weekly report: {saturday} to {friday} "
          f"({len(logs)} days of logs, {len(cc_docs)} CC docs, {len(stale_articles)} stale articles)...")

    report = asyncio.run(generate_weekly_report(saturday, friday, logs, cc_docs, stale_articles))

    out_path.write_text(report, encoding="utf-8")
    logging.info("Written: %s", out_path)
    print(f"Done: {out_path}")


if __name__ == "__main__":
    main()
