"""LLMバックエンドの抽象基底クラス。"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMBackend(ABC):
    """LLM呼び出しの共通インターフェース。

    - text()   : ツールなしのシンプルなテキスト生成（flush, query で使用）
    - agentic(): ファイル操作ツール付きのエージェント実行（compile で使用）
    """

    @abstractmethod
    async def text(self, prompt: str) -> str:
        """プロンプトを渡してテキストを返す（ツールなし）。"""
        ...

    @abstractmethod
    async def agentic(
        self,
        prompt: str,
        cwd: str,
        tools: list[str] | None = None,
        max_turns: int = 30,
    ) -> str:
        """ファイル操作ツール付きでエージェントを実行し、最終的なテキスト出力を返す。

        compile.py のように「ファイルを読んで・書いて・更新する」処理に使う。
        tools が None の場合はデフォルトの Read/Write/Edit/Glob/Grep を使用。
        """
        ...


def load_backend() -> LLMBackend:
    """settings.yaml の設定に基づいてバックエンドを返す。"""
    from config import Settings

    cfg = Settings.load()
    backend_name = cfg.llm.backend

    if backend_name == "claude_code":
        from backends.claude_code import ClaudeCodeBackend
        return ClaudeCodeBackend()
    elif backend_name == "anthropic_api":
        from backends.anthropic_api import AnthropicAPIBackend
        return AnthropicAPIBackend(
            api_key_env=cfg.llm.anthropic.api_key_env,
            model=cfg.llm.model,
        )
    elif backend_name == "vertex_ai":
        from backends.anthropic_api import AnthropicAPIBackend
        return AnthropicAPIBackend(
            api_key_env=cfg.llm.anthropic.api_key_env,
            model=cfg.llm.model,
            vertex=cfg.llm.vertex_ai,
        )
    else:
        raise ValueError(f"未知のバックエンド: {backend_name}")
