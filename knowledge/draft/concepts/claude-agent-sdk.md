---
title: "Claude Agent SDK"
aliases: [agent-sdk, claude-sdk]
tags: [sdk, claude, api]
sources:
  - "daily/2026-04-11.md"
created: 2026-04-11
updated: 2026-04-11
verified: false
---

# Claude Agent SDK

PythonからClaudeをプログラム的に実行するためのSDK。ツールアクセス付きのエージェントとして動作し、Claude Codeの組み込みCLI認証情報を使用するためAPIキーが不要。

## Key Points

- `~/.claude/.credentials.json` に保存されたClaude Code のCLI認証情報を自動使用 — Anthropic APIキーの設定が不要
- 非同期ストリーミング `query()` でLLMを呼び出す。`allowed_tools`・`permission_mode`・`max_turns` などを `ClaudeAgentOptions` で指定
- `permission_mode="acceptEdits"` でファイル操作の承認プロンプトをスキップし、バックグラウンド処理に対応
- hookから呼び出す場合は無限再帰のリスクがある（[[connections/hooks-and-recursion-guard]] 参照）
- 内部で bundled CLI（`_bundled/claude`）を使って非同期にエージェントを実行する

## Details

Claude Agent SDK の基本的な使用パターン：

```python
async for message in query(
    prompt=prompt_text,
    options=ClaudeAgentOptions(
        cwd=str(project_root),
        system_prompt={"type": "preset", "preset": "claude_code"},
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
        permission_mode="acceptEdits",
        max_turns=30,
    ),
):
    # ストリーミングメッセージを処理
```

`flush.py` での使用例（ツールなし・短い会話）：

```python
async for message in query(
    prompt=flush_prompt,
    options=ClaudeAgentOptions(
        allowed_tools=[],
        max_turns=2,
    ),
):
```

`allowed_tools=[]` はLLMにツール使用を許可しない（純粋なテキスト生成のみ）。`max_turns=2` は往復の上限を設定してコストを抑える。

依存関係：`pyproject.toml` に `claude-agent-sdk>=0.1.29` として記載。`uv` でパッケージ管理し、`uv run python scripts/compile.py` のように実行する。Python 3.12以上が必要。

## Related Concepts

- [[concepts/compile-py]] - Agent SDKを使ってwiki記事を生成するスクリプト
- [[concepts/flush-py-background-process]] - Agent SDKでLLMに保存価値を判断させるプロセス
- [[connections/hooks-and-recursion-guard]] - SDKがhookを再帰的に呼び出すリスクと対策

## Sources

- [[daily/2026-04-11.md]] - compile.pyとflush.pyの実装でAgent SDKの動作原理を確認
