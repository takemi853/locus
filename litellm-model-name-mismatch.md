---
title: "LiteLLM モデル名完全一致要件"
aliases: [model-name-mismatch, litellm-model-mapping]
tags: [llm, litellm, local-llm, configuration]
projects: ['Projects']
type: pattern
sources:
  - "daily/2026-05-04.md"
created: 2026-05-04
updated: 2026-05-04
verified: true
---

# LiteLLM モデル名完全一致要件

LiteLLM の `config.yaml` に登録された `model_name` は、Claude Code が要求するモデル名と**完全一致**している必要がある。バージョン番号のズレ（例：4-5 vs 4-6）でも LiteLLM はマッピングに失敗してエラーになる。

## Key Points

- **モデル名の完全一致が必須**：`claude-sonnet-4-5` と `claude-sonnet-4-6` は別エントリとして扱われる
- **ローカル LLM では非対応バージョンがある**：Ollama など一部ローカル実装では新バージョンモデルをサポートしていない場合がある
- **設定ファイルの事前確認**：Claude Code がどのバージョンを要求するかと、LiteLLM に登録されているバージョンを事前にチェックすること

## Anti-pattern

❌ **ズレたバージョンを登録する**
```yaml
# config.yaml
model_list:
  - model_name: claude-sonnet-4-5    # ← LiteLLM の登録
    litellm_params:
      model: ollama/qwen2.5-coder:32b
      api_base: http://localhost:11434

# Claude Code が claude-sonnet-4-6 を要求
# → LiteLLM がマッピングエントリを見つけられず、エラー
```

## Correct Pattern

✅ **Claude Code が要求するバージョンで統一する**
```yaml
# config.yaml
model_list:
  - model_name: claude-sonnet-4-5    # ← Claude Code が要求するバージョンと一致
    litellm_params:
      model: ollama/qwen2.5-coder:32b
      api_base: http://localhost:11434

# Claude Code settings.json
{
  "model": "claude-sonnet-4-5"        # ← config.yaml と同じバージョン
}
```

## When to Apply

- ローカル LLM プロキシ（LiteLLM）を使う時
- Claude Code のモデル設定を変更する時
- 新しい LLM バージョンがリリースされて設定を更新する時

## Details

### 実際の事例（2026-05-04）

Claude Code が `claude-sonnet-4-6` を要求していたが、LiteLLM の `config.yaml` には `claude-sonnet-4-5` しか登録されていなかった。その結果：

```
Error: model 'claude-sonnet-4-6' not found in LiteLLM proxy
```

ローカル環境では Ollama の Qwen モデルのみ利用可能だったため、Claude Code 側の設定を 4-5 に変更することで解決した。

### LiteLLM のマッピング仕組み

1. Claude Code が LiteLLM に「`claude-sonnet-4-6` を使いたい」とリクエスト
2. LiteLLM が `config.yaml` の `model_list` で `model_name: claude-sonnet-4-6` を探す
3. 見つからない場合 → エラー（部分一致は無視される）
4. 見つかった場合 → `litellm_params.model` の実際の LLM にリクエストを転送

## Related Concepts

- [[litellm-ollama-bridge|LiteLLM + Ollama による Claude Code ローカル LLM ブリッジ]] — 全体的なセットアップパターン
- [[local-llm-model-versioning|ローカル LLM モデルバージョン管理]] — 複数バージョン共存パターン

## Sources

- [[logs/daily/2026-05-04.md]] — セッション記録で「LiteLLMのconfig.yamlに登録の`claude-sonnet-4-5`とClaudeが要求の`claude-sonnet-4-6`が不一致」と明記されている
