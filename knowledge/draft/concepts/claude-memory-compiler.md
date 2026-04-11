---
title: "Claude Memory Compiler"
aliases: [memory-compiler, claude-kb]
tags: [system, automation, knowledge-base]
sources:
  - "daily/2026-04-11.md"
created: 2026-04-11
updated: 2026-04-11
verified: false
---

# Claude Memory Compiler

Claude Code の会話を自動でナレッジベースに蓄積するシステム。Andrej Karpathy の LLM Knowledge Base アーキテクチャを個人の AI コーディングセッションに応用したもので、会話から知識を抽出・構造化・検索可能にする。

## Key Points

- 会話ログ（`daily/`）→ コンパイル（LLM）→ 構造化ナレッジ（`knowledge/`）というコンパイラの比喩でシステムを設計
- Claude Code の hooks（SessionStart / PreCompact / SessionEnd）によって会話の自動キャプチャと注入を実現
- RAGなしでインデックスファイルだけを使った検索を採用（個人スケールではLLMがインデックスを読む方が精度が高い）
- グローバルhooks（`~/.claude/settings.json`）に絶対パスで登録することで全プロジェクトで動作
- 18時以降のセッション終了時に自動でコンパイルがトリガーされる

## Details

システムのアーキテクチャはコンパイラの比喩で整理される。`daily/` ディレクトリが「ソースコード」（会話ログ）、LLM が「コンパイラ」（知識の抽出・整理）、`knowledge/` ディレクトリが「実行ファイル」（構造化・検索可能なナレッジ）に相当する。ユーザーは手動でナレッジを整理する必要がなく、会話を続けるだけでLLMが合成・クロスリファレンス・メンテナンスを行う。

データフローは次の通り：会話が終了すると SessionEnd/PreCompact hook が `flush.py` を呼び出し、会話内容を `daily/YYYY-MM-DD.md` に書き出す。その後 `compile.py` が daily ログを読み込んで `knowledge/` 配下に記事を生成する。次回セッション開始時に SessionStart hook がナレッジベースのインデックスと最新ログをコンテキストに注入する。

プロジェクトローカルの `.claude/settings.json` にはhooksを入れないことが重要。グローバルとローカルの両方に同じhookがあると同一セッションで2回発火してしまう。

## Related Concepts

- [[concepts/claude-code-hooks]] - 自動キャプチャを実現するhookシステム
- [[concepts/flush-py-background-process]] - 会話内容をdailyログに書き出すバックグラウンドプロセス
- [[concepts/compile-py]] - dailyログをwiki記事にコンパイルするスクリプト
- [[concepts/knowledge-base-index-retrieval]] - RAGなしのインデックスベース検索

## Sources

- [[daily/2026-04-11.md]] - システムのセットアップと動作確認セッションで全体アーキテクチャを確立
