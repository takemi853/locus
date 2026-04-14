"""
定期フラッシュ — launchd / cron から呼び出す。

active-sessions.json に記録されている全セッションを確認し、
前回フラッシュ以降に新しいターンがあればそれぞれ flush を起動する。

複数の Claude Code セッションが同時に開いていても、全て個別に処理する。
SessionEnd が発火しないままクラッシュした場合でも最大5分以内にフラッシュされる。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 再帰ガード
if os.environ.get("CLAUDE_INVOKED_BY"):
    sys.exit(0)

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
HOOKS_DIR = ROOT / "hooks"
PERIODIC_STATE_FILE = SCRIPTS_DIR / "periodic-state.json"
LOG_FILE = SCRIPTS_DIR / "flush.log"

sys.path.insert(0, str(HOOKS_DIR))
from _common import uv_path  # noqa: E402

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [periodic] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

MIN_INTERVAL_SEC = 120    # 各セッションで前回フラッシュから最低2分は待つ
TLDR_INTERVAL_SEC = 7200  # TL;DR 生成は2時間ごと
MAX_LOG_CHARS = 20_000    # TL;DR 生成に送るログの最大文字数
SELF_HEAL_INTERVAL_SEC = 3600  # 自動修正は1時間に1回まで
STDERR_LOG = SCRIPTS_DIR / "flush_stderr.log"


def count_turns(transcript_path: Path) -> int:
    """トランスクリプトのユーザー/アシスタントターン数を返す。"""
    if not transcript_path.exists():
        return 0
    count = 0
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    msg = entry.get("message", {})
                    if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
                        count += 1
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return count


def load_periodic_state() -> dict:
    """per-session の定期フラッシュ状態を読む。
    形式: {"<session_id>": {"timestamp": float, "turn_count": int}, ...}
    """
    if PERIODIC_STATE_FILE.exists():
        try:
            return json.loads(PERIODIC_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_periodic_state(state: dict) -> None:
    PERIODIC_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def flush_session(session_id: str, transcript_path: Path, cwd: str = "") -> None:
    """session-end.py を呼んでフラッシュを起動する。"""
    session_end_hook = ROOT / "hooks" / "session-end.py"
    payload = json.dumps({
        "session_id": session_id,
        "transcript_path": str(transcript_path),
        "source": "periodic",
        "cwd": cwd,
    })
    proc = subprocess.Popen(
        [uv_path(), "run", "--no-sync", "--directory", str(ROOT), "python", str(session_end_hook)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.communicate(input=payload.encode())


def _today_daily_log_path() -> Path | None:
    from config import DAILY_DIR, today_iso
    path = DAILY_DIR / f"{today_iso()}.md"
    return path if path.exists() else None


async def generate_daily_tldr(log_content: str) -> str:
    """dailyログ全体を要約してTL;DRテキストを返す。"""
    try:
        from backends import load_backend
    except Exception as e:
        logging.error("Cannot import backends: %s", e)
        return ""

    prompt = f"""以下は今日のdailyログ（複数セッションの記録）です。
以下の形式で日本語でまとめてください。

---
**プロジェクト別**
- `プロジェクト名` — ひとことで何をしたか（1プロジェクト1行）

**今日のまとめ**
- 成果・判断・学びを箇条書き（5〜8項目）
---

注意:
- **Project:** フィールドをもとにプロジェクト名を特定する
- プロジェクトが不明なセッションは「その他」にまとめる
- 単純なファイル読み込みやツール呼び出しは省略
- プレーンテキストのみ（コードブロック不要）

## dailyログ

{log_content}"""

    backend = load_backend()
    try:
        return await backend.text(prompt)
    except Exception as e:
        logging.error("TL;DR backend error: %s", e)
        return ""


def update_tldr_in_daily_log(log_path: Path, tldr: str) -> None:
    """dailyログの "## Sessions" 直前にTL;DRセクションを挿入/更新する。"""
    # LLM呼び出し中に別のflushが追記している可能性があるため書き込み直前に再読み込みする
    content = log_path.read_text(encoding="utf-8")
    now_str = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
    tldr_block = f"## TL;DR — 最終更新 {now_str}\n\n{tldr.strip()}\n\n"

    sessions_pos = content.find("\n## Sessions")
    search_end = sessions_pos if sessions_pos != -1 else min(1000, len(content))

    existing = re.search(r"## TL;DR[^\n]*\n", content[:search_end])
    if existing:
        # 既存TL;DRセクションを次の ## 見出し（"## Sessions" 等）まで置換
        tldr_end_match = re.search(r"\n## ", content[existing.end():])
        if tldr_end_match:
            tldr_end = existing.end() + tldr_end_match.start() + 1
        else:
            tldr_end = sessions_pos if sessions_pos != -1 else existing.end()
        new_content = content[: existing.start()] + tldr_block + content[tldr_end:]
    elif sessions_pos != -1:
        insert_at = sessions_pos + 1
        new_content = content[:insert_at] + tldr_block + content[insert_at:]
    else:
        title_end = content.find("\n\n")
        if title_end == -1:
            new_content = content + "\n\n" + tldr_block
        else:
            new_content = content[: title_end + 2] + tldr_block + content[title_end + 2:]

    log_path.write_text(new_content, encoding="utf-8")


def collect_new_errors(since_ts: float) -> list[str]:
    """flush.log と flush_stderr.log から since_ts 以降の ERROR 行を収集する。"""
    errors: list[str] = []
    # flush.log は "YYYY-MM-DD HH:MM:SS LEVEL [tag] message" 形式
    for log_file in [LOG_FILE, STDERR_LOG]:
        if not log_file.exists():
            continue
        try:
            with open(log_file, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.rstrip()
                    if not line:
                        continue
                    # 先頭のタイムスタンプでフィルタリング
                    m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                    if m:
                        try:
                            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(
                                tzinfo=timezone.utc
                            ).timestamp()
                        except ValueError:
                            ts = 0.0
                        if ts <= since_ts:
                            continue
                    # タイムスタンプなし行は常に含める（Traceback など）
                    if "ERROR" in line or "CRITICAL" in line or "Traceback" in line or "Error:" in line:
                        errors.append(f"[{log_file.name}] {line}")
        except OSError:
            pass
    return errors


def spawn_self_heal_agent(errors: list[str]) -> None:
    """エラーを Claude CLI に渡して自動修正を依頼する。"""
    script_paths = [
        str(ROOT / "hooks" / "session-end.py"),
        str(ROOT / "scripts" / "flush.py"),
        str(ROOT / "scripts" / "flush_periodic.py"),
        str(ROOT / "hooks" / "_common.py"),
    ]
    error_text = "\n".join(errors[:100])  # 最大100行

    prompt = f"""You are a self-healing agent for the Locus project.
The following errors were detected in the flush pipeline logs:

```
{error_text}
```

Scripts involved:
{chr(10).join(f"- {p}" for p in script_paths)}

Please:
1. Read the relevant script files to understand the code
2. Identify the root cause of the errors
3. Fix the code directly (use Edit tool)
4. Briefly log what you fixed

Be conservative: only fix clear bugs. Do not refactor unrelated code.
If the errors are transient (network, file-not-found for a deleted session), just note that and exit.
"""

    env = os.environ.copy()
    # 再帰ガード：self-heal から起動した Claude セッションでフックが再発火しないよう設定
    env["CLAUDE_INVOKED_BY"] = "self-heal"

    # launchd は PATH が貧弱なので絶対パスで解決する
    _candidates = [
        "/Users/takemi/.local/bin/claude",
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
    ]
    import shutil as _shutil
    claude_bin = next((p for p in _candidates if Path(p).exists()), None) \
        or _shutil.which("claude") or "claude"

    try:
        proc = subprocess.Popen(
            [claude_bin, "-p", prompt, "--allowedTools", "Read,Edit,Glob,Grep,Bash"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(ROOT),
        )
        stdout, stderr = proc.communicate(timeout=120)
        result = (stdout or b"").decode(errors="replace")[:500]
        logging.info("Self-heal agent 完了 (rc=%d): %s", proc.returncode, result)
    except subprocess.TimeoutExpired:
        proc.kill()
        logging.warning("Self-heal agent がタイムアウトしました")
    except FileNotFoundError:
        logging.warning("Self-heal agent: claude CLI が見つかりません (試したパス: %s)", claude_bin)
    except Exception as e:
        logging.error("Self-heal agent の起動に失敗: %s", e)


def main() -> None:
    sys.path.insert(0, str(SCRIPTS_DIR))
    from session_registry import all_sessions, unregister

    sessions = all_sessions()

    periodic_state = load_periodic_state()
    now = time.time()
    updated = False

    for session_id, info in sessions.items():
        transcript_path = Path(info.get("transcript_path", ""))
        if not transcript_path.exists():
            # transcript が消えていたらクラッシュ終了とみなしてレジストリから削除
            logging.info("Removing stale session (transcript missing): %s", session_id)
            unregister(session_id)
            continue

        # このセッションの前回フラッシュ状態
        sess_state = periodic_state.get(session_id, {})
        last_ts = sess_state.get("timestamp", 0)
        last_turns = sess_state.get("turn_count", 0)

        # 最低インターバル未満はスキップ
        if now - last_ts < MIN_INTERVAL_SEC:
            continue

        current_turns = count_turns(transcript_path)
        if current_turns <= last_turns:
            continue

        logging.info("Periodic flush: session=%s turns %d→%d", session_id, last_turns, current_turns)

        try:
            flush_session(session_id, transcript_path, cwd=info.get("cwd", ""))
            periodic_state[session_id] = {"timestamp": now, "turn_count": current_turns}
            updated = True
        except Exception as e:
            logging.error("Failed to flush session %s: %s", session_id, e)

    # 終了したセッションのエントリを periodic_state からも掃除
    stale = [sid for sid in periodic_state if sid not in sessions and sid != "_meta"]
    for sid in stale:
        del periodic_state[sid]
        updated = True

    # TL;DR 生成（2時間ごと、日付をまたいだらリセット）
    meta = periodic_state.get("_meta", {})
    last_tldr = meta.get("tldr_timestamp", 0)
    if last_tldr:
        from config import today_iso
        last_tldr_date = datetime.fromtimestamp(last_tldr).strftime("%Y-%m-%d")
        if last_tldr_date != today_iso():
            last_tldr = 0
    if now - last_tldr >= TLDR_INTERVAL_SEC:
        log_path = _today_daily_log_path()
        if log_path:
            log_content = log_path.read_text(encoding="utf-8")
            if len(log_content) > MAX_LOG_CHARS:
                log_content = log_content[-MAX_LOG_CHARS:]
            try:
                tldr = asyncio.run(generate_daily_tldr(log_content))
                if tldr:
                    update_tldr_in_daily_log(log_path, tldr)
                    logging.info("TL;DR updated in %s", log_path.name)
                    meta["tldr_timestamp"] = now
                    periodic_state["_meta"] = meta
                    updated = True
            except Exception as e:
                logging.error("TL;DR generation failed: %s", e)

    # 自動修正（1時間ごと）
    last_self_heal = meta.get("last_self_heal", 0)
    if now - last_self_heal >= SELF_HEAL_INTERVAL_SEC:
        errors = collect_new_errors(since_ts=last_self_heal)
        if errors:
            logging.info("自動修正を起動: %d 件のエラー行を検出", len(errors))
            spawn_self_heal_agent(errors)
        # エラーの有無にかかわらずタイムスタンプを更新（ログ全体の再スキャンを防ぐ）
        meta["last_self_heal"] = now
        periodic_state["_meta"] = meta
        updated = True

    if updated:
        save_periodic_state(periodic_state)


if __name__ == "__main__":
    main()
