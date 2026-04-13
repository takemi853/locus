"""
Generate monthly report from weekly reports (and daily logs as fallback).

Usage:
    uv run python monthly.py             # generate report for last month
    uv run python monthly.py 2026-04    # generate report for specific month
    uv run python monthly.py --force    # regenerate even if report already exists
"""

from __future__ import annotations

import os
os.environ["CLAUDE_INVOKED_BY"] = "monthly_report"

import argparse
import asyncio
import calendar
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from config import DAILY_DIR, WEEKLY_DIR, MONTHLY_DIR
from backends import load_backend

logging.basicConfig(
    filename=str(SCRIPTS_DIR / "monthly.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def is_last_day_of_month(d: date) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]


def report_path(year: int, month: int) -> Path:
    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
    return MONTHLY_DIR / f"{year:04d}-{month:02d}.md"


def collect_weekly_reports(year: int, month: int) -> list[str]:
    """Collect weekly reports that overlap with the given month."""
    reports = []
    if not WEEKLY_DIR.exists():
        return reports

    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    for weekly_file in sorted(WEEKLY_DIR.glob("*.md")):
        try:
            week_start = date.fromisoformat(weekly_file.stem)
        except ValueError:
            continue
        week_end = week_start + timedelta(days=6)
        # Include if the week overlaps with the month
        if week_start <= last_day and week_end >= first_day:
            content = weekly_file.read_text(encoding="utf-8").strip()
            if content:
                reports.append(f"### 週次レポート ({week_start} 〜 {week_end})\n\n{content}")

    return reports


def collect_daily_logs(year: int, month: int) -> list[str]:
    """Fallback: collect daily logs for the month if no weekly reports exist."""
    logs = []
    last_day = calendar.monthrange(year, month)[1]
    for day in range(1, last_day + 1):
        log_path = DAILY_DIR / f"{year:04d}-{month:02d}-{day:02d}.md"
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8").strip()
            if content:
                logs.append(f"### {year}-{month:02d}-{day:02d}\n\n{content}")
    return logs


async def generate_monthly_report(year: int, month: int, source_content: str, source_type: str) -> str:
    """Use LLM to generate a monthly report."""
    backend = load_backend()
    month_name = date(year, month, 1).strftime("%Y年%m月")

    prompt = f"""以下は {month_name} の{source_type}です。

これを読んで、月次レポートを日本語で作成してください。

## 出力フォーマット

```markdown
---
title: "Monthly Report {year}-{month:02d}"
period: "{year}-{month:02d}"
tags: [monthly]
created: {date.today().isoformat()}
---

# 月次レポート: {month_name}

## 今月のサマリ
（今月全体を2〜3文で振り返る）

## プロジェクト別の成果
（プロジェクトごとに今月の成果・進捗をまとめる）

### `プロジェクト名`
- 達成したこと
- 残っていること

## 今月の学び・気づき
- 技術的な発見
- プロセス・習慣の改善
- 失敗から学んだこと

## 数値・定量サマリ
（できる範囲で: 作業日数、主要な成果物、解決した課題数など）

## 来月の目標
- 具体的なゴール（3つ以内）

## 総合振り返り
（今月の働き方・成長・課題を率直に評価）
```

## ソースデータ

{source_content}
"""

    try:
        response = await backend.text(prompt)
        return response
    except Exception as e:
        logging.error("LLM error: %s", e)
        return f"ERROR: {e}"


def main():
    parser = argparse.ArgumentParser(description="Generate monthly report")
    parser.add_argument("month", nargs="?", help="Target month as YYYY-MM. Default: last month.")
    parser.add_argument("--force", action="store_true", help="Regenerate even if report already exists")
    args = parser.parse_args()

    if args.month:
        year, month = map(int, args.month.split("-"))
    else:
        today = datetime.now(timezone.utc).astimezone().date()
        # Guard: only generate on the last day of the month (launchd runs on days 28-31)
        if not args.force and not is_last_day_of_month(today):
            logging.info("Not the last day of the month (%s), skipping.", today)
            return
        # Generate for the current month (today is last day)
        year, month = today.year, today.month

    out_path = report_path(year, month)

    if out_path.exists() and not args.force:
        logging.info("Report already exists: %s (use --force to regenerate)", out_path)
        print(f"Report already exists: {out_path}")
        return

    # Prefer weekly reports; fall back to daily logs
    weekly_reports = collect_weekly_reports(year, month)
    if weekly_reports:
        source_content = "\n\n---\n\n".join(weekly_reports)
        source_type = "週次レポート"
        logging.info("Using %d weekly reports for %d-%02d", len(weekly_reports), year, month)
    else:
        daily_logs = collect_daily_logs(year, month)
        if not daily_logs:
            logging.info("No data found for %d-%02d", year, month)
            print(f"No data found for {year}-{month:02d}")
            return
        source_content = "\n\n---\n\n".join(daily_logs)
        source_type = "dailyログ"
        logging.info("Using %d daily logs for %d-%02d (no weekly reports found)", len(daily_logs), year, month)

    print(f"Generating monthly report: {year}-{month:02d} (source: {source_type})...")
    report = asyncio.run(generate_monthly_report(year, month, source_content, source_type))

    out_path.write_text(report, encoding="utf-8")
    logging.info("Written: %s", out_path)
    print(f"Done: {out_path}")


if __name__ == "__main__":
    main()
