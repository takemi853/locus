"""
draft/ の記事をレビューして verified（knowledge/wiki/）に昇格させる。

Usage:
    uv run python scripts/review.py          # 全ドラフトをレビュー
    uv run python scripts/review.py --list   # ドラフト一覧を表示するだけ
    uv run python scripts/review.py --all    # 対話なしで全て承認（信頼している場合）
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from config import (
    CONCEPTS_DIR,
    CONNECTIONS_DIR,
    DRAFT_CONCEPTS_DIR,
    DRAFT_CONNECTIONS_DIR,
    KNOWLEDGE_DIR,
    DRAFT_DIR,
    now_iso,
)
from utils import load_state, path_to_slug, save_state, read_wiki_index

# ターミナルカラー
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def list_drafts() -> list[tuple[Path, Path]]:
    """(draft_path, verified_path) のリストを返す。"""
    drafts: list[tuple[Path, Path]] = []
    for draft_path in sorted(DRAFT_CONCEPTS_DIR.glob("*.md")):
        verified_path = CONCEPTS_DIR / draft_path.name
        drafts.append((draft_path, verified_path))
    for draft_path in sorted(DRAFT_CONNECTIONS_DIR.glob("*.md")):
        verified_path = CONNECTIONS_DIR / draft_path.name
        drafts.append((draft_path, verified_path))
    return drafts


def show_article(path: Path) -> None:
    """記事の内容をターミナルに整形して表示する。"""
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # YAMLフロントマターを分離
    if lines and lines[0] == "---":
        end = next((i for i, l in enumerate(lines[1:], 1) if l == "---"), None)
        if end:
            frontmatter = lines[1:end]
            body = lines[end + 1:]
        else:
            frontmatter, body = [], lines
    else:
        frontmatter, body = [], lines

    # 確信度タグを検出
    confidence_line = next((l for l in body if "confidence:" in l), None)
    unverified_start = next((i for i, l in enumerate(body) if "<!-- unverified:" in l), None)

    print(f"\n{BOLD}{'─' * 60}{RESET}")
    print(f"{BOLD}{CYAN}{path.name}{RESET}")
    print(f"{'─' * 60}")

    # フロントマター表示
    if frontmatter:
        for line in frontmatter:
            print(f"  {CYAN}{line}{RESET}")
        print()

    # 本文表示（タグを除く）
    for line in body:
        if line.startswith("<!--"):
            continue
        print(line)

    # 確信度・要確認事項を強調表示
    print(f"\n{BOLD}{'─' * 60}{RESET}")
    if confidence_line:
        score = confidence_line.strip().replace("<!--", "").replace("-->", "").strip()
        color = GREEN if "5/5" in score or "4/5" in score else YELLOW if "3/5" in score else RED
        print(f"{color}確信度: {score}{RESET}")

    if unverified_start is not None:
        print(f"{YELLOW}要確認:{RESET}")
        for line in body[unverified_start + 1:]:
            if "-->" in line:
                break
            if line.strip() and line.strip() != "なし":
                print(f"  {YELLOW}⚠ {line.strip()}{RESET}")


def prompt_action(draft_path: Path, verified_path: Path) -> str:
    """ユーザーにアクションを選ばせる。戻り値: approve / reject / edit / skip"""
    already_exists = verified_path.exists()
    status = f"{YELLOW}(上書き){RESET}" if already_exists else f"{GREEN}(新規){RESET}"

    print(f"\n{BOLD}操作を選んでください {status}{RESET}")
    print(f"  {GREEN}[y]{RESET} 承認して verified に昇格")
    print(f"  {RED}[n]{RESET} 却下（draft から削除）")
    print(f"  {CYAN}[e]{RESET} エディタで編集してから再表示")
    print(f"  [s] スキップ（後で判断）")
    print(f"  [q] レビューを終了")

    while True:
        choice = input(f"\n> ").strip().lower()
        if choice in ("y", "n", "e", "s", "q"):
            return choice
        print("y / n / e / s / q で入力してください")


def open_in_editor(path: Path) -> None:
    """$EDITOR または cursor でファイルを開く。"""
    editor = __import__("os").environ.get("EDITOR", "")
    if editor:
        subprocess.run([editor, str(path)])
    else:
        # EDITOR 未設定なら cursor を試みる
        for cmd in ("cursor", "code", "nano"):
            if shutil.which(cmd):
                subprocess.run([cmd, str(path)])
                input("編集が終わったら Enter を押してください...")
                return
        print(f"エディタが見つかりませんでした。直接編集してください: {path}")
        input("編集が終わったら Enter を押してください...")


def approve(draft_path: Path, verified_path: Path) -> None:
    """draft を verified に移動して index.md を更新する。"""
    verified_path.parent.mkdir(parents=True, exist_ok=True)

    # verified: false → verified: true に書き換えてからコピー
    content = draft_path.read_text(encoding="utf-8")
    content = content.replace("verified: false", "verified: true", 1)
    verified_path.write_text(content, encoding="utf-8")

    draft_path.unlink()

    # index.md を更新
    _update_index(verified_path)

    print(f"{GREEN}✓ 承認: {verified_path.relative_to(KNOWLEDGE_DIR)}{RESET}")


def _update_index(article_path: Path) -> None:
    """knowledge/index.md に記事のエントリを追加または更新する。"""
    index_path = KNOWLEDGE_DIR / "index.md"
    rel = article_path.relative_to(KNOWLEDGE_DIR)
    slug = path_to_slug(rel)
    today = now_iso()[:10]

    # タイトルとサマリーを記事から抽出
    content = article_path.read_text(encoding="utf-8")
    title = slug
    summary = ""
    for line in content.splitlines():
        if line.startswith("title:"):
            title = line.split(":", 1)[1].strip().strip('"')
        if not summary and line.startswith("- ") and "verified" not in line:
            summary = line[2:].strip()

    new_row = f"| [[{slug}]] | {summary or title} | - | {today} |"

    if not index_path.exists():
        index_path.write_text(
            "# Knowledge Base Index\n\n"
            "| Article | Summary | Compiled From | Updated |\n"
            "|---------|---------|---------------|---------|\n",
            encoding="utf-8",
        )

    index_content = index_path.read_text(encoding="utf-8")

    # 既存エントリがあれば更新、なければ追加
    if f"[[{slug}]]" in index_content:
        lines = index_content.splitlines()
        lines = [new_row if f"[[{slug}]]" in line else line for line in lines]
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(new_row + "\n")


def reject(draft_path: Path) -> None:
    draft_path.unlink()
    print(f"{RED}✗ 却下: {draft_path.name}{RESET}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Draft記事のレビューと承認")
    parser.add_argument("--list", action="store_true", help="ドラフト一覧を表示するだけ")
    parser.add_argument("--all", action="store_true", help="全ドラフトを自動承認")
    args = parser.parse_args()

    drafts = list_drafts()

    if not drafts:
        print("レビュー待ちのドラフトはありません。")
        return

    if args.list:
        print(f"\n{BOLD}レビュー待ちドラフト ({len(drafts)} 件){RESET}")
        for draft_path, verified_path in drafts:
            status = f"{YELLOW}[上書き]{RESET}" if verified_path.exists() else f"{GREEN}[新規]{RESET}"
            print(f"  {status} {draft_path.relative_to(DRAFT_DIR)}")
        return

    if args.all:
        print(f"{YELLOW}全 {len(drafts)} 件を自動承認します...{RESET}")
        for draft_path, verified_path in drafts:
            approve(draft_path, verified_path)
        print(f"\n{GREEN}完了。{RESET}")
        return

    # 対話モード
    print(f"\n{BOLD}レビューモード — {len(drafts)} 件のドラフトがあります{RESET}")
    approved = rejected = skipped = 0

    for i, (draft_path, verified_path) in enumerate(drafts, 1):
        print(f"\n{BOLD}[{i}/{len(drafts)}]{RESET}")
        show_article(draft_path)

        while True:
            action = prompt_action(draft_path, verified_path)
            if action == "y":
                approve(draft_path, verified_path)
                approved += 1
                break
            elif action == "n":
                reject(draft_path)
                rejected += 1
                break
            elif action == "e":
                open_in_editor(draft_path)
                show_article(draft_path)  # 編集後に再表示
            elif action == "s":
                skipped += 1
                break
            elif action == "q":
                print(f"\n{BOLD}中断しました。{RESET}")
                _print_summary(approved, rejected, skipped)
                return

    _print_summary(approved, rejected, skipped)


def _print_summary(approved: int, rejected: int, skipped: int) -> None:
    print(f"\n{BOLD}{'─' * 40}{RESET}")
    print(f"結果: {GREEN}承認 {approved}{RESET} / {RED}却下 {rejected}{RESET} / スキップ {skipped}")
    remaining = list_drafts()
    if remaining:
        print(f"{YELLOW}残り {len(remaining)} 件のドラフトが未レビューです。{RESET}")


if __name__ == "__main__":
    main()
