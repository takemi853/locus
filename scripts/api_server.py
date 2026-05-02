"""
Locus API サーバー — モバイル入力 & ナレッジクエリ

Port 8081 で起動。Tailscale 経由でプライベートアクセス。

エンドポイント:
  GET  /          → モバイルメモ入力フォーム
  POST /note      → 今日の daily ログにメモを追記
  GET  /query     → クエリフォーム
  POST /query     → ナレッジベースへの質問（JSON: {"question": "..."} or form）
"""

from __future__ import annotations

import os
os.environ["CLAUDE_INVOKED_BY"] = "locus_api"

import asyncio
import html
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from config import DAILY_DIR
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

_API_LOG_DIR = SCRIPTS_DIR / "cache" / "logs"
_API_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(_API_LOG_DIR / "api.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

app = FastAPI(title="Locus API", docs_url=None, redoc_url=None)

# ── HTML テンプレート ─────────────────────────────────────────────────────────

_STYLE = """
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, sans-serif; background: #1a1a1a; color: #e0e0e0;
         padding: 16px; max-width: 640px; margin: 0 auto; }
  h1 { font-size: 1.2rem; margin-bottom: 16px; color: #a0c4ff; }
  textarea, input[type=text] {
    width: 100%; padding: 12px; background: #2a2a2a; border: 1px solid #444;
    border-radius: 8px; color: #e0e0e0; font-size: 1rem; resize: vertical;
  }
  button {
    width: 100%; padding: 14px; background: #3a7bd5; color: white; border: none;
    border-radius: 8px; font-size: 1rem; font-weight: bold; margin-top: 12px; cursor: pointer;
  }
  button:active { background: #2a5ba5; }
  .nav { display: flex; gap: 8px; margin-bottom: 20px; }
  .nav a { flex: 1; text-align: center; padding: 10px; background: #2a2a2a;
            border-radius: 8px; color: #a0c4ff; text-decoration: none; font-size: 0.9rem; }
  .nav a.active { background: #3a7bd5; color: white; }
  .result { margin-top: 16px; padding: 12px; background: #2a2a2a; border-radius: 8px;
            white-space: pre-wrap; font-size: 0.9rem; line-height: 1.6; }
  .ok { border-left: 3px solid #4caf50; }
  .err { border-left: 3px solid #f44336; }
  label { display: block; margin-bottom: 6px; font-size: 0.85rem; color: #888; }
</style>
"""

_NOTE_FORM = """<!doctype html><html><head><title>Locus — メモ</title>{style}</head><body>
<div class="nav">
  <a href="/" class="active">📝 メモ</a>
  <a href="/query">🔍 クエリ</a>
</div>
<h1>📝 メモを追加</h1>
<form method="post" action="/note">
  <label>今日のdailyログに追記します</label>
  <textarea name="text" rows="6" placeholder="気づき、TODO、メモ..." autofocus></textarea>
  <button type="submit">保存</button>
</form>
{result}
</body></html>"""

_QUERY_FORM = """<!doctype html><html><head><title>Locus — クエリ</title>{style}</head><body>
<div class="nav">
  <a href="/">📝 メモ</a>
  <a href="/query" class="active">🔍 クエリ</a>
</div>
<h1>🔍 ナレッジベースに質問</h1>
<form method="post" action="/query">
  <label>質問を入力してください（回答まで30〜60秒かかります）</label>
  <input type="text" name="question" placeholder="例: uv の --no-sync オプションはいつ使う？" autofocus>
  <button type="submit">質問する</button>
</form>
{result}
</body></html>"""

# ── ヘルパー ──────────────────────────────────────────────────────────────────

def append_note_to_daily(text: str) -> Path:
    """テキストを今日の daily ログに追記する。ファイルがなければ作成する。"""
    today = datetime.now(timezone.utc).astimezone()
    log_path = DAILY_DIR / f"{today.strftime('%Y-%m-%d')}.md"
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    if not log_path.exists():
        log_path.write_text(
            f"# Daily Log: {today.strftime('%Y-%m-%d')}\n\n## Sessions\n\n## Memory Maintenance\n\n",
            encoding="utf-8",
        )

    time_str = today.strftime("%H:%M")
    entry = f"\n### Mobile Note ({time_str})\n\n{text.strip()}\n"

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)

    return log_path


async def run_query_async(question: str) -> str:
    """query.py の run_query を呼び出す。"""
    from query import run_query
    return await run_query(question, file_back=False)


# ── ルート ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def note_form():
    return _NOTE_FORM.format(style=_STYLE, result="")


@app.post("/note", response_class=HTMLResponse)
async def save_note(text: str = Form(...)):
    if not text.strip():
        result = '<div class="result err">テキストが空です。</div>'
        return _NOTE_FORM.format(style=_STYLE, result=result)
    try:
        log_path = append_note_to_daily(text)
        logging.info("Mobile note saved to %s (%d chars)", log_path.name, len(text))
        result = f'<div class="result ok">✓ {html.escape(log_path.name)} に保存しました。</div>'
    except Exception as e:
        logging.error("Failed to save note: %s", e)
        result = f'<div class="result err">エラー: {html.escape(str(e))}</div>'
    return _NOTE_FORM.format(style=_STYLE, result=result)


@app.get("/query", response_class=HTMLResponse)
async def query_form():
    return _QUERY_FORM.format(style=_STYLE, result="")


@app.post("/query", response_class=HTMLResponse)
async def query_post(question: str = Form(...)):
    if not question.strip():
        result = '<div class="result err">質問が空です。</div>'
        return _QUERY_FORM.format(style=_STYLE, result=result)
    logging.info("Query: %s", question[:100])
    try:
        answer = await run_query_async(question)
        result = f'<div class="result ok">{html.escape(answer)}</div>'
    except Exception as e:
        logging.error("Query failed: %s", e)
        result = f'<div class="result err">エラー: {html.escape(str(e))}</div>'
    return _QUERY_FORM.format(style=_STYLE, result=result)


@app.post("/api/note")
async def api_save_note(request: Request):
    """JSON API: {"text": "..."}"""
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)
    try:
        log_path = append_note_to_daily(text)
        return {"ok": True, "saved_to": log_path.name}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/query")
async def api_query(request: Request):
    """JSON API: {"question": "..."}"""
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)
    try:
        answer = await run_query_async(question)
        return {"answer": answer}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8081, reload=False)
