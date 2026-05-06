---
title: "Claude が設定変更を逆方向に実行するバグ"
aliases: [claude-model-config-bug, reverse-modification]
tags: [claude-code, settings, bug, debugging]
projects: ['Projects']
type: reference
sources:
  - "daily/2026-05-04.md"
created: 2026-05-04
updated: 2026-05-04
verified: true
---

# Claude が設定変更を逆方向に実行するバグ

ユーザーが「`claude-sonnet-4-5` に変更してほしい」と指示しても、Claude が逆方向（`claude-sonnet-4-5` → `claude-sonnet-4-6`）に変更してしまう現象が観測された。根本原因は未調査だが、原因仮説と対策は明記できる。

## Overview

| 項目 | 内容 |
|---|---|
| **発生条件** | ローカル LLM 設定の変更時に Claude に修正を依頼 |
| **症状** | 指示と逆方向のモデル名に修正される |
| **対象ファイル** | `~/.claude/settings.json` の `model` フィールド |
| **状態** | 再修正で対応したが、根本原因は不明 |

## Possible Causes

| 仮説 | 根拠 | 検証方法 |
|---|---|---|
| **自動スケーリング動作** | Claude Code が「より新しいモデルが使える」と判断して自動的に上げる | git log で settings.json の変更履歴を確認；パターンが反復的なら自動化の可能性 |
| **セッション再起動時の再初期化** | `/compact` や `/clear` 後の再起動でデフォルトモデルが書き込まれる | SessionStart フックの挙動を確認 |
| **LLM の理解度不足** | 指示の「変更してほしい」を「アップグレードしてほしい」と誤解 | プロンプト文言の変更で検証可能（「4-6 ではなく 4-5 を使う」と明示） |
| **ファイルロック / 並行書き込み** | 複数プロセスが同時に設定ファイルを修正 | `lsof ~/.claude/settings.json` で確認 |

## Correct Pattern

問題を回避するために、以下の方法を推奨：

```bash
# 方法1：ユーザーが直接編集する（Claude を経由しない）
vim ~/.claude/settings.json
# "model": "claude-sonnet-4-5" に手動で変更

# 方法2：Claude に明示的に指示する
# 「settings.json の model フィールドを 'claude-sonnet-4-5' に変更してほしい。
#  4-6 ではなく 4-5 を使う（ローカル環境では 4-6 は非対応のため）」

# 方法3：変更後に検証
cat ~/.claude/settings.json | grep model
```

## Related Concepts

- [[litellm-model-name-mismatch|LiteLLM モデル名完全一致要件]] — 設定値が一致しないことの影響
- [[claude-code-settings-management|Claude Code 設定ファイル管理]] — settings.json の構造と自動更新メカニズム
- [[session-start-context-injection|SessionStart コンテキスト注入]] — 再起動時の自動設定について

## Sources

- [[logs/daily/2026-05-04.md]] — 「Claudeが設定変更時に指示と逆方向（4-5→4-6）に誤変更するバグが発生」と明記
