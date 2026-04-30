"""
Telegram ニュースボット。
毎朝のニュースを送信し、👍/👎 フィードバックを news-feedback.json に蓄積する。

セットアップ:
    1. @BotFather に /newbot でボットを作成 → BOT_TOKEN を取得
    2. ~/.zshrc に追加:
           export TELEGRAM_BOT_TOKEN="1234567890:AAF..."
           export TELEGRAM_CHAT_ID="あなたのCHAT_ID"
    3. CHAT_ID の確認: ボットに何か送ってから python news_bot.py --get-chat-id

Usage:
    python news_bot.py              # 今日分を送信 + フィードバック受信（デーモン）
    python news_bot.py --send-only  # 送信だけして終了
    python news_bot.py --poll-only  # フィードバック受信のみ（デーモン）
    python news_bot.py --get-chat-id  # CHAT_ID を確認
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import today_iso

BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")

SCRIPTS_DIR   = Path(__file__).resolve().parent
LATEST_FILE   = SCRIPTS_DIR / "news-latest.json"
FEEDBACK_FILE = SCRIPTS_DIR / "news-feedback.json"
BOT_STATE_FILE = SCRIPTS_DIR / "news-bot-state.json"

JST = timezone(timedelta(hours=9))

LABEL_ICON = {
    "en_acc": "🌐", "en_kw": "🔍",
    "ja_acc": "🇯🇵", "ja_kw": "🆕",
    "hn": "🔥", "reddit": "💬", "rss": "📡",
}


# ── Telegram API ──────────────────────────────────────────────────────

def _tg(method: str, **params) -> dict:
    import urllib.request
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(params).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [tg] {method}: {e}", file=sys.stderr)
        return {}


# ── ユーティリティ ─────────────────────────────────────────────────────

def _item_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _esc(text: str) -> str:
    """Telegram HTML モード用にエスケープ。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_num(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K" if n % 1_000 == 0 else f"{n/1_000:.1f}K"
    return str(n)


# ── State / Feedback I/O ──────────────────────────────────────────────

def _load_state() -> dict:
    if BOT_STATE_FILE.exists():
        try:
            return json.loads(BOT_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(s: dict) -> None:
    BOT_STATE_FILE.write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_feedback() -> dict:
    if FEEDBACK_FILE.exists():
        try:
            return json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"items": {}, "stats": {"by_account": {}, "by_label": {}}}


def _save_feedback(fb: dict) -> None:
    FEEDBACK_FILE.write_text(
        json.dumps(fb, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_latest() -> dict:
    if LATEST_FILE.exists():
        try:
            return json.loads(LATEST_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"items": []}


# ── 送信 ──────────────────────────────────────────────────────────────

def send_news(items: list[dict], force: bool = False) -> None:
    """今日のニュースを Telegram に送信する。"""
    state = _load_state()
    today = today_iso()

    if state.get("sent_date") == today and not force:
        print("  [bot] 今日分は送信済み（--force で再送信）")
        return

    # ヘッダー
    _tg("sendMessage", chat_id=CHAT_ID,
        text=f"📰 <b>Daily Brief — {today}</b>\n{len(items)} 件のニュースです",
        parse_mode="HTML")
    time.sleep(0.5)

    sent_items: list[dict] = []
    for item in items:
        msg_id = _send_item(item)
        if msg_id:
            sent_items.append({
                "msg_id": msg_id,
                "item_id": _item_id(item.get("url", "")),
            })
        time.sleep(0.3)

    state["sent_date"] = today
    state["sent_items"] = sent_items
    _save_state(state)
    print(f"  [bot] {len(sent_items)} 件送信完了")


def _send_item(item: dict) -> int | None:
    """1件送信して message_id を返す。"""
    label  = item.get("query_label") or item.get("source", "")
    icon   = LABEL_ICON.get(label, "📌")
    title  = item.get("title", "")
    url    = item.get("url", "")
    author = item.get("author", "")
    likes  = item.get("likes", 0)
    rt_raw = 0
    metric = item.get("metric", "")
    if "RT:" in metric:
        try:
            rt_raw = int(metric.split("RT:")[1].split(" ")[0].replace(",", ""))
        except Exception:
            pass
    title_ja  = item.get("title_ja", "")
    image_url = item.get("image_url", "")

    # テキスト組み立て
    snippet = _esc(title[:100]) + ("…" if len(title) > 100 else "")
    lines = [f'{icon} <b><a href="{url}">{snippet}</a></b>']

    meta_parts = []
    if author:
        meta_parts.append(author)
    if likes:
        meta_parts.append(f"♥{_fmt_num(likes)}")
    if rt_raw:
        meta_parts.append(f"RT{_fmt_num(rt_raw)}")
    if meta_parts:
        lines.append(f"<i>{' · '.join(meta_parts)}</i>")

    if title_ja:
        lines.append(f"📝 {_esc(title_ja[:150])}")

    text = "\n".join(lines)
    item_id = _item_id(url)

    keyboard = {"inline_keyboard": [[
        {"text": "👍 いい",    "callback_data": f"like:{item_id}"},
        {"text": "👎 いらない", "callback_data": f"dislike:{item_id}"},
    ]]}

    if image_url:
        resp = _tg("sendPhoto", chat_id=CHAT_ID, photo=image_url,
                   caption=text, parse_mode="HTML", reply_markup=keyboard)
    else:
        resp = _tg("sendMessage", chat_id=CHAT_ID, text=text,
                   parse_mode="HTML", reply_markup=keyboard,
                   disable_web_page_preview=False)

    return (resp.get("result") or {}).get("message_id")


# ── フィードバック受信 ─────────────────────────────────────────────────

def poll_feedback() -> None:
    """フィードバックをポーリングして記録する（無制限・デーモン用）。"""
    state    = _load_state()
    offset   = state.get("poll_offset", 0)
    feedback = _load_feedback()
    latest   = _load_latest()

    item_detail: dict[str, dict] = {
        _item_id(it["url"]): it
        for it in latest.get("items", [])
        if it.get("url")
    }

    print("  [bot] フィードバック受信待ち... (Ctrl+C で停止)")
    try:
        while True:
            resp = _tg("getUpdates", offset=offset, timeout=30,
                       allowed_updates=["callback_query"])
            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                cq = upd.get("callback_query")
                if not cq:
                    continue

                data = cq.get("data", "")
                if ":" not in data:
                    continue
                action, item_id = data.split(":", 1)
                if action not in ("like", "dislike"):
                    continue

                detail = item_detail.get(item_id, {})
                _record_feedback(feedback, item_id, action, detail)
                _save_feedback(feedback)

                # ボタンに反応させる
                icon = "👍" if action == "like" else "👎"
                _tg("answerCallbackQuery",
                    callback_query_id=cq["id"],
                    text=f"{icon} 記録しました")

                # 押したボタンに ✅ を付ける
                msg_id = (cq.get("message") or {}).get("message_id")
                if msg_id:
                    _tg("editMessageReplyMarkup",
                        chat_id=CHAT_ID,
                        message_id=msg_id,
                        reply_markup={"inline_keyboard": [[
                            {"text": "✅ いい"    if action == "like"    else "👍 いい",
                             "callback_data": f"like:{item_id}"},
                            {"text": "✅ いらない" if action == "dislike" else "👎 いらない",
                             "callback_data": f"dislike:{item_id}"},
                        ]]})

                print(f"  [bot] {icon} {detail.get('author','')} — {detail.get('title','')[:60]}")

            state["poll_offset"] = offset
            _save_state(state)

            if not resp.get("result"):
                time.sleep(1)

    except KeyboardInterrupt:
        print("\n  [bot] 停止")


def _record_feedback(fb: dict, item_id: str, action: str, detail: dict) -> None:
    """フィードバックを記録し、stats を更新する。"""
    fb["items"][item_id] = {
        "title":       detail.get("title", ""),
        "url":         detail.get("url", ""),
        "author":      detail.get("author", ""),
        "query_label": detail.get("query_label", ""),
        "action":      action,
        "timestamp":   datetime.now(JST).isoformat(),
        "date":        today_iso(),
    }
    # stats 集計
    author = detail.get("author", "unknown")
    label  = detail.get("query_label", "unknown")
    for key, val in [("by_account", author), ("by_label", label)]:
        fb["stats"].setdefault(key, {}).setdefault(val, {"like": 0, "dislike": 0})
        fb["stats"][key][val][action] += 1


# ── メイン ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram ニュースボット")
    parser.add_argument("--send-only",   action="store_true", help="送信のみ")
    parser.add_argument("--poll-only",   action="store_true", help="ポーリングのみ（デーモン）")
    parser.add_argument("--force",       action="store_true", help="今日分を再送信")
    parser.add_argument("--get-chat-id", action="store_true", help="CHAT_ID を確認")
    args = parser.parse_args()

    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN が未設定です", file=sys.stderr)
        print("  ~/.zshrc に export TELEGRAM_BOT_TOKEN='...' を追加してください")
        sys.exit(1)

    if args.get_chat_id:
        resp = _tg("getUpdates", limit=5)
        updates = resp.get("result", [])
        if not updates:
            print("まだメッセージがありません。Telegram でこのボットに何か送ってから再実行してください。")
            return
        seen: set[int] = set()
        for upd in updates:
            chat = (upd.get("message") or {}).get("chat", {})
            cid = chat.get("id")
            if cid and cid not in seen:
                seen.add(cid)
                print(f"CHAT_ID: {cid}  (username: {chat.get('username', 'N/A')})")
        return

    if not CHAT_ID:
        print("Error: TELEGRAM_CHAT_ID が未設定です", file=sys.stderr)
        sys.exit(1)

    latest = _load_latest()
    items  = latest.get("items", [])

    if not items and not args.poll_only:
        print("  [bot] news-latest.json が空です。collect_news.py を先に実行してください。")
        sys.exit(1)

    if not args.poll_only:
        send_news(items, force=args.force)

    if not args.send_only:
        poll_feedback()


if __name__ == "__main__":
    main()
