"""
SessionStart hook - injects knowledge base context into every conversation.

Configure in .claude/settings.json:
{
    "hooks": {
        "SessionStart": [{
            "matcher": "",
            "command": "uv run python hooks/session-start.py"
        }]
    }
}
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 再帰ガード: flush.py が内部で起動した Claude セッションには登録・注入しない
if os.environ.get("CLAUDE_INVOKED_BY"):
    print(json.dumps({}))
    sys.exit(0)

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
from config import KNOWLEDGE_DIR, DAILY_DIR, INDEX_FILE, WIKI_DIR

MAX_CONTEXT_CHARS = 28_000
MAX_LOG_LINES = 30
MAX_WIKI_ARTICLES = 4       # 注入する関連記事の最大件数
MAX_WIKI_ARTICLE_CHARS = 1_800  # 1記事あたりの最大文字数

CC_CHANGELOG = Path.home() / ".claude" / "cache" / "changelog.md"
CC_MAX_VERSIONS = 2

PLANNING_NOW = KNOWLEDGE_DIR / "planning" / "now.md"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
PROJECTS_RE = re.compile(r"^projects:\s*\[([^\]]*)\]", re.MULTILINE)
HEADING_RE = re.compile(r"^# (.+)$", re.MULTILINE)


def get_claude_code_versions() -> str:
    try:
        text = CC_CHANGELOG.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""
    sections = re.split(r"\n(?=## )", text)
    version_sections = [s for s in sections if re.match(r"## \d", s)]
    latest = version_sections[:CC_MAX_VERSIONS]
    if not latest:
        return ""
    trimmed = []
    for section in latest:
        lines = section.splitlines()
        if len(lines) > 20:
            lines = lines[:20] + ["  *(trimmed)*"]
        trimmed.append("\n".join(lines))
    return "\n\n".join(trimmed)


def get_recent_log() -> str:
    today = datetime.now(timezone.utc).astimezone()
    for offset in range(2):
        date = today - timedelta(days=offset)
        log_path = DAILY_DIR / f"{date.strftime('%Y-%m-%d')}.md"
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            recent = lines[-MAX_LOG_LINES:] if len(lines) > MAX_LOG_LINES else lines
            return "\n".join(recent)
    return "(no recent daily log)"


def get_relevant_wiki_articles(cwd: str) -> str:
    """cwd のプロジェクトに紐づく wiki 記事の本文を返す。

    スコアリング:
      +2.0 — frontmatter の projects: フィールドにプロジェクト名が含まれる
      +0.5 — スラグやタイトルにプロジェクト名のキーワードが含まれる（3文字以上）
    上位 MAX_WIKI_ARTICLES 件を本文付きで返す。
    """
    if not WIKI_DIR.exists():
        return ""
    project_name = Path(cwd).name if cwd else ""
    cwd_keywords = [kw for kw in re.split(r"[-_/]", project_name.lower()) if len(kw) >= 3]

    scored: list[tuple[float, Path]] = []

    for md_file in WIKI_DIR.glob("*.md"):
        score = 0.0
        try:
            # frontmatter の解析は先頭 2KB で十分
            header = md_file.read_bytes()[:2048].decode("utf-8", errors="replace")
        except OSError:
            continue

        fm_match = FRONTMATTER_RE.match(header)
        if fm_match and project_name:
            proj_match = PROJECTS_RE.search(fm_match.group(1))
            if proj_match:
                proj_list = [p.strip() for p in proj_match.group(1).split(",") if p.strip()]
                if project_name in proj_list:
                    score += 2.0

        # スラグ・タイトルへのキーワードマッチ
        if cwd_keywords:
            slug_lower = md_file.stem.lower()
            title_match = HEADING_RE.search(header)
            title_lower = title_match.group(1).lower() if title_match else ""
            for kw in cwd_keywords:
                if kw in slug_lower or kw in title_lower:
                    score += 0.5

        if score > 0:
            scored.append((score, md_file))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:MAX_WIKI_ARTICLES]
    if not top:
        return ""

    parts = []
    for _, md_file in top:
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        # frontmatter を除いた本文を取得
        body = re.split(r"^---\s*$", content, maxsplit=2, flags=re.MULTILINE)
        body_text = body[-1].strip() if len(body) >= 2 else content.strip()
        if len(body_text) > MAX_WIKI_ARTICLE_CHARS:
            body_text = body_text[:MAX_WIKI_ARTICLE_CHARS] + "\n...(truncated)"
        parts.append(f"### [[{md_file.stem}]]\n\n{body_text}")

    return "\n\n---\n\n".join(parts)


def build_context(cwd: str = "") -> str:
    parts = []

    today = datetime.now(timezone.utc).astimezone()
    parts.append(f"## Today\n{today.strftime('%A, %B %d, %Y')}")

    try:
        planning_now = PLANNING_NOW.read_text(encoding="utf-8")
        parts.append(f"## 今週のフォーカス\n\n{planning_now}")
    except FileNotFoundError:
        pass

    if INDEX_FILE.exists():
        parts.append(f"## Knowledge Base Index\n\n{INDEX_FILE.read_text(encoding='utf-8')}")
    else:
        parts.append("## Knowledge Base Index\n\n(empty - no articles compiled yet)")

    cc_versions = get_claude_code_versions()
    if cc_versions:
        parts.append(f"## Claude Code 最新バージョン\n\n{cc_versions}")

    wiki_articles = get_relevant_wiki_articles(cwd)
    if wiki_articles:
        parts.append(f"## 関連 Wiki 記事（本文）\n\n{wiki_articles}")

    recent_log = get_recent_log()
    parts.append(f"## Recent Daily Log\n\n{recent_log}")

    context = "\n\n---\n\n".join(parts)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n...(truncated)"
    return context


def save_active_session(hook_input: dict) -> None:
    from session_registry import register
    register(
        hook_input.get("session_id", ""),
        hook_input.get("transcript_path", ""),
        hook_input.get("cwd", ""),
    )


def main():
    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except Exception:
        hook_input = {}

    save_active_session(hook_input)

    context = build_context(cwd=hook_input.get("cwd", ""))

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    main()
