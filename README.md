# Locus — パーソナルナレッジベース

Claude Code との会話が自動でナレッジベースに蓄積されるシステムです。

セッションが終わるたびに会話の要点を抽出・記事化し、次のセッション開始時にコンテキストとして注入します。使えば使うほど Claude があなたの過去の知識を参照できるようになります。

---

## 仕組み

```
会話
  └─ SessionEnd/PreCompact hook
        └─ flush.py（要約 → daily/YYYY-MM-DD.md）
              └─ compile.py（記事化 → knowledge/draft/）
                    └─ review.py（承認 → knowledge/concepts/）
                          └─ SessionStart hook（次回会話にインデックスを注入）
```

- **RAGなし** — インデックスファイルをLLMが直接読む方式（個人スケールでは精度が高い）
- **複数セッション対応** — 同時に複数の Claude Code を開いていても全て追跡
- **クラッシュ耐性** — 5分ごとの定期フラッシュで SessionEnd が発火しなくても補完
- **真偽チェック** — 自動生成は `draft/` に置き、`review.py` でレビューしてから公開

---

## リポジトリ構成

このシステムは **2つのリポジトリ** で運用します。

| リポジトリ | 内容 | 共有 |
|---|---|---|
| `locus`（本リポジトリ） | スクリプト・hooks・設定 | private / work 共通 |
| `locus-private`（データリポジトリ） | `daily/` `knowledge/` | 環境ごとに独立 |

環境ごとに `settings.yaml` の `data_dir` でデータリポジトリの場所を指定します。

---

## セットアップ（新しいPCで1から）

### 前提条件

- [Claude Code](https://claude.ai/code) インストール済み・ログイン済み
- [uv](https://docs.astral.sh/uv/) インストール済み
- SSH鍵が GitHub に登録済み

---

### 1. リポジトリをクローン

```bash
# システムリポジトリ（スクリプト・hooks）
git clone git@github.com:takemi853/my-knowledge-base.git ~/Projects/app/locus
cd ~/Projects/app/locus
uv sync

# データリポジトリ（daily/ / knowledge/ を格納）
# private 環境:
git clone git@github.com:takemi853/locus-private.git ~/Projects/locus-private
# work 環境（例）:
# git clone git@github.com:takemi853/knowledge-work.git ~/Projects/knowledge-work
```

---

### 2. data_dir を設定

`settings.yaml` の `data_dir` をデータリポジトリの場所に合わせます。

```yaml
data_dir: ~/Projects/locus-private   # private 環境
# data_dir: ~/Projects/knowledge-work    # work 環境
```

---

### 3. グローバルhooksを設定

`~/.claude/settings.json` に以下を追加（既存の設定がある場合はマージ）：

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "cd /Users/yourname/Projects/app/locus && uv run python hooks/session-start.py",
        "timeout": 15
      }]
    }],
    "PreCompact": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "cd /Users/yourname/Projects/app/locus && uv run python hooks/pre-compact.py",
        "timeout": 10
      }]
    }],
    "SessionEnd": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "cd /Users/yourname/Projects/app/locus && uv run python hooks/session-end.py",
        "timeout": 10
      }]
    }]
  }
}
```

> パスは実際の環境に合わせて変更してください。

---

### 4. 定期フラッシュを有効化

クラッシュ時でも最大5分以内にフラッシュされるよう設定します。

#### macOS（launchd）

```bash
# uv のパスを確認
which uv  # → /Users/yourname/.local/bin/uv

# com.claude-kb.flush.plist 内の uv パスが一致しているか確認・修正

# インストール
cp com.claude-kb.flush.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.claude-kb.flush.plist

# 確認
launchctl list | grep claude-kb  # → - 0 com.claude-kb.flush
```

#### Linux / GCP Vertex AI Workbench（cron）

```bash
# crontab を編集
crontab -e

# 以下を追記（5分ごとに実行）
*/5 * * * * cd ~/Projects/app/locus && uv run python scripts/flush_periodic.py >> /tmp/claude-kb-flush.log 2>&1

# 確認
crontab -l
```

---

### 5. Claude Code を再起動

一度閉じて再起動すると hooks が有効になります。**これ以降に開いたセッションから自動で追跡・記録が始まります。**

---

### 6. UIビューアのセットアップ（任意）

ブラウザでナレッジを閲覧したい場合は [Quartz](https://quartz.jzhao.xyz/) を使います。

```bash
cd ~/Projects/app
git clone https://github.com/jackyzha0/quartz.git knowledge-ui
cd knowledge-ui
npm ci
rm -rf content
ln -s ~/Projects/locus-private/knowledge content   # data_dir に合わせる
npx quartz build --serve  # → http://localhost:8080
```

---

## 日常の使い方

### 自動で行われること（何もしなくていい）

| タイミング | 処理 |
|---|---|
| セッション開始時 | ナレッジのインデックスを会話に注入 |
| セッション終了時 | 会話を要約して `daily/` に保存 |
| 5分ごと（launchd） | 未保存のターンを定期チェック・フラッシュ |
| 18時以降の終了時 | `daily/` を自動コンパイル → `knowledge/draft/` に生成 |

### 手動コマンド

```bash
cd ~/Projects/app/locus

# ドラフト記事をレビュー・承認
uv run python scripts/review.py
uv run python scripts/review.py --list   # 一覧のみ表示
uv run python scripts/review.py --all    # 全て承認

# 今すぐコンパイル
uv run python scripts/compile.py

# ナレッジに質問
uv run python scripts/query.py "SwiftUIの非同期処理は？"
uv run python scripts/query.py "質問" --file-back  # 回答を qa/ にも保存

# ヘルスチェック
uv run python scripts/lint.py
```

### review.py の操作

```
[y] 承認 → knowledge/concepts/ に昇格・index.md に追記
[n] 却下 → draft から削除
[e] エディタで編集 → 再表示
[s] スキップ（後回し）
[q] 終了
```

記事には **確信度（1〜5）** と **要確認リスト** が表示されます。

### ナレッジの同期（PC間）

```bash
# データリポジトリを更新（1日1回程度）
cd ~/Projects/locus-private
git add .
git commit -m "ナレッジ更新"
git push

# 別のPCで
git pull
```

---

## ファイル構成

```
locus/          ← システムリポジトリ（スクリプト）
├── hooks/
│   ├── session-start.py      セッション開始：コンテキスト注入・セッション登録
│   ├── session-end.py        セッション終了：フラッシュ起動・セッション削除
│   └── pre-compact.py        自動圧縮前：フラッシュ起動
├── scripts/
│   ├── flush.py              会話を要約して daily/ に書き出す
│   ├── flush_periodic.py     定期フラッシュ（launchd から呼ばれる）
│   ├── compile.py            daily/ → knowledge/draft/ に記事生成
│   ├── review.py             draft → verified への昇格レビュー
│   ├── query.py              ナレッジへの質問
│   ├── lint.py               ヘルスチェック
│   ├── session_registry.py   複数セッションの追跡
│   └── backends/             LLMバックエンド抽象化
├── settings.yaml             環境設定（data_dir でデータ置き場を指定）
└── com.claude-kb.flush.plist macOS launchd 設定

locus-private/               ← データリポジトリ（data_dir で指定）
├── daily/                    会話の要約ログ（自動生成）
└── knowledge/
    ├── draft/                未レビュー記事（compile.py が生成）
    ├── concepts/             レビュー済み記事
    ├── connections/          概念間の関係記事
    ├── qa/                   query --file-back で保存した Q&A
    └── index.md              全記事の目次（セッション開始時に注入）
```

---

## settings.yaml

```yaml
environment: private   # または work

data_dir: ~/Projects/locus-private  # データリポジトリの場所

llm:
  backend: claude_code  # claude_code | anthropic_api | vertex_ai
  model: claude-sonnet-4-6

knowledge:
  compile_after_hour: 18  # 自動コンパイル開始時刻
  language: ja            # 記事の言語
```

---

## 環境別セットアップ

### private（Mac）

```yaml
# settings.yaml
environment: private
data_dir: ~/Projects/locus-private
llm:
  backend: claude_code
  model: claude-sonnet-4-6
```

定期フラッシュは launchd（手順4参照）。

---

### work（GCP Vertex AI Workbench）

```yaml
# settings.yaml
environment: work
data_dir: ~/Projects/knowledge-work
llm:
  backend: vertex_ai
  model: claude-sonnet-4-6
  vertex_ai:
    project_id: your-gcp-project-id
    location: us-central1
```

定期フラッシュは cron（手順4参照）。

データリポジトリの初回作成：

```bash
# GitHub で knowledge-work リポジトリを作成後
git clone git@github.com:yourname/knowledge-work.git ~/Projects/knowledge-work

# または既存データなしで新規作成
mkdir -p ~/Projects/knowledge-work && cd ~/Projects/knowledge-work && git init
git remote add origin git@github.com:yourname/knowledge-work.git
```

---

### データリポジトリの初回 GitHub プッシュ

```bash
# GitHub CLI で private リポジトリを作成してプッシュ
cd ~/Projects/locus-private
gh repo create yourname/locus-private --private
git remote add origin git@github.com:yourname/locus-private.git
git push -u origin main
```

---

## トラブルシューティング

### フラッシュが動かない

```bash
tail -20 scripts/flush.log
uv run python scripts/flush_periodic.py  # 手動テスト
```

### launchd が起動しない

```bash
cat /tmp/claude-kb-flush-error.log

# plist の uv パスを修正後、再読み込み
launchctl unload ~/Library/LaunchAgents/com.claude-kb.flush.plist
launchctl load ~/Library/LaunchAgents/com.claude-kb.flush.plist
```

### セッションが追跡されていない

hooks 設定前に開始したセッションは登録されません。手動で登録できます：

```bash
python -c "
import sys; sys.path.insert(0, 'scripts')
from session_registry import register
register('SESSION_ID', '/path/to/transcript.jsonl')
# transcript は ~/.claude/projects/ 以下にある .jsonl ファイル
"
```
