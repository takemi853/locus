---
title: "launchd 最小環境での Claude CLI 認証失敗（USER/LOGNAME/TMPDIR）"
aliases: [launchd-claude-auth-env, launchd-environment-variables]
tags: [launchd, claude-cli, gotcha, environment-variables]
projects: ['locus-project', 'locus-private']
type: concept
sources:
  - "daily/2026-05-03.md"
created: 2026-05-03
updated: 2026-05-03
verified: true
---

# launchd 最小環境での Claude CLI 認証失敗

launchd が起動するプロセスはシェルの最小環境（`/bin/sh`）で動作するため、**USER / LOGNAME / TMPDIR が未定義** になる。Claude CLI は macOS のキーチェーン・Application Support ディレクトリにアクセスするため、これら環境変数がないと認証トークンを読み込めず、**「Not logged in」で無音で exit=1 に失敗する**。

## Key Points

- **問題**: launchd は `$TMPDIR` / `$USER` / `$LOGNAME` が未設定のため、claude が認証ストア（`~/Library/Application Support/Claude/`）を読めない
- **症状**: `claude --print /improve` が exit=256 で失敗。ログに「Not logged in」エラーが出ず、単に黙って落ちる
- **解決**: plist の `<dict>` ブロックに `<key>EnvironmentVariables</key>` セクションを明示的に追加
- **リスク**: 手動実行では問題なくても launchd では詰まるため、テスト段階で気づきにくい

## Details

launchd が `/bin/sh` の最小環境で起動する際、UI アプリの shell 環境変数を引き継がない。Claude CLI は認証トークンを読むために macOS のセキュアストレージにアクセスしようとするが、`$TMPDIR` がないと失敗する。

plist に明示的に環境変数を追加することで解決：

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>USER</key>
    <string>takemi</string>
    <key>LOGNAME</key>
    <string>takemi</string>
    <key>TMPDIR</key>
    <string>/var/folders/abc/xyz/T/</string>
</dict>
```

## Anti-pattern

❌ EnvironmentVariables なし → exit=1 で無音落ち

## Correct Pattern

✅ EnvironmentVariables ブロック明示 → 正常に認証・実行

## Related Concepts

- [[wiki/zshrc-vs-zshenv-launchd|zshrc vs zshenv in launchd]]
- [[wiki/launchd-process-isolation|launchd プロセスアイソレーション]]

## Sources

- [[logs/daily/2026-05-03.md]] — nightly-improve plist に EnvironmentVariables ブロック追加で修復確認
