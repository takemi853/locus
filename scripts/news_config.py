"""
ニュース収集の設定ファイル。ここを編集して自分好みにカスタマイズする。

セットアップ:
    1. https://socialdata.tools でアカウント作成、API キーを取得
    2. ~/.zshrc に以下を追加:
           export SOCIAL_DATA_API_KEY="your_key_here"
    3. このファイルの KEYWORDS / X_ACCOUNTS を自分の興味に合わせて編集
"""

from __future__ import annotations

import os

# ── Social Data API ────────────────────────────────────────────────────
SOCIAL_DATA_API_KEY = os.environ.get("SOCIAL_DATA_API_KEY", "")

# ── 検索キーワード（英語）──
# 内部で OR 連結されて1クエリにまとめられる。スパム除外: -giveaway -"free course"
# ユーザー文脈: 推薦システム本業 + AI / Claude Code / Personal OS / 情報設計
KEYWORDS: list[str] = [
    "Anthropic Claude -giveaway -\"free course\" -\"paid courses\"",
    "Claude Code -giveaway -\"free course\"",
    "LLM agent OR \"agentic workflow\" -giveaway -\"free course\"",
    "MCP server OR \"model context protocol\" -giveaway",
    "\"recommendation system\" LLM OR recsys LLM -giveaway",
    "\"personal knowledge\" AI OR \"second brain\" AI -giveaway -\"free course\"",
]

# ── 英語アカウント ──
# 内部で OR 連結されて1クエリにまとめられる（X_MAX_PER_QUERY=20 上限）
# 選定基準: 一次情報 / 高シグナル / スパム少。バズ系・営業系は除外
X_ACCOUNTS: list[str] = [
    # Anthropic / Claude Code 一次情報
    "AnthropicAI",
    "alexalbert__",
    # AI 研究・実装の論評（高シグナル）
    "karpathy",
    "simonw",          # LLM blog (Simon Willison)
    "swyx",            # Latent Space podcast
    "omarsar0",        # DAIR.AI ニュースレター
    "dwarkesh_sp",     # Dwarkesh Podcast
    "hardmaru",        # David Ha
    # 推薦・実装系
    "eugeneyan",       # eugeneyan blog（推薦/ML systems）
    "jxnl",            # Jason Liu (Instructor / DSPy)
    # Agent / framework 系
    "hwchase17",       # LangChain
    "_philschmid",     # HuggingFace 実装解説
]

# ── 日本語アカウント（lang フィルタなし、from: で取得）──
# 選定基準: AI / LLM / ML / 推薦 / Claude Code 関連で日本語の一次論評を出す人
X_ACCOUNTS_JA: list[str] = [
    "hillbig",         # Daisuke Okanohara (PFN)
    "npaka123",        # npaka — LLM tips/解説
    "karaage0703",     # karaage — ML / Maker
    "smly",            # Kaggler
    "shi3z",           # 清水亮
    "masuidrive",      # 増井雄一郎
    "mamoruk",         # 持橋大地（自然言語処理）
]

# ── 日本語キーワード（各キーワードが1クエリ。lang:ja は自動付与）──
# 数を増やすとクエリ数も増える（コスト増）。3-5 件に絞る
KEYWORDS_JA: list[str] = [
    "Claude Code",
    "LLMエージェント",
    "推薦システム LLM",
]

# ── 閾値 ──
# RT/Likes 高い = 高シグナルだが新着発見が減る。Account 指定は閾値で絞られにくい
X_MIN_RETWEETS: int = 50    # 英語キーワード/英語アカウント共通
X_MIN_LIKES: int = 200      # 〃 (0 = 無効)

# JA accounts は英語より RT/Likes が出にくいので閾値別建て（collect_news.py 引数）
X_MIN_RETWEETS_JA: int = 10
X_MIN_LIKES_JA: int = 100

# JA キーワード（より広く拾う想定の最低限フィルタ）
X_MIN_RETWEETS_KW_JA: int = 30
X_MIN_LIKES_KW_JA: int = 200

# 1クエリあたりの最大取得件数（OR 連結クエリ全体の件数上限）
X_MAX_PER_QUERY: int = 20

# 何時間以内のツイートのみ収集するか（古いツイート除外）
X_HOURS_BACK: int = 48

# 月の予算上限（USD）。0 = 無制限
# Social Data は $0.0002/tweet。
# 想定: 6 query × 20 tweets × 2 run/day × 30 day × $0.0002 = $1.44/month
X_MONTHLY_BUDGET_USD: float = 3.0

# ── Hacker News ────────────────────────────────────────────────────────
HN_MIN_POINTS: int = 100   # この点数以上のみ収集
HN_MAX_ITEMS: int = 15     # 1日の最大取得件数

# ── Reddit ─────────────────────────────────────────────────────────────
REDDIT_SUBREDDITS: list[str] = [
    "MachineLearning",
    "LocalLLaMA",
    "ClaudeAI",
    "artificial",
]
REDDIT_MIN_UPVOTES: int = 100   # この upvotes 以上のみ収集
REDDIT_MAX_PER_SUB: int = 5     # サブレディットごとの最大取得件数

# ── RSS フィード ────────────────────────────────────────────────────────
# Anthropic / OpenAI は RSS 非対応のため除外済み
RSS_FEEDS: list[tuple[str, str]] = [
    ("GitHub Blog",         "https://github.blog/feed/"),
    ("MIT Tech Review AI",  "https://www.technologyreview.com/feed/"),
    # ("VentureBeat AI",    "https://venturebeat.com/category/ai/feed/"),
]
RSS_MAX_PER_FEED: int = 5
