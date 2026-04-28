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

# news_app.py の常駐ポート（ensure-running.sh と合わせる）
NEWS_APP_URL = "http://localhost:8083"


class Item(NamedTuple):
    source: str        # "x" | "hn" | "reddit" | "rss"
    title: str
    url: str
    metric: str        # "342pts", "r/sub 1.2K↑", "Feed Name"（HN/Reddit/RSS 用）
    author: str
    image_url: str = ""       # ツイート添付画像 URL（あれば）
    title_ja: str = ""        # 日本語訳（X のみ）
    query_label: str = ""     # "en_kw" | "en_acc" | "ja_acc" | "ja_kw"
    likes: int = 0            # X のいいね数
    retweets: int = 0         # X の RT 数
    replies: int = 0          # X のリプライ数（X アルゴリズムで最高重み）
    views: int = 0            # X のインプレッション数
    created_at: str = ""     # ISO 8601 UTC（例: "2026-04-17T08:30:00Z"）


# ── HTTP ──────────────────────────────────────────────────────────────

def _get(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes | None:
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


def _save_state(state: dict, hours_back: int = 48) -> None:
    """seen_urls を {url, ts} 形式で保存し、hours_back より古いエントリを削除。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()
    entries = state.get("seen_urls", [])
    # 旧形式（文字列のみ）を新形式に変換しつつ、期限切れを除去
    now_ts = datetime.now(timezone.utc).isoformat()
    normalized = []
    for e in entries:
        if isinstance(e, str):
            normalized.append({"url": e, "ts": now_ts})
        elif isinstance(e, dict) and e.get("ts", "") >= cutoff:
            normalized.append(e)
    state["seen_urls"] = normalized[-2000:]
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


# ── 翻訳 ─────────────────────────────────────────────────────────────

# ── X 検索クエリに埋め込む否定 phrase ─────────────────────────────────
# Twitter 検索構文 `-"phrase"` で、API 返却前に literal 一致するプロモ tweet を
# 弾く。クライアント側の _is_promo_spam で再フィルタするより早く、API 課金も削減。
# 正規表現 (\d+倍 / \d+万円稼) 系は Twitter 検索が非対応のため _PROMO_PATTERNS に残す。
_X_NEGATIVE_PHRASES = [
    # 【】テンプレ
    "【保存版】", "【完全版】", "【保存推奨】", "【保存必須】",
    "【超有料級】", "【限定公開】", "【無料公開】", "【永久保存】",
    "【神AI】", "【神プロンプト】", "【神ツール】", "【神アプリ】",
    # 「○○で配布」型
    "リプで配布", "DMで配布", "コメントで配布",
    # 商業ハイプ語
    "無料配布", "無料プレゼント", "無料公開中",
    "神プロンプト集", "神ツール集",
]
_X_NEGATIVE_QUERY_FRAGMENT = " " + " ".join(f'-"{p}"' for p in _X_NEGATIVE_PHRASES)


# ── プロモ / スパム検出 ────────────────────────────────────────────────
# X 検索で混入しがちな自己プロモ / 商業煽り tweet を弾くためのパターン集。
# 過剰検出を避けるため、固有テンプレ語や強い煽り語のみに絞る。
_PROMO_PATTERNS = [
    # 「【保存版】」「【完全版】」「【神AI】」「【保存推奨】」等のテンプレ
    r"【\s*(保存版|完全版|超有料級|保存推奨|保存必須|神AI|神プロンプト|神ツール|神アプリ|限定公開|無料公開|永久保存)\s*】",
    # 「リプで配布」「DMで」「コメントで」「いいねした方に」型
    r"(リプ|DM|コメント)で(配布|送り|プレゼント|お渡し)",
    r"いいね(した|くれた)(方|人)に",
    # 「無料配布」「無料プレゼント」「無料公開」型 — 商業ハイプ語
    r"無料(配布|プレゼント|公開中)",
    # 「神プロンプト」「神ツール」「神AI」が括弧無しで本文に
    r"神(プロンプト|ツール|アプリ|AI)(集|公開)",
    # 「X倍に」「X日でX万円」型の煽り (3倍以上)
    r"\d{2,}倍に",
    r"\d+万円(稼|もらえ|貰え|稼げ)",
    # 「フォロワー」「フォロー」だけで配布タイプ
    r"フォロー(してくれた|していただいた).{0,20}(配布|送)",
]
_PROMO_RE = re.compile("|".join(_PROMO_PATTERNS))


def _is_promo_spam(text: str) -> bool:
    """X 検索で拾った tweet 本文が自己プロモ / 商業煽り型なら True。"""
    return bool(_PROMO_RE.search(text))


def _translate_ja(text: str) -> str:
    """Google Translate 非公式 API で英語→日本語に翻訳する（キー不要）。"""
    if not text:
        return ""
    url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode({
        "client": "gtx", "sl": "en", "tl": "ja", "dt": "t", "q": text,
    })
    data = _get_json(url)
    if not isinstance(data, list) or not data[0]:
        print(f"  [warn] 翻訳失敗: {text[:40]!r}", file=sys.stderr)
        return ""
    try:
        return "".join(part[0] for part in data[0] if part and part[0])
    except Exception as e:
        print(f"  [warn] 翻訳パースエラー: {e}", file=sys.stderr)
        return ""


# ── Social Data (X) ───────────────────────────────────────────────────

def collect_x(
    api_key: str,
    keywords: list[str],
    accounts: list[str],
    min_rt: int,
    hours_back: int = 48,
    max_per_query: int = 20,
    min_likes: int = 0,
    translate: bool = True,
    accounts_ja: list[str] | None = None,
    min_rt_ja: int = 10,
    min_likes_ja: int = 100,
    keywords_ja: list[str] | None = None,
    min_rt_kw_ja: int = 30,
    min_likes_kw_ja: int = 200,
    keywords_ja_v2: list[str] | None = None,
) -> list[Item]:
    if not api_key:
        print("  [skip] SOCIAL_DATA_API_KEY が未設定です", file=sys.stderr)
        return [], 0

    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    items: list[Item] = []
    seen_ids: set[str] = set()
    raw_fetched = 0  # 実際に処理したツイート数（課金対象）

    # since_time: Unix タイムスタンプ（hours_back 時間前）
    since_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp())
    # `since:YYYY-MM-DD` クエリ演算子用の日付（Top 検索だと since_time URL param が
    # 無視されるケースがあるため、クエリ文字列側にも日付フィルタを埋める）
    since_date = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime("%Y-%m-%d")

    def _build_filter(rt: int, lk: int, lang: str = "", since_d: str = "") -> str:
        lk_op = f" min_faves:{lk}" if lk > 0 else ""
        lang_op = f" lang:{lang}" if lang else ""
        since_op = f" since:{since_d}" if since_d else ""
        # 否定 phrase は API 返却前に弾く（API 課金削減）
        return f"min_retweets:{rt}{lk_op} -is:retweet{lang_op}{since_op}{_X_NEGATIVE_QUERY_FRAGMENT}"

    # (クエリ文字列, client側RT閾値, client側likes閾値, ラベル) のリスト
    # サーバー側にも同じ閾値を埋め込むことで返却件数を削減
    query_specs: list[tuple[str, int, int, str]] = []

    # キーワード: 複数を OR でまとめて1クエリ（英語のみ）
    # キーワードは "正の語句 [-否定...]" の形式を想定
    if keywords:
        positives: list[str] = []
        negatives: set[str] = set()
        for kw in keywords:
            parts = kw.split(" -", 1)
            pos = parts[0].strip()
            positives.append(f'"{pos}"' if " " in pos else pos)
            if len(parts) > 1:
                for neg in re.findall(r'-(?:"[^"]*"|\S+)', "-" + parts[1]):
                    negatives.add(neg)
        neg_str = (" " + " ".join(sorted(negatives))) if negatives else ""
        kw_base = f"({' OR '.join(positives)})" if len(positives) > 1 else positives[0]
        kw_query = f"{kw_base}{neg_str} {_build_filter(min_rt, min_likes, lang='en', since_d=since_date)}"
        query_specs.append((kw_query, min_rt, min_likes, "en_kw"))

    # 英語アカウント
    if accounts:
        acc_or = " OR ".join(f"from:{acc}" for acc in accounts)
        query_specs.append((
            f"({acc_or}) {_build_filter(min_rt, min_likes, since_d=since_date)}",
            min_rt, min_likes, "en_acc",
        ))

    # 日本語アカウント（閾値を別に設定）
    if accounts_ja:
        acc_ja_or = " OR ".join(f"from:{acc}" for acc in accounts_ja)
        query_specs.append((
            f"({acc_ja_or}) {_build_filter(min_rt_ja, min_likes_ja, since_d=since_date)}",
            min_rt_ja, min_likes_ja, "ja_acc",
        ))

    # 日本語キーワード v1（フォロー外アカウントのバズ発見用・lang:ja 固定）
    if keywords_ja:
        for kw_ja in keywords_ja:
            q = f"{kw_ja} {_build_filter(min_rt_kw_ja, min_likes_kw_ja, lang='ja', since_d=since_date)}"
            query_specs.append((q, min_rt_kw_ja, min_likes_kw_ja, "ja_kw"))

    # 日本語キーワード v2（改善クエリ・A/B テスト用）
    if keywords_ja_v2:
        for kw_ja in keywords_ja_v2:
            q = f"{kw_ja} {_build_filter(min_rt_kw_ja, min_likes_kw_ja, lang='ja', since_d=since_date)}"
            query_specs.append((q, min_rt_kw_ja, min_likes_kw_ja, "ja_kw_v2"))

    for query, q_min_rt, q_min_likes, qlabel in query_specs:
        url = "https://api.socialdata.tools/twitter/search?" + urllib.parse.urlencode(
            {"query": query, "type": "Top", "since_time": since_ts}
        )
        data = _get_json(url, headers=headers)
        if not isinstance(data, dict) or "tweets" not in data:
            continue

        raw_fetched += len(data["tweets"])
        query_count = 0
        for t in data["tweets"]:
            if max_per_query > 0 and query_count >= max_per_query:
                break
            tid = str(t.get("id_str", ""))
            if tid in seen_ids:
                continue
            seen_ids.add(tid)

            text: str = t.get("full_text") or t.get("text") or ""
            if text.startswith("RT @"):
                continue

            rt: int = t.get("retweet_count", 0)
            if rt < q_min_rt:
                continue

            likes: int = t.get("favorite_count", 0)
            if q_min_likes > 0 and likes < q_min_likes:
                continue

            replies: int = t.get("reply_count", 0)
            views: int = t.get("views_count", 0)

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

            # URL は除去（記事 URL は別途扱う）が、改行と全文は保持。
            # 表示側 (news_app の white-space: pre-wrap / _render_x_item の truncate) で扱う
            clean = re.sub(r"https?://\S+", "", text).strip()
            if not clean:
                continue  # URL のみのツイートはスキップ
            if _is_promo_spam(clean):
                continue  # 自己プロモ / 商業煽り tweet は除外

            # 添付メディア（photo / video / animated_gif の thumbnail を画像として扱う）
            # extended_entities が空なら entities を fallback
            media_list = (
                t.get("extended_entities", {}).get("media", [])
                or t.get("entities", {}).get("media", [])
            )
            image_url = ""
            if media_list and media_list[0].get("type") in ("photo", "video", "animated_gif"):
                image_url = media_list[0].get("media_url_https", "")

            # 日本語訳（日本語アカウントのツイートは翻訳不要）
            lang = t.get("lang", "")
            need_translate = translate and clean and lang != "ja"
            title_ja = _translate_ja(clean) if need_translate else ""

            # created_at を ISO UTC 文字列に正規化
            created_at_iso = ""
            if created_at:
                try:
                    from email.utils import parsedate_to_datetime
                    created_at_iso = parsedate_to_datetime(created_at).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    created_at_iso = created_at
            items.append(Item(
                source="x",
                title=clean,
                url=article_url,
                metric="",
                author=f"@{author}",
                image_url=image_url,
                title_ja=title_ja,
                query_label=qlabel,
                likes=likes,
                retweets=rt,
                replies=replies,
                views=views,
                created_at=created_at_iso,
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
        hn_dt = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else ""
        items.append(Item(source="hn", title=title, url=url, metric=f"{score:,}pts", author=author, created_at=hn_dt))

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
            reddit_ts = d.get("created_utc", 0)
            reddit_dt = datetime.utcfromtimestamp(reddit_ts).strftime("%Y-%m-%dT%H:%M:%SZ") if reddit_ts else ""
            items.append(Item(
                source="reddit",
                title=title,
                url=link,
                metric=f"r/{sub} {metric_str}",
                author=d.get("author", ""),
                created_at=reddit_dt,
            ))
            count += 1

        time.sleep(0.8)

    return items


# ── RSS ───────────────────────────────────────────────────────────────

def collect_rss(feeds: list[tuple[str, str]], max_per_feed: int, hours_back: int = CUTOFF_HOURS) -> list[Item]:
    """RSS / Atom フィードから記事を収集。
    hours_back より古い記事は skip（フィードに古い記事が居座り続ける問題対策）。
    pubDate / published / updated が解析できない記事は安全側に倒して採用する。"""
    from email.utils import parsedate_to_datetime
    cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    def _within_cutoff(rfc_or_iso: str) -> bool:
        """文字列を datetime に解析して cutoff 以降かを判定。失敗したら True (採用)。"""
        if not rfc_or_iso:
            return True
        try:
            # ISO 8601 (Atom) か RFC 822 (RSS) かを試す
            try:
                dt = datetime.fromisoformat(rfc_or_iso.replace("Z", "+00:00"))
            except ValueError:
                dt = parsedate_to_datetime(rfc_or_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt >= cutoff_dt
        except Exception:
            return True

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
        skipped_old = 0
        # RSS 2.0
        for item in root.findall(".//item"):
            if count >= max_per_feed:
                break
            title_el = item.find("title")
            link_el = item.find("link")
            if title_el is None or not (title_el.text or "").strip():
                continue
            link = (link_el.text or "").strip() if link_el is not None else ""
            pub_el = item.find("pubDate")
            rss_dt = ""
            if pub_el is not None and pub_el.text:
                try:
                    rss_dt = parsedate_to_datetime(pub_el.text).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    pass
            if not _within_cutoff(rss_dt):
                skipped_old += 1
                continue
            items.append(Item(
                source="rss",
                title=title_el.text.strip(),
                url=link,
                metric=feed_name,
                author="",
                created_at=rss_dt,
            ))
            count += 1
        if count or skipped_old:
            # RSS 2.0 でフィードがあった（採用 or skip）→ Atom 解析はスキップ
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
            pub_el = entry.find(f"{{{ATOM}}}published") or entry.find(f"{{{ATOM}}}updated")
            atom_dt = ""
            if pub_el is not None and pub_el.text:
                try:
                    atom_dt = pub_el.text.rstrip("Z").split("+")[0] + "Z"
                except Exception:
                    pass
            if not _within_cutoff(atom_dt):
                continue
            items.append(Item(
                source="rss",
                title=(title_el.text or "").strip(),
                url=link_el.get("href", "") if link_el is not None else "",
                metric=feed_name,
                author="",
                created_at=atom_dt,
            ))
            count += 1

    return items


# ── Markdown 生成 ─────────────────────────────────────────────────────

def _fmt_num(n: int) -> str:
    """数字を 62K / 1.2M のように短縮する。"""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K" if n % 1_000 == 0 else f"{n/1_000:.1f}K"
    return str(n)


def _dedup_by_account(items: list[Item], max_per: int = 2) -> list[Item]:
    """1アカウントあたり max_per 件に絞る（エンゲージメントスコア降順で先着）。"""
    def _score(it: Item) -> int:
        return it.replies * 15 + it.retweets * 3 + it.likes

    count: dict[str, int] = {}
    result: list[Item] = []
    for it in sorted(items, key=_score, reverse=True):
        if count.get(it.author, 0) < max_per:
            result.append(it)
            count[it.author] = count.get(it.author, 0) + 1
    return result


_X_SECTIONS: list[tuple[str, str, int]] = [
    ("en_acc", "🌐 Anthropic / Notable",      2),
    ("en_kw",  "🔍 英語 Tech キーワード",      2),
    ("ja_acc", "🇯🇵 日本語 AI コミュニティ",    2),
    ("ja_kw",  "🆕 日本語 新着発見",            2),
    ("ja_kw_v2", "🆕 日本語 新着発見 v2",       2),
]


def _render_x_item(it: Item) -> list[str]:
    """ツイート1件をコールアウトカード形式でレンダリング。
    Markdown のリンク本文は単一行であるべきなので、ここでだけ改行を / に縮める。
    元データ（news-latest.json の title）は news_app 表示用に改行保持済み。"""
    snippet_src = re.sub(r"\s*\n+\s*", " / ", it.title)
    snippet = snippet_src[:100] + ("…" if len(snippet_src) > 100 else "")
    parts = [f"♥{_fmt_num(it.likes)}", f"RT {_fmt_num(it.retweets)}"]
    if it.replies >= 100:
        parts.append(f"💬{_fmt_num(it.replies)}")
    metric = "  ".join(parts)
    rows = [
        f"> [!quote] {it.author} · {metric}",
        f"> [{snippet}]({it.url})",
    ]
    if it.title_ja:
        rows += [">", f"> *{it.title_ja}*"]
    if it.image_url:
        rows += [">", f"> ![]({it.image_url})"]
    return rows


def _render(
    date: str,
    x_items: list[Item],
    hn_items: list[Item],
    reddit_items: list[Item],
    rss_items: list[Item],
    run_cost_usd: float = 0.0,
    month_cost_usd: float = 0.0,
    digest: dict | None = None,
) -> str:
    now_str = datetime.now(JST).strftime("%H:%M JST")
    total = len(x_items) + len(hn_items) + len(reddit_items) + len(rss_items)
    cost_str = f" | 今回 ${run_cost_usd:.4f} / 今月 ${month_cost_usd:.4f}" if run_cost_usd else ""

    # タイトルはフロントマターから表示（本文に h1 を重複させない）
    lines = [
        "---",
        f'title: "📰 Daily Brief — {date}"',
        "tags: [news, daily-brief]",
        f"created: {date}",
        f'updated: "{date}"',
        "---",
        "",
        f"> 収集: {now_str} | {total} 件{cost_str}",
        "",
        f"> 📱 [ライブで読む]({NEWS_APP_URL}) ・ 📚 [[news/|news index]] ・ 🔧 [[wiki/personal-news-pipeline|pipeline]]",
        "",
    ]

    if digest:
        lines += _render_digest_block(digest)

    if rss_items:
        lines += ["## 📡 公式ブログ・リリース", ""]
        for it in rss_items:
            lines.append(f"- [{it.title}]({it.url})  — *{it.metric}*")
        lines.append("")

    if hn_items:
        lines += ["## 🔥 Hacker News", ""]
        for it in hn_items:
            lines.append(f"- [{it.title}]({it.url})  `{it.metric}`")
        lines.append("")

    if reddit_items:
        lines += ["## 💬 Reddit", ""]
        for it in reddit_items:
            lines.append(f"- [{it.title}]({it.url})  `{it.metric}`")
        lines.append("")

    has_x = False
    for label, section_title, max_per_acc in _X_SECTIONS:
        group = [it for it in x_items if it.query_label == label]
        if not group:
            continue
        group = _dedup_by_account(group, max_per=max_per_acc)[:10]
        if not group:
            continue
        if not has_x:
            lines += ["## 🐦 X ハイライト", ""]
            has_x = True
        lines += [f"### {section_title}", ""]
        for it in group:
            lines += _render_x_item(it)
            lines.append("")

    if not total:
        lines.append("> 今日は収集できる記事がありませんでした。")

    related = _related_kb_links(x_items + hn_items + reddit_items + rss_items)
    if related:
        lines += ["", "## 🔗 関連 KB", ""]
        lines += [f"- {link}" for link in related]

    return "\n".join(lines) + "\n"


def _load_digest_if_matches(date: str) -> dict | None:
    """scripts/news-digest.json を読み、date が一致すれば返す。"""
    path = Path(__file__).resolve().parent / "news-digest.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("date") != date:
        return None
    return data


def _render_digest_block(digest: dict) -> list[str]:
    """/news が生成した digest を Markdown に埋める。"""
    lines: list[str] = []
    headline = (digest.get("headline") or "").strip()
    summary  = (digest.get("executive_summary") or "").strip()
    insight  = (digest.get("insight") or "").strip()
    lead     = digest.get("lead") or {}
    quick    = digest.get("quick_hits") or []
    tools    = digest.get("new_tools") or []

    if headline:
        lines += [f"## ✨ {headline}", ""]
    if summary:
        lines += [summary, ""]
    if lead.get("url"):
        lines += [
            "### 🎯 Lead",
            "",
            f"**[{lead.get('what','').strip()}]({lead.get('url','')})**",
            "",
        ]
        why = (lead.get("why_it_matters") or "").strip()
        if why:
            lines += [f"> {why}", ""]
    if quick:
        lines += ["### ⚡ Quick Hits", ""]
        for q in quick:
            url = q.get("url", "")
            point = (q.get("point") or "").strip()
            if url and point:
                lines.append(f"- [{point}]({url})")
        lines.append("")
    if insight:
        lines += [f"> 💡 **Insight**: {insight}", ""]
    if tools:
        lines += ["### 🛠 New Tools", ""]
        for t in tools:
            name = t.get("name", "").strip()
            what = (t.get("what") or "").strip()
            rel  = t.get("relevance", "")
            rel_mark = {"high": "🔥", "medium": "⭐", "low": "·"}.get(rel, "")
            lines.append(f"- {rel_mark} **{name}** — {what}")
            reason = (t.get("relevance_reason") or "").strip()
            how    = (t.get("how_to_start") or "").strip()
            if reason:
                lines.append(f"  - なぜ: {reason}")
            if how:
                lines.append(f"  - 試す: {how}")
        lines.append("")
    return lines


# キーワード → KB ページ の静的マップ。
# 記事タイトルやXツイート本文にキーワードが含まれていれば対応ページを関連として出す。
_KB_LINK_MAP: list[tuple[tuple[str, ...], str]] = [
    (("claude code", "claude cli"),
     "[[projects/claude-code/index|Claude Code プロジェクト]]"),
    (("claude opus", "claude sonnet", "claude haiku", "anthropic"),
     "[[wiki/claude-agent-sdk|Claude / Anthropic 関連 wiki]]"),
    (("mcp", "model context protocol"),
     "[[wiki/claude-code-hooks|Claude Code hooks / MCP]]"),
    (("locus", "claude-memory-compiler", "compile.py"),
     "[[projects/locus/index|Locus]]"),
    (("世界遺産", "unesco", "world heritage"),
     "[[learning/world-heritage/|世界遺産検定1級]]"),
]


def _related_kb_links(items: list[Item]) -> list[str]:
    """記事タイトル・ツイート本文から KB ページ候補を抽出する（重複排除）。"""
    haystack = " ".join(
        (it.title or "") + " " + (it.title_ja or "")
        for it in items
    ).lower()
    seen: set[str] = set()
    out: list[str] = []
    for keywords, link in _KB_LINK_MAP:
        if link in seen:
            continue
        if any(kw in haystack for kw in keywords):
            seen.add(link)
            out.append(link)
    return out


# ── メイン ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="毎朝のニュース収集")
    parser.add_argument("--dry-run", action="store_true", help="保存せず stdout に出力")
    parser.add_argument("--force", action="store_true", help="コスト上限を無視して実行")
    parser.add_argument("--render-only", action="store_true", help="news-latest.json から MD のみ再生成（収集スキップ）")
    parser.add_argument("--no-dedup", action="store_true",
        help="seen_urls の重複判定を無効化（手動テスト実行用、launchd の定時実行では使わない）")
    parser.add_argument(
        "--sources", nargs="+", choices=["x", "hn", "reddit", "rss"],
        help="収集するソースを指定（デフォルト: 全部）",
    )
    args = parser.parse_args()
    sources = set(args.sources) if args.sources else {"x", "hn", "reddit", "rss"}

    # --render-only: JSON から MD だけ再生成して終了
    if args.render_only:
        try:
            import news_config as cfg
        except ImportError:
            print("Error: scripts/news_config.py が見つかりません", file=sys.stderr)
            sys.exit(1)
        latest_file = Path(__file__).resolve().parent / "news-latest.json"
        if not latest_file.exists():
            print("Error: news-latest.json が見つかりません", file=sys.stderr)
            sys.exit(1)
        data = json.loads(latest_file.read_text(encoding="utf-8"))
        date = data.get("date", today_iso())
        all_items = [Item(**{k: v for k, v in it.items() if k in Item._fields}) for it in data["items"]]
        x_items     = [it for it in all_items if it.source == "x"]
        hn_items    = [it for it in all_items if it.source == "hn"]
        reddit_items= [it for it in all_items if it.source == "reddit"]
        rss_items   = [it for it in all_items if it.source == "rss"]
        digest = _load_digest_if_matches(date)
        content = _render(date, x_items, hn_items, reddit_items, rss_items, digest=digest)
        NEWS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = NEWS_DIR / f"{date}.md"
        out_path.write_text(content, encoding="utf-8")
        print(f"再生成: {out_path} ({len(all_items)} 件)")
        return

    try:
        import news_config as cfg
    except ImportError:
        print("Error: scripts/news_config.py が見つかりません", file=sys.stderr)
        sys.exit(1)

    state = _load_state()
    costs = _load_costs()
    seen: set[str] = set() if args.no_dedup else {
        e["url"] if isinstance(e, dict) else e
        for e in state.get("seen_urls", [])
    }
    if args.no_dedup:
        print("  [no-dedup] seen_urls 重複判定を無効化（手動テスト実行用）")
    monthly_budget = getattr(cfg, "X_MONTHLY_BUDGET_USD", 0.0)

    def _dedup(items: list[Item]) -> list[Item]:
        if args.no_dedup:
            return list(items)
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

    if "x" in sources and not _check_budget(costs, monthly_budget):
        # 1回実行コストの上限チェック（--force で無視可）
        # クエリはキーワード・英語アカウント・日本語アカウントを各1本に統合済み
        max_run_cost = getattr(cfg, "X_MAX_COST_PER_RUN_USD", 0.0)
        if max_run_cost > 0:
            # merged query 数: kw(1) + en_acc(1) + ja_acc(1) + ja_kw(N) + ja_kw_v2(M)
            n_queries = 3 + len(getattr(cfg, "KEYWORDS_JA", [])) + len(getattr(cfg, "KEYWORDS_JA_V2", []))
            tweets_per_query = 20  # Social Data API の実績値
            estimated = n_queries * tweets_per_query * SOCIAL_DATA_COST_PER_ITEM
            if estimated > max_run_cost and not args.force:
                print(f"  [abort] 推定コスト ${estimated:.4f} が上限 ${max_run_cost:.4f} を超えます。")
                print(f"          実行するには --force を付けてください。")
                sys.exit(1)
        print("  X (Social Data)...")
        raw_x, raw_fetched = collect_x(
            cfg.SOCIAL_DATA_API_KEY, cfg.KEYWORDS, cfg.X_ACCOUNTS,
            cfg.X_MIN_RETWEETS,
            getattr(cfg, "X_HOURS_BACK", 48),
            getattr(cfg, "X_MAX_PER_QUERY", 20),
            getattr(cfg, "X_MIN_LIKES", 0),
            translate=getattr(cfg, "X_TRANSLATE", True),
            accounts_ja=getattr(cfg, "X_ACCOUNTS_JA", []),
            min_rt_ja=getattr(cfg, "X_MIN_RETWEETS_JA", 10),
            min_likes_ja=getattr(cfg, "X_MIN_LIKES_JA", 100),
            keywords_ja=getattr(cfg, "KEYWORDS_JA", []),
            min_rt_kw_ja=getattr(cfg, "X_MIN_RETWEETS_KW_JA", 50),
            min_likes_kw_ja=getattr(cfg, "X_MIN_LIKES_KW_JA", 500),
            keywords_ja_v2=getattr(cfg, "KEYWORDS_JA_V2", []),
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
    digest = _load_digest_if_matches(date)
    content = _render(date, x_items, hn_items, reddit_items, rss_items, run_cost, month_cost, digest=digest)

    if args.dry_run:
        print("\n" + content)
        return

    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = NEWS_DIR / f"{date}.md"
    out_path.write_text(content, encoding="utf-8")

    # seen に追記（重複排除用）。--no-dedup 実行は state に残さない（次回の通常実行を汚染しない）
    all_items: list[Item] = x_items + hn_items + reddit_items + rss_items
    if not args.no_dedup:
        now_ts = datetime.now(timezone.utc).isoformat()
        state["seen_urls"] = state.get("seen_urls", []) + [
            {"url": it.url, "ts": now_ts} for it in all_items if it.url
        ]
        hours_back = getattr(cfg, "X_HOURS_BACK", 24)
        _save_state(state, hours_back=hours_back * 2)  # 収集窓の2倍を保持
    _save_costs(costs)

    # 最新アイテムを JSON で保存（latest + 日時アーカイブ）
    jst_now  = datetime.now(JST)
    hhmm     = jst_now.strftime("%H%M")   # 例: "0800" / "1730"
    archive_key = f"{date}-{hhmm}"        # 例: "2026-04-17-0800"
    payload = json.dumps({
        "date":     date,
        "datetime": archive_key,
        "items":    [it._asdict() for it in all_items],
    }, ensure_ascii=False, indent=2)
    scripts_dir = Path(__file__).resolve().parent
    latest_file = scripts_dir / "news-latest.json"
    latest_file.write_text(payload, encoding="utf-8")
    archive_file = scripts_dir / f"news-{archive_key}.json"
    archive_file.write_text(payload, encoding="utf-8")

    total = len(all_items)
    print(f"\n保存: {out_path}")
    print(f"合計: {total} 件 | 今月累計コスト: ${month_cost:.4f}")


if __name__ == "__main__":
    main()
