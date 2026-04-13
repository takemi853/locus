"""
複数の Claude Code セッションを同時に追跡するレジストリ。

active-sessions.json の形式:
{
  "<session_id>": {
    "transcript_path": "/path/to/session.jsonl",
    "started_at": "2026-04-12T00:00:00+09:00"
  },
  ...
}
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REGISTRY_FILE = SCRIPTS_DIR / "active-sessions.json"


def _load() -> dict:
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(registry: dict) -> None:
    """tmp ファイル経由でアトミックに書き込む（複数プロセスの同時書き込み対策）。"""
    data = json.dumps(registry, indent=2)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(SCRIPTS_DIR), suffix=".json.tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp_path, str(REGISTRY_FILE))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def register(session_id: str, transcript_path: str, cwd: str = "") -> None:
    """セッション開始時に登録する。"""
    if not session_id or not transcript_path:
        return
    registry = _load()
    registry[session_id] = {
        "transcript_path": transcript_path,
        "started_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "cwd": cwd,
    }
    _save(registry)


def unregister(session_id: str) -> None:
    """セッション終了時に削除する。"""
    if not session_id:
        return
    registry = _load()
    registry.pop(session_id, None)
    _save(registry)


def all_sessions() -> dict[str, dict]:
    """現在アクティブな全セッションを返す。"""
    return _load()
