"""Anthropic SDK を直接使うバックエンド。

work 環境（Vertex AI Workbench など）向け。
Claude Code CLI に依存しないため、どの環境でも動作する。

Vertex AI 経由でも使用可能:
  anthropic[vertex] をインストールして vertex=True を設定する。
"""

from __future__ import annotations

import glob as _glob
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from backends.base import LLMBackend

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]


# ── ローカルファイルツールの実装 ───────────────────────────────────────────────

def _tool_read(path: str, offset: int = 0, limit: int = 2000) -> str:
    p = Path(path)
    if not p.exists():
        return f"ERROR: ファイルが見つかりません: {path}"
    lines = p.read_text(encoding="utf-8").splitlines()
    sliced = lines[offset: offset + limit]
    return "\n".join(f"{offset + i + 1}\t{line}" for i, line in enumerate(sliced))


def _tool_write(path: str, content: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"書き込み完了: {path}"


def _tool_edit(file_path: str, old_string: str, new_string: str) -> str:
    p = Path(file_path)
    if not p.exists():
        return f"ERROR: ファイルが見つかりません: {file_path}"
    content = p.read_text(encoding="utf-8")
    if old_string not in content:
        return f"ERROR: 対象文字列が見つかりません"
    p.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
    return f"編集完了: {file_path}"


def _tool_glob(pattern: str, path: str = ".") -> str:
    base = Path(path)
    matches = list(base.glob(pattern))
    if not matches:
        return "(マッチなし)"
    return "\n".join(str(m) for m in sorted(matches))


def _tool_grep(pattern: str, path: str = ".", glob: str | None = None) -> str:
    cmd = ["grep", "-rn", "--include", glob or "*", pattern, path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout or "(マッチなし)"
    except Exception as e:
        return f"ERROR: {e}"


TOOL_DEFINITIONS = [
    {
        "name": "Read",
        "description": "ファイルを読む",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "offset": {"type": "integer", "default": 0},
                "limit": {"type": "integer", "default": 2000},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "Write",
        "description": "ファイルを作成または上書きする",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "Edit",
        "description": "ファイルの特定文字列を置換する",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "Glob",
        "description": "ファイルをパターンで検索する",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "Grep",
        "description": "ファイル内容を正規表現で検索する",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "glob": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
]


def _dispatch_tool(name: str, inputs: dict[str, Any], cwd: str) -> str:
    """ツール名と引数からローカルのツール実装を呼び出す。"""
    # パスを cwd 基準で解決
    def resolve(p: str) -> str:
        return str(Path(cwd) / p) if not Path(p).is_absolute() else p

    if name == "Read":
        return _tool_read(resolve(inputs["file_path"]), inputs.get("offset", 0), inputs.get("limit", 2000))
    elif name == "Write":
        return _tool_write(resolve(inputs["file_path"]), inputs["content"])
    elif name == "Edit":
        return _tool_edit(resolve(inputs["file_path"]), inputs["old_string"], inputs["new_string"])
    elif name == "Glob":
        return _tool_glob(inputs["pattern"], resolve(inputs.get("path", ".")))
    elif name == "Grep":
        return _tool_grep(inputs["pattern"], resolve(inputs.get("path", ".")), inputs.get("glob"))
    else:
        return f"ERROR: 未知のツール: {name}"


# ── バックエンド本体 ────────────────────────────────────────────────────────────

class AnthropicAPIBackend(LLMBackend):
    """Anthropic Python SDK を直接使うバックエンド。

    vertex=True のとき anthropic[vertex] を使って Vertex AI 経由で動作する。
    """

    def __init__(
        self,
        api_key_env: str = "ANTHROPIC_API_KEY",
        model: str = DEFAULT_MODEL,
        vertex: Any = None,
    ):
        self.model = model
        self.vertex = vertex
        self.api_key_env = api_key_env

    def _client(self):
        if self.vertex:
            import anthropic
            return anthropic.AnthropicVertex(
                project_id=self.vertex.project_id,
                region=self.vertex.location,
            )
        else:
            import anthropic
            api_key = os.environ.get(self.api_key_env)
            if not api_key:
                raise EnvironmentError(f"環境変数 {self.api_key_env} が設定されていません")
            return anthropic.Anthropic(api_key=api_key)

    async def text(self, prompt: str) -> str:
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(None, self._text_sync, prompt)

    def _text_sync(self, prompt: str) -> str:
        client = self._client()
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    async def agentic(
        self,
        prompt: str,
        cwd: str,
        tools: list[str] | None = None,
        max_turns: int = 30,
    ) -> str:
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, self._agentic_sync, prompt, cwd, tools or DEFAULT_TOOLS, max_turns
        )

    def _agentic_sync(
        self, prompt: str, cwd: str, tools: list[str], max_turns: int
    ) -> str:
        """ツールループを自前で回す agentic 実行。"""
        client = self._client()
        active_tools = [t for t in TOOL_DEFINITIONS if t["name"] in tools]

        messages: list[dict] = [{"role": "user", "content": prompt}]
        final_text = ""

        for _ in range(max_turns):
            response = client.messages.create(
                model=self.model,
                max_tokens=8192,
                tools=active_tools,
                messages=messages,
            )

            # アシスタントのメッセージを追加
            messages.append({"role": "assistant", "content": response.content})

            # テキストブロックを収集
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                # ツール呼び出しを実行して結果を返す
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = _dispatch_tool(block.name, block.input, cwd)
                        logger.debug("Tool %s -> %s chars", block.name, len(result))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                messages.append({"role": "user", "content": tool_results})
            else:
                break

        return final_text
