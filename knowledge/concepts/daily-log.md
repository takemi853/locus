---
title: "Daily Log"
aliases: [daily-log, session-log]
tags: [system, automation, daily]
sources:
  - "daily/2026-04-11.md"
created: 2026-04-11
updated: 2026-04-11
---

# Daily Log

`daily/YYYY-MM-DD.md` に日ごとに蓄積される会話ログ。セッション終了時に自動で生成・追記される「生ログ」で、[[concepts/compile-py]] によって `knowledge/` 記事にコンパイルされる元ネタ。

## Key Points

- `daily/` は入力（生ログ）、`knowledge/` は出力（構造化記事）という役割分担
- セッション終了ごとに `flush.py` が自動追記（手動操作不要）
- 1日複数セッションがあれば `### Session (HH:MM)` セクションが積み重なる
- Quartz の `content/daily/` にシンボリックリンクを張ればブラウザで閲覧可能

## ファイル構造

```
daily/
  2026-04-11.md
  2026-04-12.md
  ...
```

各ファイルの構造：

```markdown
# Daily Log: YYYY-MM-DD

## Sessions

### Session (HH:MM)

**Context:** 何をしていたか
**Key Exchanges:** ...
**Decisions Made:** ...
**Lessons Learned:** ...
**Action Items:** ...

<!-- confidence: X/5 -->

### Memory Flush (HH:MM)

FLUSH_OK - Nothing worth saving from this session

## Memory Maintenance
```

## 生成フロー

```
Claude Code セッション終了
  ↓
session-end.py (hook)
  ↓ transcript から会話テキストを抽出してファイルに保存
flush.py (バックグラウンドプロセス)
  ↓ Claude Agent SDK で要約・重要情報を抽出
daily/YYYY-MM-DD.md に追記
  ↓ (18時以降のみ自動)
compile.py → knowledge/ 記事を更新
```

## セクション種別

| セクション | 意味 |
|---|---|
| `### Session (HH:MM)` | 重要な内容があったセッション |
| `### Memory Flush (HH:MM)` | `FLUSH_OK`（保存すべき内容なし）または `FLUSH_ERROR` |

## Quartzでの閲覧

`knowledge-ui/content/daily` にシンボリックリンクを張ることで `http://localhost:8080/daily/YYYY-MM-DD` で閲覧可能。生ログなので公開用途には向かない。

```bash
ln -s /path/to/claude-memory-compiler/daily \
      /path/to/knowledge-ui/content/daily
```

## Related Concepts

- [[concepts/flush-py-background-process]] - dailyログへの書き出しプロセス
- [[concepts/compile-py]] - dailyログを構造化記事にコンパイル
- [[concepts/claude-code-hooks]] - セッション終了を検知するhook
- [[concepts/claude-memory-compiler]] - システム全体のアーキテクチャ
