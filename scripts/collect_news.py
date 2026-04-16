"""
毎朝のニュース収集スクリプト。
Social Data API (X), Hacker News, Reddit, RSS から情報を集め、
knowledge/news/YYYY-MM-DD.md に個人新聞として保存する。

Usage:
    uv run python collect_news.py              # 全ソースから収集
    uv run python collect_news.py --dry-run    # 保存せず stdout に出力
    uv run python collect_news.py --sources hn reddit  # ソース指定
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import NEWS_DIR, today_iso

STATE_FILE = Path(__file__).resolve().parent / "news-state.json"
COST_FILE  = Path(__file__).resolve().parent / "news-costs.json"
JST = timezone(timedelta(hours=9))
CUTOFF_HOURS = 24  # 何時間前までの記事を収集するか

# Social Data API の単価（$0.0002 / tweet）
SOCIAL_DATA_COST_PER_ITEM = 0.0002


class Item(NamedTuple):
    source: str   # "x" | "hn" | "reddit" | "rss"
    title: str
    url: str
    metric: str   # "RT:123", "342pts", "r/sub 1.2K↑", "Feed Name"
    author: str


# ── HTTP ──────────────────────────────────────────────────────────────

def _get(url: str, headers: dict[str, str] | None = None, timeout: int = 10) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": "locus-news/1.0", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        print(f"  [warn] GET {url[:70]}: {e}", file=sys.stderr)
        return None


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict | list | None:
    raw = _get(url, headers)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ── State（重複排除） ─────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"seen_urls": []}


def _save_state(state: dict) -> None:
    state["seen_urls"] = state["seen_urls"][-2000:]
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ── コスト管理 ────────────────────────────────────────────────────────

def _load_costs() -> dict:
    if COST_FILE.exists():
        try:
            return json.loads(COST_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"runs": [], "total_usd": 0.0}


def _save_costs(costs: dict) -> None:
    costs["runs"] = costs["runs"][-365:]  # 1年分まで保持
    COST_FILE.write_text(json.dumps(costs, ensure_ascii=False, indent=2), encoding="utf-8")


def _this_month_cost(costs: dict) -> float:
    """今月の累計コストを返す。"""
    ym = datetime.now(JST).strftime("%Y-%m")
    return sum(r["cost_usd"] for r in costs["runs"] if r["date"].startswith(ym))


def _record_cost(costs: dict, date: str, fetched: int) -> float:
    """取得件数からコストを計算して記録し、今回のコストを返す。"""
    cost = fetched * SOCIAL_DATA_COST_PER_ITEM
    costs["runs"].append({"date": date, "fetched": fetched, "cost_usd": round(cost, 6)})
    costs["total_usd"] = round(costs.get("total_usd", 0.0) + cost, 6)
    return cost


def _check_budget(costs: dict, monthly_budget: float) -> bool:
    """月予算を超えていたら True を返す（X 収集をスキップすべき）。"""
    if monthly_budget <= 0:
        return False
    spent = _this_month_cost(costs)
    if spent >= monthly_budget:
        print(f"  [budget] 今月の累計 ${spent:.4f} が上限 ${monthly_budget:.2f} に達しました。X 収集をスキップします。")
        return True
    return False


# ── Social Data (X) ───────────────────────────────────────────────────

def collect_x(
    api_key: str,
    keywords: list[str],
    accounts: list[str],
    min_rt: int,
    hours_back: int = 48,
    max_per_query: int = 20,
    min_likes: int = 0,
) -> list[Item]:
    if not api_key:
        print("  [skip] SOCIAL_DATA_API_KEY が未設定です", file=sys.stderr)
        return []

    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    items: list[Item] = []
    seen_ids: set[str] = set()
    raw_fetched = 0  # API から返された全ツイート数（課金対象）

    # since_time: Unix タイムスタンプ（hours_back 時間前）
    since_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp())

    queries: list[str] = [
        f"{kw} min_retweets:{min_rt} -is:retweet lang:en"
        for kw in keywords
    ] + [
        f"from:{acc} min_retweets:{min_rt} -is:retweet"
        for acc in accounts
    ]

    for query in queries:
        url = "https://api.socialdata.tools/twitter/search?" + urllib.parse.urlencode(
            {"query": query, "type": "Top", "since_time": since_ts}
        )
        data = _get_json(url, headers=headers)
        if not isinstance(data, dict) or "tweets" not in data:
            continue

        raw_fetched += len(data["tweets"])
        query_count = 0
        for t in data["tweets"]:
            if query_count >= max_per_query:
                break
            tid = str(t.get("id_str", ""))
            if tid in seen_ids:
                continue
            seen_ids.add(tid)

            text: str = t.get("full_text") or t.get("text") or ""
            if text.startswith("RT @"):
                continue

            rt: int = t.get("retweet_count", 0)
            if rt < min_rt:
                continue

            likes: int = t.get("favorite_count", 0)
            if min_likes > 0 and likes < min_likes:
                continue

            # 時間フィルタ（created_at で確認）
            created_at: str = t.get("tweet_created_at") or t.get("created_at") or ""
            if created_at:
                try:
                    from email.utils import parsedate_to_datetime
                    tweet_ts = parsedate_to_datetime(created_at).timestamp()
                    if tweet_ts < since_ts:
                        continue
                except Exception:
                    pass

            author: str = t.get("user", {}).get("screen_name", "")
            # 記事URLがあればそちらを使い、なければポストURLにフォールバック
            urls = t.get("entities", {}).get("urls", [])
            article_url = urls[-1].get("expanded_url", "") if urls else ""
            if not article_url or "t.co" in article_url:
                article_url = f"https://x.com/{author}/status/{tid}"

            # ツイート本文からURLを除去してタイトルとして使う
            clean = re.sub(r"https?://\S+", "", text).strip()
            clean = (clean[:120] + "…") if len(clean) > 120 else clean

            items.append(Item(
                source="x",
                title=clean,
                url=article_url,
                metric=f"RT:{rt:,} ♥{likes:,}",
                author=f"@{author}",
            ))
            query_count += 1

        time.sleep(0.3)

    return items, raw_fetched


# ── Hacker News ───────────────────────────────────────────────────────

def collect_hn(min_points: int, max_items: int) -> list[Item]:
    story_ids = _get_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    if not isinstance(story_ids, list):
        return []

    cutoff = datetime.now(timezone.utc).timestamp() - CUTOFF_HOURS * 3600
    items: list[Item] = []

    for sid in story_ids[:150]:
        if len(items) >= max_items:
            break
        data = _get_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
        if not isinstance(data, dict):
            continue
        score: int = data.get("score", 0)
        ts: int = data.get("time", 0)
        if score < min_points or ts < cutoff:
            continue
        url: str = data.get("url") or f"https://news.ycombinator.com/item?id={sid}"
        title: str = data.get("title", "")
        author: str = data.get("by", "")
        items.append(Item(source="hn", title=title, url=url, metric=f"{score:,}pts", author=author))

    return items


# ── Reddit ─────────────────────────────────────────────────────────────

def collect_reddit(subreddits: list[str], min_upvotes: int, max_per_sub: int) -> list[Item]:
    items: list[Item] = []
    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=25"
        data = _get_json(url)
        if not isinstance(data, dict):
            time.sleep(1.0)
            continue

        count = 0
        for child in data.get("data", {}).get("children", []):
            if count >= max_per_sub:
                break
            d = child.get("data", {})
            score: int = d.get("score", 0)
            if score < min_upvotes:
                continue
            title: str = d.get("title", "")
            link: str = d.get("url", "")
            if not link or link.startswith("/r/"):
                link = "https://reddit.com" + d.get("permalink", "")
            # スコアを K 表記に変換
            metric_str = f"{score/1000:.1f}K↑" if score >= 1000 else f"{score}↑"
            items.append(Item(
                source="reddit",
                title=title,
                url=link,
                metric=f"r/{sub} {metric_str}",
                author=d.get("author", ""),
            ))
            count += 1

        time.sleep(0.8)

    return items


# ── RSS ───────────────────────────────────────────────────────────────

def collect_rss(feeds: list[tuple[str, str]], max_per_feed: int) -> list[Item]:
    items: list[Item] = []
    for feed_name, feed_url in feeds:
        raw = _get(feed_url)
        if raw is None:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue

        count = 0
        # RSS 2.0
        for item in root.findall(".//item"):
            if count >= max_per_feed:
                break
            title_el = item.find("title")
            link_el = item.find("link")
            if title_el is None or not (title_el.text or "").strip():
                continue
            link = (link_el.text or "").strip() if link_el is not None else ""
            items.append(Item(
                source="rss",
                title=title_el.text.strip(),
                url=link,
                metric=feed_name,
                author="",
            ))
            count += 1
        if count:
            continue

        # Atom
        ATOM = "http://www.w3.org/2005/Atom"
        for entry in root.findall(f".//{{{ATOM}}}entry"):
            if count >= max_per_feed:
                break
            title_el = entry.find(f"{{{ATOM}}}title")
            link_el = entry.find(f"{{{ATOM}}}link")
            if title_el is None:
                continue
            items.append(Item(
                source="rss",
                title=(title_el.text or "").strip(),
                url=link_el.get("href", "") if link_el is not None else "",
                metric=feed_name,
                author="",
            ))
            count += 1

    return items


# ── Markdown 生成 ─────────────────────────────────────────────────────

def _render(
    date: str,
    x_items: list[Item],
    hn_items: list[Item],
    reddit_items: list[Item],
    rss_items: list[Item],
    run_cost_usd: float = 0.0,
    month_cost_usd: float = 0.0,
) -> str:
    now_str = datetime.now(JST).strftime("%H:%M JST")
    total = len(x_items) + len(hn_items) + len(reddit_items) + len(rss_items)
    cost_str = f" | 今回 ${run_cost_usd:.4f} / 今月 ${month_cost_usd:.4f}" if run_cost_usd else ""

    lines = [
        "---",
        f'title: "Daily Brief — {date}"',
        "tags: [news, daily-brief]",
        f"created: {date}",
        f'updated: "{date}"',
        "---",
        "",
        f"# 📰 Daily Brief — {date}",
        "",
        f"> 収集: {now_str} | {total} 件{cost_str}",
        "",
    ]

    def _section(title: str, items: list[Item], fmt: str) -> None:
        if not items:
            return
        lines.append(f"## {title}")
        lines.append("")
        for it in items:
            if fmt == "x":
                lines.append(f"- **{it.author}** `{it.metric}`  {it.title}")
                lines.append(f"  <{it.url}>")
            elif fmt == "link":
                lines.append(f"- [{it.title}]({it.url})  `{it.metric}`")
            elif fmt == "rss":
                lines.append(f"- [{it.title}]({it.url})  — {it.metric}")
        lines.append("")

    _section("📡 公式ブログ・リリース", rss_items, "rss")
    _section("🔥 Hacker News", hn_items, "link")
    _section("💬 Reddit", reddit_items, "link")
    _section("🐦 X ハイライト", x_items, "x")

    if not total:
        lines.append("> 今日は収集できる記事がありませんでした。")

    return "\n".join(lines) + "\n"


# ── メイン ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="毎朝のニュース収集")
    parser.add_argument("--dry-run", action="store_true", help="保存せず stdout に出力")
    parser.add_argument(
        "--sources", nargs="+", choices=["x", "hn", "reddit", "rss"],
        help="収集するソースを指定（デフォルト: 全部）",
    )
    args = parser.parse_args()
    sources = set(args.sources) if args.sources else {"x", "hn", "reddit", "rss"}

    try:
        import news_config as cfg
    except ImportError:
        print("Error: scripts/news_config.py が見つかりません", file=sys.stderr)
        sys.exit(1)

    state = _load_state()
    costs = _load_costs()
    seen: set[str] = set(state.get("seen_urls", []))
    monthly_budget = getattr(cfg, "X_MONTHLY_BUDGET_USD", 0.0)

    def _dedup(items: list[Item]) -> list[Item]:
        result = []
        for it in items:
            if it.url and it.url not in seen:
                result.append(it)
        return result

    print("ニュース収集を開始...")

    x_items: list[Item] = []
    hn_items: list[Item] = []
    reddit_items: list[Item] = []
    rss_items: list[Item] = []
    run_cost = 0.0

    if "x" in sources:
        if _check_budget(costs, monthly_budget):
            pass  # 予算超過でスキップ
        else:
            print("  X (Social Data)...")
            raw_x, raw_fetched = collect_x(
                cfg.SOCIAL_DATA_API_KEY, cfg.KEYWORDS, cfg.X_ACCOUNTS,
                cfg.X_MIN_RETWEETS,
                getattr(cfg, "X_HOURS_BACK", 48),
                getattr(cfg, "X_MAX_PER_QUERY", 20),
                getattr(cfg, "X_MIN_LIKES", 0),
            )
            x_items = _dedup(raw_x)
            run_cost = _record_cost(costs, today_iso(), raw_fetched)
            month_cost = _this_month_cost(costs)
            print(f"  → {len(x_items)} 件  (取得 {raw_fetched} tweets / 今回 ${run_cost:.4f} / 今月 ${month_cost:.4f})")

    if "hn" in sources:
        print("  Hacker News...")
        hn_items = _dedup(collect_hn(cfg.HN_MIN_POINTS, cfg.HN_MAX_ITEMS))
        print(f"  → {len(hn_items)} 件")

    if "reddit" in sources:
        print("  Reddit...")
        reddit_items = _dedup(collect_reddit(
            cfg.REDDIT_SUBREDDITS, cfg.REDDIT_MIN_UPVOTES, cfg.REDDIT_MAX_PER_SUB,
        ))
        print(f"  → {len(reddit_items)} 件")

    if "rss" in sources:
        print("  RSS...")
        rss_items = _dedup(collect_rss(cfg.RSS_FEEDS, cfg.RSS_MAX_PER_FEED))
        print(f"  → {len(rss_items)} 件")

    date = today_iso()
    month_cost = _this_month_cost(costs)
    content = _render(date, x_items, hn_items, reddit_items, rss_items, run_cost, month_cost)

    if args.dry_run:
        print("\n" + content)
        return

    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = NEWS_DIR / f"{date}.md"
    out_path.write_text(content, encoding="utf-8")

    # seen に追記（重複排除用）
    all_items: list[Item] = x_items + hn_items + reddit_items + rss_items
    state["seen_urls"] = state.get("seen_urls", []) + [it.url for it in all_items if it.url]
    _save_state(state)
    _save_costs(costs)

    total = len(all_items)
    print(f"\n保存: {out_path}")
    print(f"合計: {total} 件 | 今月累計コスト: ${month_cost:.4f}")


if __name__ == "__main__":
    main()
