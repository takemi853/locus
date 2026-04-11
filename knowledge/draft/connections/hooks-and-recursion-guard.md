---
title: "Connection: Claude Code Hooks と Agent SDK の再帰リスク"
connects:
  - "concepts/claude-code-hooks"
  - "concepts/claude-agent-sdk"
sources:
  - "daily/2026-04-11.md"
created: 2026-04-11
updated: 2026-04-11
verified: false
---

# Connection: Claude Code Hooks と Agent SDK の再帰リスク

Claude Code hooks が Claude Agent SDK を呼び出すと、SDKが新しいClaudeセッションを生成し、そのセッションで再びhookが発火して無限再帰に陥る。`CLAUDE_INVOKED_BY` 環境変数がこのループを断ち切る。

## The Connection

Claude Code のhooksはセッションライフサイクルに応じてコマンドを実行する仕組みだが、hookから Claude Agent SDK を呼び出すと問題が生じる。Agent SDKは内部で新しいClaudeセッションを起動するため、そのセッションで再びSessionEndなどのhookが発火し、また別のAgent SDKを呼び出す——という無限ループが発生する。

## Key Insight

環境変数 `CLAUDE_INVOKED_BY` をガードとして使用する。flush.pyはAgent SDKを呼び出す前に `CLAUDE_INVOKED_BY=memory_flush` を設定し、hookスクリプト（session-end.py / pre-compact.py）は起動時にこの変数が設定されていれば即座に終了する。

```python
# session-end.py の冒頭
if os.environ.get("CLAUDE_INVOKED_BY"):
    sys.exit(0)  # 再帰を検知 → 即時終了
```

```python
# flush.py の冒頭
os.environ["CLAUDE_INVOKED_BY"] = "memory_flush"
# この後にAgent SDKを呼び出す
```

## Evidence

セットアップセッション（2026-04-11）でこの問題を事前に特定し、ガードを実装した。実際の再帰事故が発生する前に対策が講じられている。

再帰が起きると：SessionEnd → flush.py → Agent SDK → 新しいClaudeセッション → SessionEnd → flush.py → … と際限なく続き、APIコストが膨大になる可能性がある。

## Related Concepts

- [[concepts/claude-code-hooks]] - 再帰の引き金となるhookシステム
- [[concepts/claude-agent-sdk]] - 新しいClaudeセッションを生成するSDK
- [[concepts/flush-py-background-process]] - ガードを実装するプロセス

## Sources

- [[daily/2026-04-11.md]] - hooks設定の注意点レビューセッションで問題と対策を確認
