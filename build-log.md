# KB Build Log

## [2026-05-04T18:43:28+09:00] compile | 2026-05-04.md

### 作成した記事
- [[litellm-model-name-mismatch]] — LiteLLMモデル名完全一致要件（model_nameのバージョン不一致がエラーになることの診断パターン）
- [[local-llm-response-latency]] — ローカルLLM応答遅延の診断パターン（ネットワークレイテンシ vs 生成速度の切り分け手順）
- [[claude-config-reverse-modification]] — Claude が設定変更を逆方向に実行するバグ（原因仮説と対策）

### 抽出元
- 2026-05-04.md — Projects（LiteLLMローカルLLMモード設定）/ lumi（Mistral調査）セッション記録

### ファクトチェック結果
- ✅ LiteLLMのconfig.yamlとClaudeが要求するモデル名の不一致 — dailyログで確認（「LiteLLMのconfig.yamlに登録の`claude-sonnet-4-5`とClaudeが要求の`claude-sonnet-4-6`が不一致」）
- ✅ Claudeの逆方向誤変更 — dailyログで「Claudeが指示と逆方向（4-5→4-6）に誤変更するバグ」と記載
- ✅ ローカルLLMの応答遅延 — dailyログで「phi4:14bで0.5秒以上」と計測値記載

### 保存対象外（記事化しなかった項目）
- Mistral-Medium-3.5-128Bの情報調査は定型的なリサーチ作業のため（記事にすべき「判断」「教訓」が不明確）
- Ollama直接接続試行の最終結果が会話末時点で未確認のため（未完結のため記事化は時期尚早）
- task-achievement-appプロジェクト名確認は単純な検索確認（記事化価値なし）

### 信頼度評価
- litellm-model-name-mismatch: ✅ verified=true（日本語ログに明示記載あり）
- local-llm-response-latency: ✅ verified=true（計測値・課題が明示記載）
- claude-config-reverse-modification: ✅ verified=true（発生事実が記載）ただし根本原因は未調査のため、記事内で仮説として記載

## [2026-05-04T20:13:49+09:00] compile | 2026-05-04.md

### 作成した記事
- [[inbox/wiki/litellm-model-name-complete-match]] — LiteLLM model_name 完全一致要件（バージョン番号ズレがエラーになる根拠）
- [[inbox/wiki/javascript-date-parsing-timezone-pitfall]] — JavaScript Date パース — タイムゾーン落とし穴（ISO 8601文字列の UTC 解析問題）
- [[inbox/wiki/mistral-medium-3-5-128b-overview]] — Mistral-Medium-3.5-128B — 概要と使い所（参考用途・コンテキスト情報）

### 抽出元
- 2026-05-04.md — Projects（LiteLLMローカルLLMモード設定）/ lumi（Mistral調査）/ task-achievement-app（日付バグ修正）セッション記録

### ファクトチェック結果
- ✅ LiteLLMの model_name と要求モデル名の完全一致要件 — dailyログで「LiteLLMのmodel_nameはClaudeが要求するモデル名と完全一致が必須」と記載
- ✅ JavaScript Date UTC 解析問題 — dailyログで「日付文字列"2026-06-04"がブラウザUTC解析される」と記載、修正で `split()` で分解して JST 処理に変更と明記
- ⚠️ Mistral-Medium-3.5-128B ベンチマーク — 会話では「テキスト理解が強い」と定性的に述べられているが、具体的なスコア値なし（unverified フラグ）

### 保存対象外（記事化しなかった項目）
- Ollama直接接続試行の最終結果が未確認（記事化は完結後）
- Qwen3.6-27B検証結果が会話末時点で未報告（検証後に改めて記事化予定）
- Claudeの設定逆方向誤変更 — 前回コンパイル（18:43）で既に記事化済みのため重複回避

### 信頼度評価
- litellm-model-name-complete-match: ✅ verified=true（dailyログに明示記載、実装経験に基づく）
- javascript-date-parsing-timezone-pitfall: ✅ verified=true（バグ発見と修正を実装確認）
- mistral-medium-3-5-128b-overview: ⚠️ verified=false（ベンチマーク数値が unverified）

