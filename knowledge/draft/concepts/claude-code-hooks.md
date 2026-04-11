---
title: "Claude Code Hooks"
aliases: [hooks, session-hooks]
tags: [claude-code, automation, hooks]
sources:
  - "daily/2026-04-11.md"
created: 2026-04-11
updated: 2026-04-11
verified: false
---

# Claude Code Hooks

Claude Code のライフサイクルイベントに応じてシェルコマンドを自動実行する仕組み。SessionStart・PreCompact・SessionEnd の3種類のhookがあり、`.claude/settings.json` に設定する。

## Key Points

- **SessionStart** — セッション開始時に発火。ナレッジベースのインデックスや最新ログをコンテキストに注入するために使う。API呼び出しなしの純粋なローカルI/Oで1秒以内に完了する必要がある
- **PreCompact** — コンテキストウィンドウの自動圧縮前に発火。長時間セッションで圧縮によって失われる文脈を事前にキャプチャする
- **SessionEnd** — セッション終了時に発火。会話内容をdailyログに書き出す処理を起動する
- グローバル（`~/.claude/settings.json`）とプロジェクトローカル（`.claude/settings.json`）に同じイベントのhookが両方存在すると**同一セッションで2回発火**する — 片方にのみ登録すること
- 既知のバグ（Claude Code Issue #13668）：長時間セッションのPreCompactイベントで `transcript_path` が空になることがある — hookスクリプトで空パスのガードが必須

## Details

hooksの設定は `.claude/settings.json` の `hooks` キーに記述する。各hookは `matcher`（空文字列で全イベントにマッチ）と `hooks` 配列（`type: "command"` と `command`、`timeout` を指定）で構成される。

```json
{
  "hooks": {
    "SessionStart": [{ "matcher": "", "hooks": [{ "type": "command", "command": "uv run python hooks/session-start.py", "timeout": 15 }] }],
    "PreCompact": [{ "matcher": "", "hooks": [{ "type": "command", "command": "uv run python hooks/pre-compact.py", "timeout": 10 }] }],
    "SessionEnd": [{ "matcher": "", "hooks": [{ "type": "command", "command": "uv run python hooks/session-end.py", "timeout": 10 }] }]
  }
}
```

SessionStart hookは stdout にJSON（`{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`）を出力することでClaudeのコンテキストに情報を注入できる。最大20,000文字。

SessionEnd と PreCompact hookは stdin からJSON（`session_id`、`transcript_path`、`cwd` を含む）を受け取る。`transcript_path` は Claude Code が会話を保存しているJSONLファイルへのパスで、PreCompactイベントでは空になることがある（Issue #13668）。

**PreCompactとSessionEndの両方が必要な理由：** 長時間セッションでは1回のセッション中に複数回の自動圧縮が発生することがある。PreCompactがなければ、SessionEndが発火する前に中間の文脈が圧縮によって失われてしまう。

## Related Concepts

- [[concepts/claude-memory-compiler]] - hooksを活用した全体システム
- [[concepts/flush-py-background-process]] - SessionEnd/PreCompactから呼び出されるバックグラウンドプロセス
- [[connections/hooks-and-recursion-guard]] - hooksとAgent SDKの再帰リスクと対策

## Sources

- [[daily/2026-04-11.md]] - セットアップセッションでhookの設定方法と落とし穴を詳細に検討
