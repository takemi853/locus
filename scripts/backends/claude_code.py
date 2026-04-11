"""Claude Code CLI を使ったバックエンド（claude_agent_sdk 経由）。

private 環境向け。システムの `claude` コマンドを使用するため、
Claude Code サブスクリプションで動作する。
"""

from __future__ import annotations

import logging

from backends.base import LLMBackend

logger = logging.getLogger(__name__)

DEFAULT_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]


class ClaudeCodeBackend(LLMBackend):
    """システムの `claude` CLI を claude_agent_sdk 経由で呼び出すバックエンド。"""

    async def text(self, prompt: str) -> str:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )

        response = ""
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=[],
                max_turns=2,
                cli_path="claude",
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text

        return response

    async def agentic(
        self,
        prompt: str,
        cwd: str,
        tools: list[str] | None = None,
        max_turns: int = 30,
    ) -> str:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            query,
        )

        cost = 0.0
        response = ""

        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=cwd,
                system_prompt={"type": "preset", "preset": "claude_code"},
                allowed_tools=tools or DEFAULT_TOOLS,
                permission_mode="acceptEdits",
                max_turns=max_turns,
                cli_path="claude",
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text
            elif isinstance(message, ResultMessage):
                cost = message.total_cost_usd or 0.0

        logger.info("ClaudeCodeBackend agentic cost: $%.4f", cost)
        return response
