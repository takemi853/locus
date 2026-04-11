---
title: "flush.py バックグラウンドプロセス"
aliases: [flush-py, memory-flush]
tags: [scripts, automation, background-process]
sources:
  - "daily/2026-04-11.md"
created: 2026-04-11
updated: 2026-04-11
---

# flush.py バックグラウンドプロセス

SessionEnd/PreCompact hookから完全に切り離されたバックグラウンドプロセスとして起動され、会話の文脈を `daily/YYYY-MM-DD.md` に書き出すスクリプト。Claude Code のhookプロセスが終了した後も生き続け、保存すべき知識をLLMに判断させて記録する。

## Key Points

- **完全に切り離されたプロセス**として起動する — Mac/Linux では `start_new_session=True`、Windows では `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` フラグを使用
- `CLAUDE_INVOKED_BY=memory_flush` 環境変数を設定してhookの無限再帰を防ぐ（[[connections/hooks-and-recursion-guard]] 参照）
- 同一セッションを60秒以内に2回フラッシュしない重複排除ロジックを持つ（`scripts/last-flush.json` で追跡）
- Claude Agent SDK を使ってLLMに「保存すべき内容か」を判断させ、構造化されたbullet pointsまたは `FLUSH_OK` を返す
- 18時以降のセッション終了時、かつ当日のdailyログが前回コンパイル後に変更されていれば、`compile.py` をさらに別のバックグラウンドプロセスとして起動する

## Details

flush.pyの処理フローは以下の通り：

1. `CLAUDE_INVOKED_BY=memory_flush` を設定して再帰ガードを有効化
2. 事前抽出された会話の文脈（hookが一時ファイルにコピーしたもの）を読み込む
3. コンテキストが空または60秒以内の重複セッションであればスキップ
4. Claude Agent SDK の `query()`（`allowed_tools=[]`、`max_turns=2`）を呼び出す
5. LLMが保存すべき内容を判断 — 有意な知識があればstructured bullet points、なければ `FLUSH_OK` を返す
6. 結果を `daily/YYYY-MM-DD.md` に追記
7. 一時ファイルを削除
8. 18時以降 + dailyログ変更済みの条件が揃えば `compile.py` を別バックグラウンドプロセスとして起動

初回フラッシュはセットアップ直後でコンテキストが空のため失敗することがある（`FLUSH_ERROR` または `FLUSH_OK` with no content）。2回目以降のセッションからは正常動作する。これは期待される挙動。

flush.pyが会話内容を受け取る方法：hookスクリプト（session-end.py / pre-compact.py）がJSONLトランスクリプトファイルをパースして文脈を抽出し、一時的な `.md` ファイルに書き出す。flush.pyはこの一時ファイルを読み込む。hookプロセス内ではパースを行わず、高速性を保つ。

## Related Concepts

- [[concepts/claude-code-hooks]] - flush.pyを起動するhookシステム
- [[concepts/claude-agent-sdk]] - flush.pyが使用するSDK
- [[connections/hooks-and-recursion-guard]] - 無限再帰を防ぐ環境変数ガード
- [[concepts/compile-py]] - flush.pyから起動される後続プロセス

## Sources

- [[daily/2026-04-11.md]] - flush.pyの動作原理とバックグラウンドプロセス設計を詳細に確認
