---
title: "ローカルLLM応答遅延の診断パターン"
aliases: [local-llm-latency, ollama-response-time]
tags: [local-llm, ollama, performance, debugging]
projects: ['Projects']
type: how-to
sources:
  - "daily/2026-05-04.md"
created: 2026-05-04
updated: 2026-05-04
verified: true
---

# ローカルLLM応答遅延の診断パターン

ローカル LLM（Ollama など）の応答遅延は、**ネットワークレイテンシ** と **モデルの生成速度** の 2 つの原因が考えられる。問題の根本を切り分けるまで、最適化判断ができない。

## Prerequisites

- Ollama が起動している（`http://localhost:11434` でアクセス可能）
- LiteLLM プロキシを使用している（オプション）
- curl や直接 API 呼び出しでテストできる環境

## Steps

1. **直接 API でテストして基準遅延を測定する**
   ```bash
   # Ollama 直接アクセス（ネットワークレイテンシのベース値）
   time curl -X POST http://localhost:11434/api/generate \
     -d '{"model": "phi4:14b", "prompt": "hello", "stream": false}'
   ```
   実測値で応答時間を確認（タイムスタンプ前後）

2. **同じモデルで複数リクエストを送ってメディアン遅延を確認**
   ```bash
   for i in {1..5}; do
     echo "Request $i:"
     time curl -X POST http://localhost:11434/api/generate \
       -d '{"model": "phi4:14b", "prompt": "test", "stream": false}' \
       -s | jq -r '.response' | head -c 50
     echo ""
   done
   ```
   初回は遅くなる傾向（モデルのメモリ読み込み）

3. **異なるモデルで比較テストを実施**
   ```bash
   # 軽量モデル（qwen2.5-coder:1.5b）の遅延を測定
   time curl -X POST http://localhost:11434/api/generate \
     -d '{"model": "qwen2.5-coder:1.5b", "prompt": "hello"}'
   
   # 大規模モデル（qwen3.6-27b）の遅延を測定
   time curl -X POST http://localhost:11434/api/generate \
     -d '{"model": "qwen3.6:27b-a3b", "prompt": "hello"}'
   ```
   モデル間の差異を定量化

4. **LiteLLM プロキシ経由の遅延と直接接続の遅延を比較**
   ```bash
   # LiteLLM 経由（プロキシオーバーヘッド含む）
   time curl -X POST http://localhost:8000/v1/completions \
     -H "Authorization: Bearer fake" \
     -d '{"model": "claude-sonnet-4-5", "prompt": "hello", "max_tokens": 10}'
   
   # Ollama 直接
   time curl -X POST http://localhost:11434/api/generate \
     -d '{"model": "qwen2.5-coder:32b", "prompt": "hello", "stream": false}'
   ```

5. **ネットワーク vs 計算処理の切り分け**
   - **ネットワークが原因**：LiteLLM 経由の方が遅延が大きい（プロキシオーバーヘッド）
   - **計算処理が原因**：直接 Ollama でも遅延が大きい（モデルの推論速度が遅い）

## Caveats

- 初回実行は遅くなる：モデルが GPU メモリに読み込まれていないため
- GPU メモリ容量が限界に達すると、モデル切り替え時に遅延が増加
- CPU のみでの推論は極めて遅い（ARM Mac で Ollama を動かす場合）
- Claude Code が期待するプロンプト形式とローカル LLM の理解度のギャップは別の問題

## Related Concepts

- [[litellm-model-name-mismatch|LiteLLM モデル名完全一致要件]] — 設定レイヤの問題との区別
- [[ollama-model-selection|Ollama モデル選定基準]] — パフォーマンスとメモリの兼ね合い
- [[local-llm-prompt-format-gap|ローカルLLM×Claude のプロンプト形式ギャップ]] — 応答速度ではなく応答品質の問題

## Sources

- [[logs/daily/2026-05-04.md]] — 「ローカルLLM応答遅延（phi4:14bで0.5秒以上）がネットワークレイテンシか生成速度かの切り分けが課題」と記載
