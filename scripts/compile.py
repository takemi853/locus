"""
Compile daily conversation logs into structured knowledge articles.

This is the "LLM compiler" - it reads daily logs (source code) and produces
organized knowledge articles (the executable).

Usage:
    uv run python compile.py                    # compile new/changed logs only
    uv run python compile.py --all              # force recompile everything
    uv run python compile.py --file daily/2026-04-01.md  # compile a specific log
    uv run python compile.py --dry-run          # show what would be compiled
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from config import (
    AGENTS_FILE, DATA_DIR, DAILY_DIR, KNOWLEDGE_DIR,
    DRAFT_DIR,
    now_iso,
)

DRAFT_WIKI_DIR = DRAFT_DIR / "wiki"
from utils import (
    file_hash,
    list_raw_files,
    list_wiki_articles,
    load_state,
    read_wiki_index,
    save_state,
)

# ── Paths for the LLM to use ──────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent


def _extract_projects_from_log(log_content: str) -> list[str]:
    """dailyログの **Project:** 行からプロジェクト名を抽出する。"""
    import re
    found = re.findall(r"\*\*Project:\*\*\s*`([^`]+)`", log_content)
    # パス末尾のディレクトリ名（例: /Users/x/Projects/locus → locus）
    return list(dict.fromkeys(Path(p).name for p in found if p))


def _existing_article_titles() -> str:
    """wiki/ と inbox/wiki/ の既存記事タイトルをスラグ付きで一覧返す（重複防止用）。"""
    lines = []
    for article_path in list_wiki_articles():
        slug = article_path.stem
        # frontmatter から title だけ抜く（全文読まない）
        try:
            header = article_path.read_bytes()[:512].decode("utf-8", errors="replace")
        except OSError:
            continue
        title_match = __import__("re").search(r'^title:\s*["\']?(.+?)["\']?\s*$', header, __import__("re").MULTILINE)
        title = title_match.group(1) if title_match else slug
        lines.append(f"- `{slug}` — {title}")
    return "\n".join(lines) if lines else "（まだ記事なし）"


# ── 画像検索 ──────────────────────────────────────────────────────────

# 画像を埋め込む価値があるタグ（視覚的・地理的・歴史的トピック）
_VISUAL_TAGS = {
    "世界遺産検定", "自然遺産", "文化遺産", "複合遺産", "危機遺産",
    "アフリカ", "アジア", "ヨーロッパ", "アメリカ", "オセアニア",
    "歴史", "地理", "建築", "自然",
}


def _fetch_wiki_thumbnail(title: str, en_aliases: list[str]) -> str | None:
    """Wikipedia REST API でサムネイル URL を取得する。英語エイリアス → 日本語タイトルの順で試す。"""
    candidates = [*en_aliases, title]
    for cand in candidates:
        for lang in ("en", "ja"):
            try:
                encoded = urllib.parse.quote(cand.replace(" ", "_"))
                url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
                req = urllib.request.Request(url, headers={"User-Agent": "locus-kb/1.0"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    data = json.loads(r.read())
                thumb = data.get("thumbnail", {}).get("source")
                if thumb:
                    return thumb
            except Exception:
                continue
    return None


def _embed_image(article_path: Path) -> bool:
    """視覚的なトピックの記事に Wikipedia サムネイルを埋め込む。
    既に画像がある場合・視覚的タグがない場合はスキップ。"""
    content = article_path.read_text(encoding="utf-8")
    if "![" in content:
        return False

    fm_m = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not fm_m:
        return False
    fm_text = fm_m.group(1)

    # tags を確認
    tags_m = re.search(r'^tags:\s*\[(.+)\]', fm_text, re.MULTILINE)
    tags = {t.strip().strip("\"'") for t in tags_m.group(1).split(",")} if tags_m else set()
    if not (tags & _VISUAL_TAGS):
        return False

    title_m = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', fm_text, re.MULTILINE)
    title = title_m.group(1) if title_m else ""

    aliases_m = re.search(r'^aliases:\s*\[(.+)\]', fm_text, re.MULTILINE)
    aliases = [a.strip().strip("\"'") for a in aliases_m.group(1).split(",")] if aliases_m else []
    en_aliases = [a for a in aliases if a.isascii() and len(a) > 3]

    thumb = _fetch_wiki_thumbnail(title, en_aliases)
    if not thumb:
        return False

    # frontmatter に image フィールドを追加
    new_fm = fm_text.rstrip() + f'\nimage: "{thumb}"\n'
    # H1 の直後に画像を挿入（intro 段落の前）
    body = content[fm_m.end():]
    h1_m = re.search(r"^# .+\n\n", body, re.MULTILINE)
    if h1_m:
        insert_at = fm_m.end() + h1_m.end()
        new_content = (
            content[:fm_m.start()]
            + "---\n" + new_fm + "---\n"
            + body[:h1_m.end()]
            + f"![{title}]({thumb})\n\n"
            + body[h1_m.end():]
        )
    else:
        new_content = content.replace(fm_text, new_fm)

    article_path.write_text(new_content, encoding="utf-8")
    return True


async def compile_daily_log(log_path: Path, state: dict) -> float:
    """dailyログ1件をコンパイルして wiki 記事を生成する。"""
    from backends import load_backend

    log_content = log_path.read_text(encoding="utf-8")
    wiki_index = read_wiki_index()
    existing_titles = _existing_article_titles()
    projects = _extract_projects_from_log(log_content)
    projects_field = str(projects) if projects else "[]"
    timestamp = now_iso()

    prompt = f"""あなたは個人ナレッジベース「Locus」のコンパイラです。
dailyログを読み、保存価値のある知識を wiki 記事として抽出してください。

## 現在のナレッジベース（タイトル一覧）

{existing_titles}

## 現在のインデックス

{wiki_index}

---

## 記事フォーマット（必ずこの形式に従う）

```markdown
---
title: "記事タイトル（日本語）"
aliases: [英語略称, 別名]
tags: [カテゴリ, トピック]
projects: {projects_field}
type: concept | how-to | reference | pattern
sources:
  - "daily/{log_path.name}"
created: {log_path.stem}
updated: {log_path.stem}
verified: false
---

# 記事タイトル

[2〜3文の核心的な説明。これだけ読めば概念がわかる水準で]

## Key Points

- **ポイント1**：説明
- **ポイント2**：説明
- **ポイント3**：説明（3〜5項目）

## Details

[詳細説明。背景・仕組み・注意点を段落で。具体的なコード例があれば含める]

## Related Concepts

- [[wiki/関連記事スラグ]] — どう関連するか一言
- [[wiki/別の関連記事]] — どう関連するか一言

## Sources

- [[daily/{log_path.name}]] — このログから抽出した具体的な根拠
```

---

## 記事タイプ別の構造（type フィールドに応じて使い分ける）

| type | 使うセクション | 特徴 |
|------|-------------|------|
| `concept` | Key Points / Details / Related Concepts / Sources | デフォルト。概念・設計思想の解説 |
| `pattern` | Key Points / **Anti-pattern** / **Correct Pattern** / When to Apply / Related Concepts / Sources | アンチパターン＋正しいパターンをコード例付きで |
| `how-to` | **Prerequisites** / **Steps** / **Caveats** / Related Concepts / Sources | 番号付き手順。Caveats に注意点をまとめる |
| `reference` | **Overview** / **表（markdown table）** / Notes / Related Concepts / Sources | 比較表・設定値一覧を表形式で |

### タイプ別の追加規則
- `pattern`：Anti-pattern に ❌ コード例、Correct Pattern に ✅ コード例を必ず含める
- `how-to`：Steps は番号付きリスト（`1. 〜 2. 〜`）で書く
- `reference`：Markdown テーブルを必ず1つ以上含める
- `concept`：Key Points と Details を充実させ、概念の本質を深掘りする

---

## ルール

### 何を記事にするか
- 「次のセッションでも参照したい知識」を3〜7件抽出する
- 単純な操作ログ（ファイルを読んだ、コマンドを実行した）は記事にしない
- 下した判断・発見したパターン・ハマったポイント・設計決定 → 記事にする価値が高い

### 重複防止（最重要）
**上記「タイトル一覧」に同じトピックの記事が既に存在する場合、新記事を作らず既存記事を更新すること。**
- 既存記事を読む → 新情報を追記 → sources に今回のログを追加 → updated を更新
- スラグが似ている記事（例：`active-sessions-registry` と `active-sessions-multi-session`）は同一トピックとみなして統合を検討

### ファイルパス
- 新規記事の書き込み先：`{DRAFT_WIKI_DIR}/スラグ.md`
- 既存 inbox 記事の更新先：`{DRAFT_WIKI_DIR}/スラグ.md`（既存を Read してから Edit）
- **触ってはいけない**：`{KNOWLEDGE_DIR / 'index.md'}`（昇格時のみ更新）
- ログ追記先：`{KNOWLEDGE_DIR / 'log.md'}`

### スラグ命名規則
- 英語、ケバブケース（例：`session-end-hook`, `uv-no-sync-flag`）
- 既存スラグとの一貫性を優先（例：既に `flush-py` があるなら `flush-py-xxx` で統一）
- 長すぎるスラグは避ける（30文字以内を目安）

### 品質基準
- frontmatter の全フィールドを必ず埋める
- Related Concepts には必ず2件以上の `[[wiki/スラグ]]` wikilink を書く（記事がまだ存在しなくてもよい — スタブとして積極的にリンクする）
- wikilink のパスは `wiki/スラグ` 形式（`concepts/` や `connections/` は廃止）
- Key Points は太字ラベル付きで（`- **ラベル**：説明`）
- Sources には「何を根拠にしたか」の具体的な説明を書く

### ファクトチェック（各記事作成・更新の直後に必ず実行）

記事を書いたら、その記事に戻って以下を確認する：

1. **ソース照合**: 記事内の具体的な主張（年号、数値、固有名詞、手順、バージョン）が
   元のdailyログに実際に記述されているかを照合する
2. **問題なし** → frontmatter の `verified: false` を `verified: true` に変更する
3. **不確かな主張がある** → `verified: false` のまま、`## Sources` の後に以下を追加する：

```
> [!unverified] 未検証の情報
> 以下はdailyログに明示的な根拠がなく、要確認です：
> - 主張1（なぜ不確かか）
> - 主張2（なぜ不確かか）
```

注意: 「根拠がない」とは「dailyログのどこを読んでも確認できない」こと。
推測・補完・一般知識で書いた内容は必ずフラグを立てること。

### 最後に必ず実行
以下の形式で `{KNOWLEDGE_DIR / 'log.md'}` に追記する：
```
## [{timestamp}] compile | {log_path.name}
- Source: daily/{log_path.name}
- 作成：[[inbox/wiki/x]], [[inbox/wiki/y]]
- 更新：[[inbox/wiki/z]]（更新なしの場合は省略）
```

---

## コンパイル対象の dailyログ

**ファイル：** {log_path.name}

{log_content}
"""

    cost = 0.0

    # コンパイル前の記事一覧（新規/更新検出用）
    before_mtimes = {p: p.stat().st_mtime for p in DRAFT_WIKI_DIR.glob("*.md")}

    try:
        backend = load_backend()
        await backend.agentic(prompt=prompt, cwd=str(ROOT_DIR), max_turns=30)
    except Exception as e:
        print(f"  エラー: {e}")
        return 0.0

    # 新規/更新された記事に画像を埋め込む
    image_count = 0
    for p in DRAFT_WIKI_DIR.glob("*.md"):
        if p.name == "index.md":
            continue
        prev_mtime = before_mtimes.get(p)
        if prev_mtime is None or p.stat().st_mtime > prev_mtime:
            if _embed_image(p):
                image_count += 1
    if image_count:
        print(f"  画像埋め込み: {image_count} 件")

    # 処理済み状態を記録
    rel_path = log_path.name
    state.setdefault("ingested", {})[rel_path] = {
        "hash": file_hash(log_path),
        "compiled_at": now_iso(),
        "cost_usd": cost,
    }
    state["total_cost"] = state.get("total_cost", 0.0) + cost
    save_state(state)

    return cost


def main():
    parser = argparse.ArgumentParser(description="Compile daily logs into knowledge articles")
    parser.add_argument("--all", action="store_true", help="Force recompile all logs")
    parser.add_argument("--file", type=str, help="Compile a specific daily log file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be compiled")
    args = parser.parse_args()

    state = load_state()

    # Determine which files to compile
    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            target = DAILY_DIR / target.name
        if not target.exists():
            # Try resolving relative to data dir
            target = DATA_DIR / args.file
        if not target.exists():
            print(f"Error: {args.file} not found")
            sys.exit(1)
        to_compile = [target]
    else:
        all_logs = list_raw_files()
        if args.all:
            to_compile = all_logs
        else:
            to_compile = []
            for log_path in all_logs:
                rel = log_path.name
                prev = state.get("ingested", {}).get(rel, {})
                if not prev or prev.get("hash") != file_hash(log_path):
                    to_compile.append(log_path)

    if not to_compile:
        print("Nothing to compile - all daily logs are up to date.")
        return

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Files to compile ({len(to_compile)}):")
    for f in to_compile:
        print(f"  - {f.name}")

    if args.dry_run:
        return

    # Compile each file sequentially
    total_cost = 0.0
    for i, log_path in enumerate(to_compile, 1):
        print(f"\n[{i}/{len(to_compile)}] Compiling {log_path.name}...")
        cost = asyncio.run(compile_daily_log(log_path, state))
        total_cost += cost
        print(f"  Done.")

    articles = list_wiki_articles()
    print(f"\nCompilation complete. Total cost: ${total_cost:.2f}")
    print(f"Knowledge base: {len(articles)} articles")

    # インデックス再生成（LLM不要・高速）
    print("\nインデックスを再生成中...")
    from reindex import run as reindex_run
    reindex_run()


if __name__ == "__main__":
    main()
