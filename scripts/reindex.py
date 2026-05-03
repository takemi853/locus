"""
Generate index pages from daily logs — no LLM, no side effects.

Outputs:
  knowledge/logs/daily/index.md     — 日付一覧（逆順）
  knowledge/projects/<slug>.md      — プロジェクトごとのセッション一覧
  knowledge/inbox/wiki/index.md     — inbox ドラフト記事をタグ別に一覧

各ページは大元の daily ログを wikilink で参照するだけで、内容を複製しない。

Usage:
    uv run python reindex.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DAILY_DIR, DRAFT_DIR, KNOWLEDGE_DIR, PROJECTS_DIR, WIKI_DIR, today_iso
from utils import extract_wikilinks, path_to_slug

DRAFT_WIKI_DIR = DRAFT_DIR / "wiki"

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
        lines.append(f"| [[logs/daily/{date}\\|{date}]] | {proj_str} | {safe} |")
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
        lines.append(f"| [[logs/daily/{s['date']}\\|{s['date']}]] | {s['time']} | {ctx} |")
    return "\n".join(lines) + "\n"


# ── Inbox index ────────────────────────────────────────────────────────

def _parse_inbox_frontmatter(content: str) -> dict[str, object]:
    """frontmatter から title / tags / created を抽出する（YAML依存なし）。"""
    m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    result: dict[str, object] = {}

    for line in block.splitlines():
        # title: "..."  or  title: ...
        km = re.match(r'^(\w+):\s*["\']?(.+?)["\']?\s*$', line)
        if km:
            result[km.group(1)] = km.group(2)
        # tags: [tag1, tag2]
        tm = re.match(r'^tags:\s*\[(.+)\]', line)
        if tm:
            result["tags"] = [t.strip().strip("\"'") for t in tm.group(1).split(",")]

    return result


def _inbox_index(articles: list[tuple[str, str, str, list[str]]]) -> str:
    """inbox/wiki/index.md の本文を生成する。

    articles: [(created, slug, title, tags), ...]  ← created 降順でソート済み
    """
    now = today_iso()
    total = len(articles)

    lines = [
        "---",
        'title: "Inbox — ドラフト記事一覧"',
        'tags: ["inbox", "index"]',
        f'updated: "{now}"',
        "---",
        "",
        f"# Inbox ドラフト（{total} 件）",
        "",
        "> `/study wiki/<slug>` でレビュー → wiki/ に昇格、または削除。",
        "",
    ]

    # ── タグ別グループ ───────────────────────────────────────────────
    tag_groups: dict[str, list[tuple[str, str, str]]] = {}
    for created, slug, title, tags in articles:
        primary = tags[0] if tags else "その他"
        tag_groups.setdefault(primary, []).append((created, slug, title))

    for tag in sorted(tag_groups):
        rows = sorted(tag_groups[tag], key=lambda r: r[0], reverse=True)
        lines += [f"## {tag}  ({len(rows)}件)", ""]
        lines += [
            "| 作成日 | 記事 |",
            "|--------|------|",
        ]
        for created, slug, title in rows:
            lines.append(f"| {created} | [[inbox/wiki/{slug}\\|{title}]] |")
        lines.append("")

    return "\n".join(lines)


# ── Co-link discovery（Scrapbox 式の暗黙的関連検出）────────────────────

def _collect_article_links(search_dirs: list[Path]) -> dict[str, set[str]]:
    """各記事が持つ wikilink のセットを返す。logs/daily/ リンクは除外。"""
    result: dict[str, set[str]] = {}
    for d in search_dirs:
        if not d.is_dir():
            continue
        for f in d.glob("*.md"):
            if f.name in ("index.md", "discovered-connections.md"):
                continue
            try:
                content = f.read_text(encoding="utf-8")
            except OSError:
                continue
            links = {
                link for link in extract_wikilinks(content)
                if not link.startswith("logs/daily/")
            }
            if links:
                result[path_to_slug(f.relative_to(KNOWLEDGE_DIR))] = links
    return result


def _compute_colinks(
    article_links: dict[str, set[str]], min_shared: int = 2, top_n: int = 30
) -> list[tuple[str, str, int, list[str]]]:
    """min_shared 以上の共通リンクを持つ記事ペアを返す（多い順）。"""
    slugs = list(article_links.keys())
    pairs = []
    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            intersection = article_links[a] & article_links[b]
            if len(intersection) >= min_shared:
                pairs.append((a, b, len(intersection), sorted(intersection)))
    return sorted(pairs, key=lambda x: x[2], reverse=True)[:top_n]


def _colink_page(pairs: list[tuple[str, str, int, list[str]]]) -> str:
    """knowledge/wiki/discovered-connections.md の内容を生成する。"""
    now = today_iso()
    lines = [
        "---",
        'title: "発見された繋がり（共リンク）"',
        'tags: ["meta", "graph"]',
        'type: reference',
        f'updated: "{now}"',
        "---",
        "",
        "# 発見された繋がり（共リンク）",
        "",
        "> 2つ以上の共通リンクを持つ記事ペアを自動検出。Scrapbox の co-occurrence と同じ原理。",
        "> 明示的なラベルなしに、リンクの重なりから暗黙的な関連性が浮かび上がる。",
        "",
        "| ページ A | ページ B | 共通リンク数 | 共通リンク |",
        "|---------|---------|------------|----------|",
    ]
    for a, b, count, shared in pairs:
        shared_str = " · ".join(f"[[{s}]]" for s in shared[:3])
        if len(shared) > 3:
            shared_str += f" ほか{len(shared) - 3}件"
        lines.append(f"| [[{a}]] | [[{b}]] | {count} | {shared_str} |")
    if not pairs:
        lines.append("| — | — | — | 共通リンクが2件以上のペアはまだありません |")
    lines += ["", f"*{now} 時点 · reindex.py が自動生成*"]
    return "\n".join(lines) + "\n"


# ── メイン ─────────────────────────────────────────────────────────────

def _promote_to_knowledge(draft_wiki_dir: Path, knowledge_wiki_dir: Path) -> int:
    """draft/wiki/ の記事を knowledge/wiki/ に昇格。
    frontmatter を検証して、その後 move。
    Returns: 昇格した記事数
    """
    promoted = 0

    if not draft_wiki_dir.is_dir():
        return 0

    knowledge_wiki_dir.mkdir(parents=True, exist_ok=True)

    for draft_file in draft_wiki_dir.glob("*.md"):
        if draft_file.name == "index.md":
            continue

        try:
            content = draft_file.read_text(encoding="utf-8")

            # frontmatter 検証（簡易版）
            if not content.startswith("---"):
                print(f"  ⊘ {draft_file.name}: no frontmatter")
                continue

            # knowledge/ へ move
            kb_file = knowledge_wiki_dir / draft_file.name
            kb_file.write_text(content, encoding="utf-8")
            draft_file.unlink()
            promoted += 1
            print(f"  ✓ {draft_file.name} → knowledge/wiki/")
        except Exception as e:
            print(f"  ❌ {draft_file.name}: {e}")
            continue

    return promoted


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

    for project, sessions in sorted(all_sessions.items()):
        slug = re.sub(r"[^\w-]", "-", project.lower()).strip("-")
        slug = re.sub(r"-+", "-", slug)
        path = PROJECTS_DIR / f"{slug}.md"
        path.write_text(_project_page(project, sessions), encoding="utf-8")
        print(f"  projects/{slug}.md  ({len(sessions)} sessions)")

    inbox_articles: list[tuple[str, str, str, list[str]]] = []
    if DRAFT_WIKI_DIR.is_dir():
        for f in DRAFT_WIKI_DIR.glob("*.md"):
            if f.name == "index.md":
                continue
            try:
                fm = _parse_inbox_frontmatter(f.read_text(encoding="utf-8"))
            except OSError:
                continue
            title = str(fm.get("title", f.stem))
            tags = fm.get("tags", [])
            if not isinstance(tags, list):
                tags = [str(tags)]
            created = str(fm.get("created", ""))
            inbox_articles.append((created, f.stem, title, tags))

    inbox_articles.sort(key=lambda r: r[0], reverse=True)
    inbox_idx_path = DRAFT_WIKI_DIR / "index.md"
    inbox_idx_path.write_text(_inbox_index(inbox_articles), encoding="utf-8")
    print(f"  inbox/wiki/index.md  ({len(inbox_articles)} articles)")

    # discovered-connections.md（Scrapbox 式 co-link 検出）
    article_links = _collect_article_links([WIKI_DIR, DRAFT_WIKI_DIR])
    colink_pairs = _compute_colinks(article_links)
    colink_path = WIKI_DIR / "discovered-connections.md"
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    colink_path.write_text(_colink_page(colink_pairs), encoding="utf-8")
    print(f"  wiki/discovered-connections.md  ({len(colink_pairs)} pairs)")

    # tags インデックス生成
    _index_tags()

    # draft/wiki/ → knowledge/wiki/ 昇格
    knowledge_wiki_dir = KNOWLEDGE_DIR / "wiki"
    promoted = _promote_to_knowledge(DRAFT_WIKI_DIR, knowledge_wiki_dir)
    if promoted > 0:
        print(f"  promoted {promoted} articles to knowledge/wiki/")

    print(f"\n完了: {len(log_files)} 日分 / {len(all_sessions)} プロジェクト")


# ── Tags インデックス ─────────────────────────────────────────────────

def _parse_frontmatter(text: str) -> dict:
    """frontmatter をパース（YAML 簡易版）。"""
    if not text.startswith("---"):
        return {}
    
    lines = text.split("\n")
    fm_end = None
    for i in range(1, len(lines)):
        if lines[i].startswith("---"):
            fm_end = i
            break
    
    if fm_end is None:
        return {}
    
    fm_dict = {}
    for line in lines[1:fm_end]:
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # リスト形式 [item1, item2]
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
        # quoted
        elif val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        fm_dict[key] = val
    
    return fm_dict


def _build_tags_index(search_dirs: list[Path]) -> dict:
    """tags を集計。draft/wiki/ と knowledge/wiki/ をスキャン。
    Returns: { "tags": { "tag1": [...paths], "tag2": [...paths] }, "total_tags", "total_pages" }
    """
    tags_map: dict[str, list] = {}
    total_pages = 0
    
    for base_dir in search_dirs:
        if not base_dir.is_dir():
            continue
        
        for md_file in base_dir.glob("*.md"):
            if md_file.name == "index.md":
                continue
            
            try:
                text = md_file.read_text(encoding="utf-8")
                fm = _parse_frontmatter(text)
                rel_path = str(md_file.relative_to(KNOWLEDGE_DIR if KNOWLEDGE_DIR in md_file.parents else base_dir))
                title = fm.get("title", md_file.stem)
                
                total_pages += 1
                
                # frontmatter の tags フィールド
                tags = fm.get("tags", [])
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",")]
                elif not isinstance(tags, list):
                    tags = []
                
                for tag in tags:
                    tag = tag.strip()
                    if tag:
                        if tag not in tags_map:
                            tags_map[tag] = []
                        tags_map[tag].append({
                            "path": rel_path,
                            "title": title,
                        })
            except Exception:
                continue
    
    # タグごとにソート
    for tag in tags_map:
        tags_map[tag].sort(key=lambda x: x["title"])
    
    return {
        "tags": tags_map,
        "total_tags": len(tags_map),
        "total_pages": total_pages,
    }


def _index_tags() -> None:
    """tags インデックスを生成して knowledge/index-tags.json に保存。"""
    import json
    
    search_dirs = [WIKI_DIR, DRAFT_WIKI_DIR]
    index_data = _build_tags_index(search_dirs)
    
    out_path = KNOWLEDGE_DIR / "index-tags.json"
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    print(f"  knowledge/index-tags.json  ({index_data['total_tags']} tags, {index_data['total_pages']} pages)")


if __name__ == "__main__":
    run()
