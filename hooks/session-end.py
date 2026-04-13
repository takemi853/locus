"""
SessionEnd hook - captures conversation transcript for memory extraction.

When a Claude Code session ends, this hook reads the transcript path from
stdin, extracts conversation context, and spawns flush.py as a background
process to extract knowledge into the daily log.

The hook itself does NO API calls - only local file I/O for speed (<10s).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from _common import detach_popen_kwargs, extract_conversation_context, uv_path

# Recursion guard: if we were spawned by flush.py (which calls Agent SDK,
# which runs Claude Code, which would fire this hook again), exit immediately.
if os.environ.get("CLAUDE_INVOKED_BY"):
    sys.exit(0)

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
STATE_DIR = SCRIPTS_DIR

logging.basicConfig(
    filename=str(SCRIPTS_DIR / "flush.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [hook] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

MAX_TURNS_FULL = 10_000     # SessionEnd: effectively unlimited
MAX_TURNS_PERIODIC = 50    # periodic: recent turns only (earlier turns already flushed)
MIN_TURNS_TO_FLUSH = 1


def main() -> None:
    # Read hook input from stdin
    # Claude Code on Windows may pass paths with unescaped backslashes
    try:
        raw_input = sys.stdin.read()
        try:
            hook_input: dict = json.loads(raw_input)
        except json.JSONDecodeError:
            fixed_input = re.sub(r'(?<!\\)\\(?!["\\])', r'\\\\', raw_input)
            hook_input = json.loads(fixed_input)
    except (json.JSONDecodeError, ValueError, EOFError) as e:
        logging.error("Failed to parse stdin: %s", e)
        return

    session_id = hook_input.get("session_id", "unknown")
    source = hook_input.get("source", "unknown")
    transcript_path_str = hook_input.get("transcript_path", "")
    cwd = hook_input.get("cwd", "")

    logging.info("SessionEnd fired: session=%s source=%s", session_id, source)

    if not transcript_path_str or not isinstance(transcript_path_str, str):
        logging.info("SKIP: no transcript path")
        return

    transcript_path = Path(transcript_path_str)
    if not transcript_path.exists():
        logging.info("SKIP: transcript missing: %s", transcript_path_str)
        return

    # Extract conversation context in the hook (fast, no API calls)
    # Periodic flushes only capture recent turns (earlier turns were already flushed).
    # SessionEnd captures the full session.
    max_turns = MAX_TURNS_PERIODIC if source == "periodic" else MAX_TURNS_FULL
    try:
        context, turn_count = extract_conversation_context(transcript_path, max_turns=max_turns)
    except Exception as e:
        logging.error("Context extraction failed: %s", e)
        return

    if not context.strip():
        logging.info("SKIP: empty context")
        return

    if turn_count < MIN_TURNS_TO_FLUSH:
        logging.info("SKIP: only %d turns (min %d)", turn_count, MIN_TURNS_TO_FLUSH)
        return

    # Write context to a temp file for the background process
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    context_file = STATE_DIR / f"session-flush-{session_id}-{timestamp}.md"
    context_file.write_text(context, encoding="utf-8")

    # Spawn flush.py as a background process
    flush_script = SCRIPTS_DIR / "flush.py"

    cmd = [
        uv_path(),
        "run",
        "--no-sync",
        "--directory",
        str(ROOT),
        "python",
        str(flush_script),
        str(context_file),
        session_id,
        cwd,
    ]

    stderr_log_path = STATE_DIR / "flush_stderr.log"
    try:
        with open(str(stderr_log_path), "a") as stderr_log:
            subprocess.Popen(
                cmd,
                stdout=stderr_log,
                stderr=stderr_log,
                **detach_popen_kwargs(),
            )
        logging.info("Spawned flush.py for session %s (%d turns, %d chars)", session_id, turn_count, len(context))
    except Exception as e:
        logging.error("Failed to spawn flush.py: %s", e)
        context_file.unlink(missing_ok=True)

    # セッション終了をレジストリから削除（periodic フラッシュの場合はセッションは続くので削除しない）
    if source != "periodic":
        try:
            sys.path.insert(0, str(SCRIPTS_DIR))
            from session_registry import unregister
            unregister(session_id)
        except Exception as e:
            logging.error("Failed to unregister session: %s", e)


if __name__ == "__main__":
    main()
