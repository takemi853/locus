"""hooks 共通ユーティリティ。pre-compact.py と session-end.py で共有する。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def extract_conversation_context(
    transcript_path: Path,
    max_turns: int = 10_000,
    max_context_chars: int = 100_000,
) -> tuple[str, int]:
    """Read JSONL transcript and extract last ~N conversation turns as markdown."""
    turns: list[str] = []

    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg = entry.get("message", {})
            if isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")
            else:
                role = entry.get("role", "")
                content = entry.get("content", "")

            if role not in ("user", "assistant"):
                continue

            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = "\n".join(text_parts)

            if isinstance(content, str) and content.strip():
                label = "User" if role == "user" else "Assistant"
                turns.append(f"**{label}:** {content.strip()}\n")

    recent = turns[-max_turns:]
    context = "\n".join(recent)

    if len(context) > max_context_chars:
        context = context[-max_context_chars:]
        boundary = context.find("\n**")
        if boundary > 0:
            context = context[boundary + 1:]

    return context, len(recent)


def uv_path() -> str:
    """uv のフルパスを返す（launchd は PATH が最小限なのでフルパス必須）。"""
    import os, shutil
    home = Path.home()
    candidates = [
        home / ".local/bin/uv",
        Path("/usr/local/bin/uv"),
        Path("/opt/homebrew/bin/uv"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    found = shutil.which("uv")
    return found if found else "uv"


def detach_popen_kwargs() -> dict:
    """プラットフォームに応じた subprocess.Popen の切り離しオプションを返す。

    On Windows: CREATE_NO_WINDOW でフラッシュコンソールを抑制。
    On macOS/Linux: start_new_session=True で launchd のプロセスグループから切り離す。
    """
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW, "start_new_session": False}
    return {"creationflags": 0, "start_new_session": True}
