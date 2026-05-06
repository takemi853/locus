---
title: "News App へのナレッジベース API・UI 統合（Phase 1-3）"
aliases: [news-app-kb-integration, kb-api-implementation, kb-ui-panel]
tags: [news-app, kb-api, fastapi, frontend, integration]
projects: ['locus-project', 'locus-private']
type: how-to
sources:
  - "daily/2026-05-03.md (21:42-21:57 sessions)"
created: 2026-05-03
updated: 2026-05-03
verified: true
---

# News App へのナレッジベース API・UI 統合

News App (port 8083) にナレッジベース API エンドポイントとフロントエンド UI パネルを統合し、Quartz (8080) の機能を徐々に一本化する Phase 1-3 実装を完了した。

## Key Points

- **Phase 1**: GET /api/kb, /api/kb/{path}, /api/kb-search エンドポイント実装
- **Phase 2**: キャッシュ付き /api/kb/tags（376タグ）、/api/kb/sidebar 実装
- **Phase 3**: HTML に .kb-panel div・CSS・JavaScript（showKbFile/searchKb）追加
- **ルート順序**: FastAPI は定義順序が重要。汎用パターン `{path:path}` より具体的なルートを先に定義
- **レスポンス速度**: スタートアップキャッシュで 15ms 実現

## How to Implement

### Step 1: Phase 1 エンドポイント追加

news_app.py に以下を追加（routes セクション）：

```python
@app.get("/api/kb")
def list_kb():
    """KB ファイル一覧を返す"""
    kb_root = _get_knowledge_dir()
    # ... ファイル走査ロジック
    return {"files": [...]}

@app.get("/api/kb/{path:path}")
def get_kb_file(path: str):
    """Markdown ファイルを読み込んで frontmatter + body を返す"""
    kb_root = _get_knowledge_dir()
    file_path = kb_root / f"{path}.md"
    # ... ファイル読み込み、YAML frontmatter 抽出
    return {"path": path, "metadata": {...}, "body": "..."}

@app.get("/api/kb-search")
def search_kb(q: str):
    """全文検索"""
    # ... TF-IDF or grep 検索
    return {"results": [...]}
```

### Step 2: Phase 2 キャッシュ付きエンドポイント

スタートアップイベントでメモリキャッシュを構築：

```python
@app.on_event("startup")
async def build_kb_cache():
    global KB_CACHE
    KB_CACHE = {
        "tags": _extract_all_tags(),
        "sidebar": _build_sidebar(),
        "built_at": datetime.now()
    }

@app.get("/api/kb/tags")
def get_kb_tags():
    """キャッシュからタグ情報を返す"""
    return {"total_tags": 376, "total_pages": 411, "tags": KB_CACHE["tags"]}

@app.get("/api/kb/sidebar")
def get_kb_sidebar():
    """KB ツリービュー用サイドバー構造"""
    return KB_CACHE["sidebar"]
```

### Step 3: HTML に KB UI を統合

メイン HTML テンプレートに以下を追加：

```html
<div id="kb-panel" style="display: none; border: 1px solid #ccc;">
    <div id="kb-title"></div>
    <div id="kb-content"></div>
</div>

<script>
async function showKbFile(path) {
    const res = await fetch(`/api/kb/${path}`);
    const data = await res.json();
    // Markdown をレンダリング
    document.getElementById('kb-content').innerHTML = marked(data.body);
}

async function searchKb(query) {
    const res = await fetch(`/api/kb-search?q=${encodeURIComponent(query)}`);
    const results = await res.json();
    // 結果を表示
}
</script>
```

### Step 4: ルート定義順序に注意

**重要**: FastAPI では以下の順序で定義する：

```python
# ✅ 順序が正しい
@app.get("/api/kb/tags")  # 具体的なルート → 先
def get_tags(): ...

@app.get("/api/kb/sidebar")  # 具体的なルート → 先
def get_sidebar(): ...

@app.get("/api/kb/{path:path}")  # 汎用ルート → 後
def get_kb(path: str): ...
```

**逆順だと汎用パターンが全てをキャッチしてしまい、/api/kb/tags は {path:path} に吸収される。**

## Caveats

- **複数 HTML テンプレート**: news_app.py に TIPS_HTML, INTERESTS_HTML など複数テンプレートがある場合、メインの index のみに KB パネルを追加するべき（全テンプレートへの展開はスコープ拡大）
- **_KB_ROOT 未定義**: コード中に `_KB_ROOT` 変数参照があるが、実際の KB 関数は `_get_knowledge_dir()` を使用。技術的負債として残存している が動作に影響なし
- **Mac mini HTTP アクセス**: laptop からは `http://mini.local:8083` への HTTP が無応答（SSH は可能）。ファイアウォール設定の可能性。ブラウザテストは mini ローカルか SSH トンネル経由で実施

## Related Concepts

- [[wiki/fastapi-route-ordering|FastAPI ルート定義順序]]
- [[wiki/uvicorn-reload-launchd|uvicorn --reload と launchd]]
- [[wiki/locus-architecture|Locus アーキテクチャ再検討]]

## Sources

- [[logs/daily/2026-05-03.md]] — Phase 1-3 実装と Mac mini への本番反映
- commit 222d91e: news_app.py KB 統合実装（805行追加）
- commit 894eea0: knowledge/ wiki ドラフト 7 件追加
