"""
定期フラッシュ — launchd / cron から呼び出す。

active-sessions.json に記録されている全セッションを確認し、
前回フラッシュ以降に新しいターンがあればそれぞれ flush を起動する。

複数の Claude Code セッションが同時に開いていても、全て個別に処理する。
SessionEnd が発火しないままクラッシュした場合でも最大5分以内にフラッシュされる。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# 再帰ガード
if os.environ.get("CLAUDE_INVOKED_BY"):
    sys.exit(0)

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
PERIODIC_STATE_FILE = SCRIPTS_DIR / "periodic-state.json"
LOG_FILE = SCRIPTS_DIR / "flush.log"

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [periodic] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

MIN_INTERVAL_SEC = 120  # 各セッションで前回フラッシュから最低2分は待つ


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


def _uv_path() -> str:
    """uv のフルパスを返す（launchd は PATH が最小限なのでフルパス必須）。"""
    candidates = [
        "/Users/takemi/.local/bin/uv",
        "/usr/local/bin/uv",
        "/opt/homebrew/bin/uv",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return "uv"  # フォールバック


def flush_session(session_id: str, transcript_path: Path) -> None:
    """session-end.py を呼んでフラッシュを起動する。"""
    session_end_hook = ROOT / "hooks" / "session-end.py"
    payload = json.dumps({
        "session_id": session_id,
        "transcript_path": str(transcript_path),
        "source": "periodic",
    })
    proc = subprocess.Popen(
        [_uv_path(), "run", "--directory", str(ROOT), "python", str(session_end_hook)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.communicate(input=payload.encode())


def main() -> None:
    sys.path.insert(0, str(SCRIPTS_DIR))
    from session_registry import all_sessions

    sessions = all_sessions()
    if not sessions:
        sys.exit(0)

    periodic_state = load_periodic_state()
    now = time.time()
    updated = False

    for session_id, info in sessions.items():
        transcript_path = Path(info.get("transcript_path", ""))
        if not transcript_path.exists():
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
            flush_session(session_id, transcript_path)
            periodic_state[session_id] = {"timestamp": now, "turn_count": current_turns}
            updated = True
        except Exception as e:
            logging.error("Failed to flush session %s: %s", session_id, e)

    # 終了したセッションのエントリを periodic_state からも掃除
    stale = [sid for sid in periodic_state if sid not in sessions]
    for sid in stale:
        del periodic_state[sid]
        updated = True

    if updated:
        save_periodic_state(periodic_state)


if __name__ == "__main__":
    main()
