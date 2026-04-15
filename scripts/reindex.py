"""
Generate index pages from daily logs — no LLM, no side effects.

Outputs:
  knowledge/daily/index.md          — 日付一覧（逆順）
  knowledge/projects/<slug>.md      — プロジェクトごとのセッション一覧

各ページは大元の daily ログを wikilink で参照するだけで、内容を複製しない。

Usage:
    uv run python reindex.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DAILY_DIR, KNOWLEDGE_DIR, PROJECTS_DIR, today_iso

# ── パーサ ─────────────────────────────────────────────────────────────

def _extract_tldr(content: str) -> str:
    """TL;DR セクションの「プロジェクト別」行を短くまとめる。"""
    m = re.search(r"## TL;DR[^\n]*\n\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if not m:
        return ""
    text = m.group(1).strip()

    proj_m = re.search(r"\*\*プロジェクト別\*\*\n(.*?)(?=\n\*\*|\Z)", text, re.DOTALL)
    if proj_m:
        lines = [l.strip() for l in proj_m.group(1).splitlines() if l.strip().startswith("- ")]
        return " / ".join(l[2:] for l in lines[:3])

    # 「今日のまとめ」の最初の箇条書き
    bullet = re.search(r"- (.+)", text)
    return bullet.group(1)[:100] if bullet else text[:100].replace("\n", " ")


# ルートや汎用ディレクトリ名として誤検出されやすい名前を除外
_PROJECT_DENYLIST = {"Projects", "projects", "Users", "home", "app", "src", "code"}


def _is_valid_project_name(name: str) -> bool:
    """プロジェクト名として妥当かチェック（ディレクトリ名ベース）。"""
    if not name or len(name) > 50:
        return False
    candidate = Path(name).name
    if candidate in _PROJECT_DENYLIST:
        return False
    # スペース多い・日本語メインはスキップ
    if " " in candidate and len(candidate) > 30:
        return False
    return bool(candidate)


def _extract_projects(content: str) -> list[str]:
    """**Project:** `name` のユニーク一覧と WHS セッションを返す。"""
    seen: dict[str, None] = {}
    for m in re.finditer(r"\*\*Project:\*\*\s*`([^`]+)`", content):
        raw = m.group(1)
        name = Path(raw).name
        if _is_valid_project_name(name):
            seen[name] = None
    if re.search(r"### WHS学習", content):
        seen.setdefault("世界遺産検定", None)
    return list(seen)


def _extract_sessions(content: str, date: str) -> dict[str, list[dict]]:
    """プロジェクト名 → セッションリスト を返す。"""
    result: dict[str, list[dict]] = {}

    # --- 通常 Session ブロック ---
    for m in re.finditer(
        r"### Session \((\d{2}:\d{2})\)\n(.*?)(?=\n### |\n## |\Z)",
        content, re.DOTALL
    ):
        time, body = m.group(1), m.group(2)

        proj_m = re.search(r"\*\*Project:\*\*\s*`([^`]+)`", body)
        raw_proj = proj_m.group(1) if proj_m else ""
        candidate = Path(raw_proj).name if raw_proj else ""
        project = candidate if _is_valid_project_name(candidate) else "その他"

        ctx_m = re.search(r"\*\*Context:\*\*\s*(.+)", body)
        context = ctx_m.group(1).strip()[:100] if ctx_m else ""

        result.setdefault(project, []).append(
            {"date": date, "time": time, "context": context}
        )

    # --- WHS 学習セッション ---
    for m in re.finditer(r"### WHS学習 \((\d{2}:\d{2})\) \| (.+)", content):
        result.setdefault("世界遺産検定", []).append(
            {"date": date, "time": m.group(1), "context": m.group(2).strip()}
        )

    return result


# ── ページ生成 ──────────────────────────────────────────────────────────

def _daily_index(rows: list[tuple[str, str, list[str]]]) -> str:
    now = today_iso()
    lines = [
        "---",
        'title: "Daily Logs"',
        f'updated: "{now}"',
        "---",
        "",
        "# Daily Logs",
        "",
        "| 日付 | プロジェクト | 概要 |",
        "|------|------------|------|",
    ]
    for date, summary, projects in sorted(rows, key=lambda r: r[0], reverse=True):
        proj_str = " · ".join(f"`{p}`" for p in projects[:4])
        safe = summary.replace("|", "｜")[:80]
        lines.append(f"| [[daily/{date}\\|{date}]] | {proj_str} | {safe} |")
    return "\n".join(lines) + "\n"


def _project_page(project: str, sessions: list[dict]) -> str:
    now = today_iso()
    sessions_desc = sorted(sessions, key=lambda s: (s["date"], s["time"]), reverse=True)
    lines = [
        "---",
        f'title: "{project}"',
        'tags: ["project-log"]',
        f'updated: "{now}"',
        "---",
        "",
        f"# {project}",
        "",
        "> 大元の daily ログへのリンク集。詳細は各日付から参照。",
        "",
        "| 日付 | 時刻 | 概要 |",
        "|------|------|------|",
    ]
    for s in sessions_desc:
        ctx = s["context"].replace("|", "｜")[:80]
        lines.append(f"| [[daily/{s['date']}\\|{s['date']}]] | {s['time']} | {ctx} |")
    return "\n".join(lines) + "\n"


# ── メイン ─────────────────────────────────────────────────────────────

def run() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    log_files = sorted(
        f for f in DAILY_DIR.glob("*.md")
        if re.match(r"\d{4}-\d{2}-\d{2}\.md", f.name)
    )

    daily_rows: list[tuple[str, str, list[str]]] = []
    all_sessions: dict[str, list[dict]] = {}

    for log_path in log_files:
        date = log_path.stem
        content = log_path.read_text(encoding="utf-8")

        tldr = _extract_tldr(content)
        projects = _extract_projects(content)
        sessions = _extract_sessions(content, date)

        daily_rows.append((date, tldr, projects))
        for proj, sess_list in sessions.items():
            all_sessions.setdefault(proj, []).extend(sess_list)

    # daily/index.md
    idx_path = DAILY_DIR / "index.md"
    idx_path.write_text(_daily_index(daily_rows), encoding="utf-8")
    print(f"  daily/index.md  ({len(daily_rows)} days)")

    # projects/<slug>.md
    for project, sessions in sorted(all_sessions.items()):
        slug = re.sub(r"[^\w-]", "-", project.lower()).strip("-")
        slug = re.sub(r"-+", "-", slug)
        path = PROJECTS_DIR / f"{slug}.md"
        path.write_text(_project_page(project, sessions), encoding="utf-8")
        print(f"  projects/{slug}.md  ({len(sessions)} sessions)")

    print(f"\n完了: {len(log_files)} 日分 / {len(all_sessions)} プロジェクト")


if __name__ == "__main__":
    run()
