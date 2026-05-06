---
title: "Quartz の構造的ミスマッチ — 公開ブログ設計 vs 個人 KB ダッシュボード"
aliases: [quartz-architecture-mismatch, locus-architecture-redesign]
tags: [quartz, locus-architecture, design-decision, gotcha]
projects: ['locus-project', 'locus-private']
type: concept
sources:
  - "daily/2026-05-03.md (20:26-21:32 sessions)"
created: 2026-05-03
updated: 2026-05-03
verified: false
---

# Quartz の構造的ミスマッチ

Quartz は「Obsidian 形式の Markdown ノートを静的サイトとして公開する」ツールとして設計された。これを個人用のダッシュボード・ハブとして毎日使おうとしたとき、根本的なミスマッチが発生している。

## Key Points

- **Quartz の本来の用途**: Markdown wiki を綺麗な静的 HTML に変換して公開（ブログ / ドキュメント向け）
- **Locus での実際の用途**: 毎日の情報ハブ、ランチャー、KB ビューア（個人 KB ダッシュボード向け）
- **構造的矛盾**: 420 行の SCSS + 30 個のカスタムコンポーネントを投じてもなお「微妙」と感じるのは、CSS レベルの問題ではなく設計選択の問題
- **結論**: Quartz の CSS をいくら調整しても個人用途の UX は向上しない。ツール選択の変更が必要

## Details

### Quartz が不適な理由

| 用途 | Quartz の適性 | 理由 |
|---|---|---|
| Markdown wiki の公開 | ✅ 最高 | これが本来の目的 |
| 個人 KB の閲覧 | ⚠️ 微妙 | ビルド必要、静的ファイル走査が遅い |
| ダッシュボール（毎日アクセス） | ❌ 不適 | 複数サービスに分散（:8080/:8081/:8083） |
| インタラクティブ操作 | ❌ 不適 | 静的サイトなので動的機能に限界 |
| モバイル対応 | ⚠️ 弱い | レスポンシブ設計がない |

### 現状の投資規模

```
Quartz カスタマイズ
├─ SCSS: 420行（color, transition, layout 等）
├─ React コンポーネント: 30個
├─ hooks/plugin: 複数
└─ ビルドプロセス: custom config 多数
```

**この投資量で「微妙」と感じるなら、ツール選択が間違っている信号。**

## 2026年時点での代替候補

### SilverBullet

- ✅ Markdown ファイル直読み（ビルド不要）
- ✅ Web ブラウザ UI + モバイル
- ✅ Lua でカスタマイズ可能
- ❌ 双方向リンクが弱い
- 評価: ★★★★☆（最有力候補）

### Docmost

- ✅ UI が最も美しい
- ✅ Web + 整理UI
- ❌ DB 移行が必要（markdown ファイルのままではない）
- 評価: ★★★★☆（UI 重視なら）

### MkDocs Material

- ✅ Markdown 直読み
- ✅ 無料・シンプル
- ❌ ダッシュボード的ではない（ドキュメント向け）
- 評価: ★★★☆☆

### AFFiNE / Anytype / Outline

- ✅ モダン UI
- ❌ すべて DB ベース（markdown ファイル移行できない）
- 評価: UI は良いが都市選択の自由度が低い

### News App 一本化（自作）

- ✅ Python FastAPI + JavaScript で完全カスタマイズ可能
- ✅ 既に foundation がある（8083 で稼働中）
- ✅ `/kb/*` エンドポイントを追加するだけ
- ❌ 工期が短い（1-2日程度）
- 評価: ★★★★★（最現実的）

## 決定フロー

```
「Quartz の UX を改善したい」
    ↓
「CSS をもっと調整すればいい？」
    ↓
「420 行 SCSS + 30 コンポーネント投じたのに微妙…」
    ↓
「ここまで投資してもダメなら、ツール選択が根本的に違う」
    ↓
「Quartz を廃止、News App 一本化へ」
```

## Recommended Action

1. **SilverBullet を試す**（`npx @silverbullet/silverbullet serve ./knowledge`）
   - 評価: 1-2 時間の PoC で判定可能
   - リスク低い（既存 markdown ファイルはそのまま）

2. **評価結果に応じて**
   - SilverBullet OK → 移行を検討
   - SilverBullet NG → News App 一本化に進む（フォールバック）

3. **実装スケジュール**
   - SilverBullet 試用: 2時間
   - News App `/kb` 機能追加: 2-3時間
   - Quartz 廃止: 1時間

## Related Concepts

- [[wiki/news-app-kb-integration|News App KB 統合]]
- [[wiki/locus-architecture|Locus 全体構成（2層設計）]]
- [[wiki/tool-selection-criteria|ツール選択の判断基準]]

## Sources

- [[logs/daily/2026-05-03.md]] — Quartz ナビ修正をきっかけに全体構成を再検討
- Session (21:07-21:35) — ツール比較分析とアーキテクチャ再検討
