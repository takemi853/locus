"""
Memory flush agent - extracts important knowledge from conversation context.

Spawned by session-end.py or pre-compact.py as a background process. Reads
pre-extracted conversation context from a .md file, uses the Claude Agent SDK
to decide what's worth saving, and appends the result to today's daily log.

Usage:
    uv run python flush.py <context_file.md> <session_id>
"""

from __future__ import annotations

# Recursion prevention: set this BEFORE any imports that might trigger Claude
import os
os.environ["CLAUDE_INVOKED_BY"] = "memory_flush"

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
LOG_FILE = SCRIPTS_DIR / "flush.log"

# Set up file-based logging so we can verify the background process ran.
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,  # 既存のハンドラがあっても上書き（no-op を防ぐ）
)

# データパスは config.py の DATA_DIR に従う（ログ設定の後に import）
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from config import DAILY_DIR  # noqa: E402
except Exception as _e:
    import traceback as _tb
    logging.critical("FATAL: Cannot import DAILY_DIR: %s\n%s", _e, _tb.format_exc())
    sys.exit(1)

STATE_FILE = SCRIPTS_DIR / "last-flush.json"


def load_flush_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_flush_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def append_to_daily_log(content: str, section: str = "Session") -> None:
    """Append content to today's daily log."""
    today = datetime.now(timezone.utc).astimezone()
    log_path = DAILY_DIR / f"{today.strftime('%Y-%m-%d')}.md"

    if not log_path.exists():
        DAILY_DIR.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"# Daily Log: {today.strftime('%Y-%m-%d')}\n\n## Sessions\n\n## Memory Maintenance\n\n",
            encoding="utf-8",
        )

    time_str = today.strftime("%H:%M")
    entry = f"### {section} ({time_str})\n\n{content}\n\n"

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


async def run_flush(context: str, cwd: str = "") -> str:
    """会話コンテキストから重要な知識を抽出してdailyログ用テキストを返す。"""
    import sys
    sys.path.insert(0, str(SCRIPTS_DIR))
    from backends import load_backend

    prompt = f"""以下の会話コンテキストを読み、dailyログに残す価値のある情報を日本語で簡潔にまとめてください。
ツールは使わず、プレーンテキストで返してください。

以下のセクション形式で構造化してください：

**Context:** 何をしていたか1行で

**Key Exchanges:**
- 重要なやり取りや議論

**Decisions Made:**
- 下した判断とその理由

**Lessons Learned:**
- 発見したパターン・ハマったポイント・知見

**Action Items:**
- 次にやること・TODO

以下は含めないでください：
- 単純なツール呼び出しやファイル読み込み
- 明らかに自明な内容
- 簡単な確認のやり取り

保存すべき内容がない場合は、正確に「FLUSH_OK」とだけ返してください。

最後に必ず以下のメタ情報を追記してください：

<!-- confidence: X/5 -->
<!-- unverified:
- [会話に明示的な根拠がない、または誤解している可能性がある主張を列挙。なければ「なし」]
-->

## 会話コンテキスト

{context}"""

    backend = load_backend()

    try:
        response = await backend.text(prompt)
    except Exception as e:
        import traceback
        logging.error("Backend error: %s\n%s", e, traceback.format_exc())
        response = f"FLUSH_ERROR: {type(e).__name__}: {e}"

    # Project情報をプログラム側で付加（LLMに任せると抜けるため）
    if cwd and response and not response.startswith("FLUSH_OK") and not response.startswith("FLUSH_ERROR:"):
        project_name = Path(cwd).name
        response = f"**Project:** `{project_name}` (`{cwd}`)\n\n{response}"

    return response


def _compile_after_hour() -> int:
    try:
        from config import Settings
        return Settings.load().knowledge.compile_after_hour
    except Exception:
        return 18


def _notify_error(message: str) -> None:
    """macOS通知でエラーを知らせる（non-fatal）。"""
    if sys.platform != "darwin":
        return
    import subprocess as _sp
    script = f'display notification "{message}" with title "memory flush ⚠️" sound name "Basso"'
    try:
        _sp.run(["osascript", "-e", script], timeout=5, capture_output=True)
    except Exception:
        pass


def maybe_trigger_compilation() -> None:
    """If it's past the compile hour and today's log hasn't been compiled, run compile.py."""
    import subprocess as _sp

    now = datetime.now(timezone.utc).astimezone()
    if now.hour < _compile_after_hour():
        return

    # Check if today's log has already been compiled
    today_log = f"{now.strftime('%Y-%m-%d')}.md"
    compile_state_file = SCRIPTS_DIR / "state.json"
    if compile_state_file.exists():
        try:
            compile_state = json.loads(compile_state_file.read_text(encoding="utf-8"))
            ingested = compile_state.get("ingested", {})
            if today_log in ingested:
                # Already compiled today - check if the log has changed since
                from hashlib import sha256
                log_path = DAILY_DIR / today_log
                if log_path.exists():
                    current_hash = sha256(log_path.read_bytes()).hexdigest()[:16]
                    if ingested[today_log].get("hash") == current_hash:
                        return  # log unchanged since last compile
        except (json.JSONDecodeError, OSError):
            pass

    compile_script = SCRIPTS_DIR / "compile.py"
    if not compile_script.exists():
        return

    logging.info("End-of-day compilation triggered (after %d:00)", _compile_after_hour())

    uv = next((p for p in ["/Users/takemi/.local/bin/uv", "/usr/local/bin/uv", "/opt/homebrew/bin/uv"] if Path(p).exists()), "uv")
    cmd = [uv, "run", "--directory", str(ROOT), "python", str(compile_script)]

    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True

    try:
        log_handle = open(str(SCRIPTS_DIR / "compile.log"), "a")
        _sp.Popen(cmd, stdout=log_handle, stderr=_sp.STDOUT, cwd=str(ROOT), **kwargs)
    except Exception as e:
        logging.error("Failed to spawn compile.py: %s", e)


def main():
    if len(sys.argv) < 3:
        logging.error("Usage: %s <context_file.md> <session_id> [cwd]", sys.argv[0])
        sys.exit(1)

    context_file = Path(sys.argv[1])
    session_id = sys.argv[2]
    cwd = sys.argv[3] if len(sys.argv) > 3 else ""

    logging.info("flush.py started for session %s, context: %s", session_id, context_file)

    if not context_file.exists():
        logging.error("Context file not found: %s", context_file)
        return

    # Deduplication: skip if same session was flushed within 60 seconds
    state = load_flush_state()
    if (
        state.get("session_id") == session_id
        and time.time() - state.get("timestamp", 0) < 60
    ):
        logging.info("Skipping duplicate flush for session %s", session_id)
        context_file.unlink(missing_ok=True)
        return

    # Read pre-extracted context
    context = context_file.read_text(encoding="utf-8").strip()
    if not context:
        logging.info("Context file is empty, skipping")
        context_file.unlink(missing_ok=True)
        return

    logging.info("Flushing session %s: %d chars", session_id, len(context))

    # Run the LLM extraction
    response = asyncio.run(run_flush(context, cwd=cwd))

    # Append to daily log
    if response.startswith("FLUSH_OK"):
        logging.info("Result: FLUSH_OK")
        append_to_daily_log(
            "FLUSH_OK - Nothing worth saving from this session", "Memory Flush"
        )
    elif response.startswith("FLUSH_ERROR:"):
        logging.error("Result: %s", response)
        append_to_daily_log(response, "Memory Flush")
        _notify_error(f"flush failed: {response[:80]}")
    else:
        logging.info("Result: saved to daily log (%d chars)", len(response))
        append_to_daily_log(response, "Session")

    # Update dedup state
    save_flush_state({"session_id": session_id, "timestamp": time.time()})

    # Clean up context file
    context_file.unlink(missing_ok=True)

    # End-of-day auto-compilation: if it's past the compile hour and today's
    # log hasn't been compiled yet, trigger compile.py in the background.
    maybe_trigger_compilation()

    logging.info("Flush complete for session %s", session_id)


if __name__ == "__main__":
    main()
