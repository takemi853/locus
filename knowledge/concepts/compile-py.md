---
title: "compile.py — ナレッジコンパイラ"
aliases: [compile-py, compiler]
tags: [scripts, automation, knowledge-base]
sources:
  - "daily/2026-04-11.md"
created: 2026-04-11
updated: 2026-04-11
---

# compile.py — ナレッジコンパイラ

`daily/` ディレクトリのログファイルを読み込み、Claude Agent SDK を使ってLLMに `knowledge/` 配下のwiki記事を直接生成・更新させるスクリプト。手動実行と、flush.pyからの自動起動の両方に対応する。

## Key Points

- Claude Agent SDK の非同期ストリーミング `query()` を使用し、`permission_mode="acceptEdits"` で全ファイル操作を自動承認
- AGENTS.md スキーマ・現在のインデックス・既存全記事・dailyログをプロンプトに含めてLLMに渡す
- `scripts/state.json` にdailyログのSHA-256ハッシュを記録し、変更のないファイルの再コンパイルをスキップする増分処理
- コスト：dailyログ1件あたり約$0.45〜$0.65（ナレッジベースの成長に伴い増加）
- `--all` フラグで全ファイルを強制再コンパイル、`--file` で特定ファイルを指定、`--dry-run` で確認のみ

## Details

`compile.py` はClaude Agent SDKの非同期ストリーミングAPIを使用する：

```python
async for message in query(
    prompt=compile_prompt,
    options=ClaudeAgentOptions(
        cwd=str(ROOT_DIR),
        system_prompt={"type": "preset", "preset": "claude_code"},
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
        permission_mode="acceptEdits",
        max_turns=30,
    ),
):
```

`allowed_tools` に Read・Write・Edit・Glob・Grep を指定することでLLMが直接ファイルを読み書きできる。`permission_mode="acceptEdits"` により全ファイル操作の承認プロンプトをスキップする。

増分処理の仕組み：`scripts/state.json` の `ingested` マップにdailyログのファイル名をキーとして、SHA-256ハッシュ・コンパイル日時・コストを記録する。次回実行時にハッシュを比較し、変更がなければそのファイルをスキップする。`--all` フラグはこのチェックを無効化して全ファイルを強制再コンパイルする。

flush.pyからの自動起動：18時以降のセッション終了後、当日のdailyログが変更されていれば、flush.pyがcompile.pyを別のバックグラウンドプロセスとして起動する。これにより手動操作なしで1日1回の自動コンパイルが実現する。

## Related Concepts

- [[concepts/claude-memory-compiler]] - compile.pyを中核とした全体システム
- [[concepts/claude-agent-sdk]] - compile.pyが内部で使用するSDK
- [[concepts/flush-py-background-process]] - compile.pyを自動起動するプロセス
- [[concepts/knowledge-base-index-retrieval]] - コンパイルで生成するインデックス

## Sources

- [[daily/2026-04-11.md]] - compile.pyのアーキテクチャ・CLI・コスト・自動起動の仕組みを確認
