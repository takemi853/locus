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

# 検索キーワード（Twitter 検索演算子が使える: AND / OR / -除外 など）
# スパム除外: -giveaway -"free course" -"paid courses"
KEYWORDS: list[str] = [
    # AI / Tech（具体的なトピックを指定すると精度が上がる）
    "Anthropic Claude -giveaway -\"free course\" -\"paid courses\"",
    "LLM agent research -giveaway -\"free course\"",
    "Claude Code -giveaway -\"free course\"",
    # 追加したいキーワードをここに
]

# 特定アカウントのツイートを収集（スクリーンネームのみ、@ なし）
# アカウント指定は精度が高くスパムが入りにくい
X_ACCOUNTS: list[str] = [
    "AnthropicAI",
    "karpathy",
    # "sama",
    # "ylecun",
]

# RT 数フィルタ（これ未満の投稿はスキップ）
X_MIN_RETWEETS: int = 50

# いいね数フィルタ（0 = 無効）
X_MIN_LIKES: int = 200

# 1クエリあたりの最大取得件数（アカウント指定クエリの件数制限に使う）
X_MAX_PER_QUERY: int = 10

# 何時間以内のツイートのみ収集するか（古いツイート除外）
X_HOURS_BACK: int = 48

# 月の予算上限（USD）。0 = 無制限
# Social Data は $0.0002/tweet。1日50件 × 30日 ≒ $0.30/月
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
