from __future__ import annotations

import hashlib
import json
import math
import random
import re
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from scripts.ai_relevance import add_ai_relevance_fields, score_ai_relevance
from scripts.radar.common import (
    CREATOR_FRESHNESS_BONUS_HOURS,
    CREATOR_FRESHNESS_BONUS_POINTS,
    CREATOR_HOT_WINDOW_DAYS,
    CREATOR_SITE_IDS,
    GITHUB_REPO_SUBSCRIPTION_SITE_ID,
    MAOBIDAO_WECHAT_SITE_ID,
    RawItem,
    SUBSCRIPTION_TEXT_MARKERS,
    SUBSCRIPTION_URL_MARKERS,
    UTC,
    WEWE_RSS_SITE_ID,
    creator_metric_count,
    event_time,
    has_cjk,
    has_mojibake_noise,
    host_of_url,
    iso,
    is_mostly_english,
    maybe_fix_mojibake,
    normalize_url,
    parse_iso,
)
from scripts.radar.fetchers.public import (
    fetch_ai_breakfast,
    fetch_ai_hubtoday,
    fetch_aibase,
    fetch_aihot,
    fetch_bestblogs,
    fetch_buzzing,
    fetch_curated_ai_media,
    fetch_follow_builders,
    fetch_hacker_news_algolia,
    fetch_iris,
    fetch_newsnow,
    fetch_official_ai_updates,
    fetch_techurls,
    fetch_tophub,
    fetch_zeli,
)

"""Archive, dedupe, scoring, story merge, and payload builders."""

def collect_all(
    session: requests.Session,
    now: datetime,
    allowed_site_ids: frozenset[str] | None = None,
) -> tuple[list[RawItem], list[dict[str, Any]]]:
    tasks = [
        ("official_ai", "Official AI Updates", fetch_official_ai_updates),
        ("curated_media", "Curated Media", fetch_curated_ai_media),
        ("aibreakfast", "AI Breakfast", fetch_ai_breakfast),
        ("followbuilders", "Follow Builders", fetch_follow_builders),
        ("techurls", "TechURLs", fetch_techurls),
        ("buzzing", "Buzzing", fetch_buzzing),
        ("iris", "Info Flow", fetch_iris),
        ("bestblogs", "BestBlogs", fetch_bestblogs),
        ("tophub", "TopHub", fetch_tophub),
        ("zeli", "Zeli", fetch_zeli),
        ("hackernews", "Hacker News", fetch_hacker_news_algolia),
        ("aihubtoday", "AI HubToday", fetch_ai_hubtoday),
        ("aibase", "AIbase", fetch_aibase),
        ("aihot", "AI HOT", fetch_aihot),
        ("newsnow", "NewsNow", fetch_newsnow),
    ]

    raw_items: list[RawItem] = []
    statuses: list[dict[str, Any]] = []

    for site_id, site_name, fn in tasks:
        if allowed_site_ids is not None and site_id not in allowed_site_ids:
            continue
        start = time.perf_counter()
        error = None
        count = 0
        try:
            items = fn(session, now)
            count = len(items)
            raw_items.extend(items)
        except Exception as exc:
            error = str(exc)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        statuses.append(
            {
                "site_id": site_id,
                "site_name": site_name,
                "ok": error is None,
                "item_count": count,
                "duration_ms": elapsed_ms,
                "error": error,
            }
        )

    return raw_items, statuses



def load_archive(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    items = payload.get("items", [])
    out: dict[str, dict[str, Any]] = {}
    if isinstance(items, list):
        for it in items:
            item_id = it.get("id")
            if item_id:
                out[item_id] = it
    elif isinstance(items, dict):
        for item_id, it in items.items():
            if isinstance(it, dict):
                it["id"] = item_id
                out[item_id] = it
    return out



def filter_archive_by_source_ids(
    archive: dict[str, dict[str, Any]],
    allowed_source_ids: frozenset[str] | None,
) -> dict[str, dict[str, Any]]:
    if allowed_source_ids is None:
        return archive
    return {
        item_id: record
        for item_id, record in archive.items()
        if str(record.get("site_id") or "") in allowed_source_ids
    }


def filter_raw_items_by_collect_window(
    raw_items: list[RawItem],
    now: datetime,
    window_hours: int,
    existing_source_counts: dict[tuple[str, str], int] | None = None,
    seed_min_items_per_source: int = 5,
) -> tuple[list[RawItem], int]:
    if window_hours <= 0:
        return raw_items, 0
    window_start = now - timedelta(hours=window_hours)
    window_end = now + timedelta(minutes=5)
    filtered: list[RawItem] = []
    skipped = 0
    for item in raw_items:
        source_key = (item.site_id, item.source)
        existing_count = int((existing_source_counts or {}).get(source_key, 0))
        if existing_source_counts is not None and existing_count < seed_min_items_per_source:
            filtered.append(item)
            existing_source_counts[source_key] = existing_count + 1
            continue
        if not item.published_at or item.published_at < window_start or item.published_at > window_end:
            skipped += 1
            continue
        filtered.append(item)
    return filtered, skipped


def archive_source_counts(archive: dict[str, dict[str, Any]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for record in archive.values():
        key = (str(record.get("site_id") or ""), str(record.get("source") or ""))
        if not key[0] and not key[1]:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


SOURCE_TIER_BY_SITE: dict[str, tuple[str, str, int]] = {
    "official_ai": ("official", "官方一手源", 0),
    "curated_media": ("ai_media", "精选AI媒体", 2),
    "aibreakfast": ("ai_vertical", "AI垂直源", 1),
    "aihubtoday": ("ai_vertical", "AI垂直源", 1),
    "aibase": ("ai_vertical", "AI垂直源", 1),
    "aihot": ("ai_vertical", "AI垂直源", 1),
    "bestblogs": ("ai_vertical", "AI垂直源", 1),
    "waytoagi": ("community", "社区更新", 2),
    "followbuilders": ("builders", "Builders/X源", 2),
    "opmlrss": ("user_opml", "RSS/OPML", 3),
    "bilibili_dynamic": ("self_media", "我的订阅", 4),
    "tikhub_douyin": ("self_media", "我的订阅", 4),
    "tikhub_xiaohongshu": ("self_media", "我的订阅", 4),
    "mediacrawler_douyin": ("self_media", "我的订阅", 4),
    "mediacrawler_xhs": ("self_media", "我的订阅", 4),
    GITHUB_REPO_SUBSCRIPTION_SITE_ID: ("self_media", "我的订阅", 4),
    MAOBIDAO_WECHAT_SITE_ID: ("self_media", "我的订阅", 4),
    WEWE_RSS_SITE_ID: ("self_media", "我的订阅", 4),
    "xapi": ("advanced", "高级源", 4),
    "socialdata_x": ("advanced", "高级源", 4),
    "techurls": ("discussion", "热议参考", 5),
    "buzzing": ("discussion", "热议参考", 5),
    "iris": ("discussion", "热议参考", 5),
    "tophub": ("discussion", "热议参考", 5),
    "zeli": ("discussion", "热议参考", 5),
    "hackernews": ("discussion", "热议参考", 5),
    "newsnow": ("discussion", "热议参考", 5),
}

SOURCE_TIER_IMPORTANCE = {
    "official": 1.0,
    "ai_vertical": 0.78,
    "ai_media": 0.58,
    "community": 0.54,
    "builders": 0.62,
    "user_opml": 0.5,
    "self_media": 0.48,
    "advanced": 0.45,
    "discussion": 0.32,
    "other": 0.25,
}

TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "for",
    "from",
    "in",
    "into",
    "is",
    "new",
    "of",
    "on",
    "the",
    "to",
    "with",
    "发布",
    "推出",
    "上线",
    "更新",
}

VENDOR_ALIASES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "google": "google",
    "deepmind": "google",
    "gemini": "google",
    "microsoft": "microsoft",
    "github": "github",
    "huggingface": "huggingface",
    "hugging face": "huggingface",
    "meta": "meta",
    "llama": "meta",
    "deepseek": "deepseek",
    "mistral": "mistral",
    "xai": "xai",
    "grok": "xai",
}

MODEL_RE = re.compile(
    r"(?i)\b("
    r"gpt[-\s]?\d+(?:\.\d+)?[a-z]*|"
    r"claude(?:[-\s]?(?:opus|sonnet|haiku))?[-\s]?\d+(?:\.\d+)?|"
    r"gemini[-\s]?\d+(?:\.\d+)?|"
    r"llama[-\s]?\d+(?:\.\d+)?|"
    r"deepseek[-\s]?[a-z0-9.]+|"
    r"grok[-\s]?\d+(?:\.\d+)?|"
    r"mistral[-\s]?[a-z0-9.]+"
    r")\b"
)


def source_tier_for_site(site_id: str) -> dict[str, Any]:
    sid = str(site_id or "").strip().lower()
    if sid.startswith("opmlrss"):
        sid = "opmlrss"
    tier, label, rank = SOURCE_TIER_BY_SITE.get(sid, ("other", "其他来源", 9))
    return {"source_tier": tier, "source_tier_label": label, "source_tier_rank": rank}


def add_source_tier_fields(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out.update(source_tier_for_site(str(out.get("site_id") or "")))
    return out


def source_tier_sort_key(record: dict[str, Any]) -> tuple[int, float, str]:
    tier = source_tier_for_site(str(record.get("site_id") or ""))
    ts = event_time(record)
    return (int(tier["source_tier_rank"]), -(ts.timestamp() if ts else 0), str(record.get("title") or ""))


AI_KEYWORDS = [
    "aigc",
    "llm",
    "gpt",
    "claude",
    "gemini",
    "deepseek",
    "openai",
    "anthropic",
    "copilot",
    "codex",
    "mcp",
    "hugging face",
    "huggingface",
    "transformer",
    "prompt",
    "diffusion",
    "agent",
    "多模态",
    "大模型",
    "模型",
    "人工智能",
    "机器学习",
    "深度学习",
    "智能体",
    "算力",
    "推理",
    "微调",
]

TECH_KEYWORDS = [
    "robot",
    "robotics",
    "embodied",
    "autonomous",
    "vision",
    "chip",
    "semiconductor",
    "cuda",
    "npu",
    "gpu",
    "cloud",
    "developer",
    "开源",
    "技术",
    "编程",
    "软件",
    "芯片",
    "机器人",
    "具身",
]

NOISE_KEYWORDS = [
    "娱乐",
    "明星",
    "八卦",
    "足球",
    "篮球",
    "彩票",
    "情感",
    "旅游",
    "美食",
]

COMMERCE_NOISE_KEYWORDS = [
    "淘宝",
    "天猫",
    "京东",
    "拼多多",
    "券后",
    "热销总榜",
    "促销",
    "优惠",
    "补贴",
    "下单",
    "首发价",
]

EN_SIGNAL_RE = re.compile(
    r"(?i)(?<![a-z0-9])(ai|aigc|llm|gpt|openai|anthropic|deepseek|gemini|claude|robot|robotics|embodied|autonomous|machine learning|artificial intelligence|transformer|diffusion|agent)(?![a-z0-9])"
)

TOPHUB_ALLOW_KEYWORDS = [
    "readhub · ai",
    "hacker news",
    "github",
    "product hunt",
    "v2ex",
    "少数派",
    "infoq",
    "36氪",
    "机器之心",
    "量子位",
    "科技",
    "人工智能",
    "机器人",
    "具身",
    "开源",
]

TOPHUB_BLOCK_KEYWORDS = [
    "热销总榜",
    "淘宝",
    "天猫",
    "京东",
    "拼多多",
    "抖音",
    "快手",
    "微博",
    "小红书",
]


MEANINGFUL_EN_SIGNAL_RE = re.compile(
    r"(?i)(?<![a-z0-9])(ai|aigc|llm|gpt|openai|anthropic|deepseek|gemini|claude|robot|robotics|embodied|autonomous|machine learning|artificial intelligence|transformer|diffusion)(?![a-z0-9])"
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SECRET_LIKE_RE = re.compile(r"\b(sk-(?!hynix\b)[A-Za-z0-9_-]{12,}|(?:api[_-]?key|secret|token)=([^\s&]{6,}))\b", re.I)
URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>]+")
BROAD_AI_TERMS = {"agent", "模型", "推理"}



def normalize_source_for_display(site_id: str, source: str, url: str) -> str:
    src = (source or "").strip()
    if not src:
        host = host_of_url(url)
        if host.startswith("www."):
            host = host[4:]
        return host or "未分区"
    if site_id == "buzzing" and src.lower() == "buzzing":
        host = host_of_url(url)
        if host.startswith("www."):
            host = host[4:]
        return host or src
    return src


def is_ai_related_record(record: dict[str, Any]) -> bool:
    if has_mojibake_noise(str(record.get("source") or "")) or has_mojibake_noise(str(record.get("title") or "")):
        return False
    return bool(score_ai_relevance(record)["is_ai_related"])


def load_title_zh_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if str(k).strip() and str(v).strip()}
    except Exception:
        pass
    return {}


def translate_to_zh_cn(session: requests.Session, text: str) -> str | None:
    s = (text or "").strip()
    if not s:
        return None
    try:
        r = session.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": "zh-CN",
                "dt": "t",
                "q": s,
            },
            timeout=12,
        )
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, list) or not payload:
            return None
        segs = payload[0]
        if not isinstance(segs, list):
            return None
        translated = "".join(str(seg[0]) for seg in segs if isinstance(seg, list) and seg and seg[0])
        translated = translated.strip()
        if translated and translated != s:
            return translated
    except Exception:
        return None
    return None


def add_bilingual_fields(
    items_ai: list[dict[str, Any]],
    items_all: list[dict[str, Any]],
    session: requests.Session,
    cache: dict[str, str],
    max_new_translations: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    zh_by_url: dict[str, str] = {}
    for it in items_all:
        title = str(it.get("title") or "").strip()
        url = normalize_url(str(it.get("url") or ""))
        if title and url and has_cjk(title):
            zh_by_url[url] = title

    translated_now = 0

    def enrich(item: dict[str, Any], allow_translate: bool) -> dict[str, Any]:
        nonlocal translated_now
        out = dict(item)
        title = str(out.get("title") or "").strip()
        url = normalize_url(str(out.get("url") or ""))

        out["title_original"] = title
        out["title_en"] = None
        out["title_zh"] = None
        out["title_bilingual"] = title

        if has_cjk(title):
            out["title_zh"] = title
            return out

        if not is_mostly_english(title):
            return out

        out["title_en"] = title

        zh_title = zh_by_url.get(url)
        if not zh_title:
            zh_title = cache.get(title)
        if not zh_title and allow_translate and translated_now < max_new_translations:
            tr = translate_to_zh_cn(session, title)
            if tr and has_cjk(tr):
                zh_title = tr
                cache[title] = tr
                translated_now += 1

        if zh_title:
            out["title_zh"] = zh_title
            out["title_bilingual"] = f"{zh_title} / {title}"
        return out

    ai_out = [enrich(it, allow_translate=True) for it in items_ai]
    all_out = [enrich(it, allow_translate=False) for it in items_all]
    return ai_out, all_out, cache


def dedupe_items_by_title_url(items: list[dict[str, Any]], random_pick: bool = True) -> list[dict[str, Any]]:
    def duplicate_pick_key(record: dict[str, Any]) -> tuple[int, float, float, str]:
        tier_rank, published_sort, title = source_tier_sort_key(record)
        last_seen = parse_iso(record.get("last_seen_at")) or event_time(record)
        return (tier_rank, published_sort, -(last_seen.timestamp() if last_seen else 0), title)

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        site_id = str(item.get("site_id") or "").strip().lower()
        title = str(item.get("title_original") or item.get("title") or "").strip().lower()
        url = normalize_url(str(item.get("url") or ""))
        if site_id == "aihubtoday":
            key = f"url::{url}"
        else:
            key = f"{title}||{url}"
        groups.setdefault(key, []).append(item)

    out: list[dict[str, Any]] = []
    for values in groups.values():
        if random_pick:
            out.append(random.choice(values))
        else:
            chosen = min(values, key=duplicate_pick_key)
            out.append(chosen)

    out.sort(key=source_tier_sort_key)
    return out


def suppress_near_duplicate_items(
    items: list[dict[str, Any]],
    window_hours: float = 6.0,
    similarity_threshold: float = 0.9,
) -> list[dict[str, Any]]:
    """Collapse near-identical items from the same site (rewritten syndication,
    e.g. "推出法案" vs "推出立法") that exact title||url dedup cannot catch.
    Keeps the more authoritative copy (tier, then ai_score, then earliest)."""

    def quality(item: dict[str, Any]) -> tuple:
        tier_rank = item.get("source_tier_rank")
        try:
            tier_rank = int(tier_rank)
        except Exception:
            tier_rank = 99
        try:
            score = float(item.get("ai_score") or 0)
        except Exception:
            score = 0.0
        ts = event_time(item) or datetime.max.replace(tzinfo=UTC)
        return (-tier_rank, score, -ts.timestamp())

    by_site: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_site.setdefault(str(item.get("site_id") or ""), []).append(item)

    dropped_ids: set[str] = set()
    for site_items in by_site.values():
        ordered = sorted(site_items, key=lambda x: event_time(x) or datetime.min.replace(tzinfo=UTC))
        kept: list[tuple[dict[str, Any], str, set[str], datetime | None]] = []
        for item in ordered:
            title = normalized_story_title(item)
            tokens = title_tokens(title)
            ts = event_time(item)
            if not title_is_mergeable(title):
                kept.append((item, title, tokens, ts))
                continue
            duplicate_of = None
            for kept_entry in reversed(kept[-60:]):
                other, other_title, other_tokens, other_ts = kept_entry
                if ts and other_ts and abs((ts - other_ts).total_seconds()) / 3600 > window_hours:
                    continue
                if not tokens or not other_tokens:
                    continue
                jaccard = len(tokens & other_tokens) / len(tokens | other_tokens)
                if jaccard < 0.5:
                    continue
                if title_similarity(title, other_title) >= similarity_threshold and story_titles_can_merge(title, other_title):
                    duplicate_of = kept_entry
                    break
            if duplicate_of is None:
                kept.append((item, title, tokens, ts))
                continue
            other = duplicate_of[0]
            if quality(item) > quality(other):
                dropped_ids.add(str(other.get("id") or id(other)))
                kept[kept.index(duplicate_of)] = (item, title, tokens, ts)
            else:
                dropped_ids.add(str(item.get("id") or id(item)))

    return [item for item in items if str(item.get("id") or id(item)) not in dropped_ids]


def canonical_story_url(raw_url: str) -> str:
    normalized = normalize_url(raw_url)
    try:
        parsed = urlparse(normalized)
    except Exception:
        return normalized
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if query_pairs:
        identity_keys = {"id", "item", "p"}
        kept = [(k, v) for k, v in query_pairs if k.lower() in identity_keys]
        parsed = parsed._replace(query=urlencode(kept, doseq=True))
    return urlunparse(parsed).rstrip("/")


def title_tokens(title: str) -> set[str]:
    compact = re.sub(r"https?://\S+", " ", str(title or "").lower())
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", compact)
    return {tok for tok in tokens if tok not in TITLE_STOPWORDS and len(tok) >= 2}


def normalized_story_title(item: dict[str, Any]) -> str:
    title = str(item.get("title_original") or item.get("title") or "").strip().lower()
    if item.get("title_bilingual"):
        title = re.sub(r"\s*/\s*.+$", "", title)
    return re.sub(r"\s+", " ", title)


def title_is_mergeable(title: str) -> bool:
    tokens = title_tokens(title)
    return len(tokens) >= 4 and len(str(title or "").strip()) >= 18


def title_similarity(a: str, b: str) -> float:
    ta = title_tokens(a)
    tb = title_tokens(b)
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / len(ta | tb)
    sequence = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return round(max(sequence, (sequence * 0.6) + (jaccard * 0.4)), 4)


def title_entities(title: str) -> tuple[set[str], set[str]]:
    lower = str(title or "").lower()
    vendors = {canonical for alias, canonical in VENDOR_ALIASES.items() if alias in lower}
    models = {re.sub(r"\s+", "-", match.group(1).lower()) for match in MODEL_RE.finditer(lower)}
    return vendors, models


def story_titles_can_merge(a: str, b: str) -> bool:
    vendors_a, models_a = title_entities(a)
    vendors_b, models_b = title_entities(b)
    if vendors_a and vendors_b and vendors_a.isdisjoint(vendors_b):
        return False
    if models_a and models_b and models_a.isdisjoint(models_b):
        return False
    return True


def recency_score(record: dict[str, Any], now: datetime, window_hours: int) -> float:
    ts = event_time(record)
    if not ts:
        return 0.0
    age_hours = max(0.0, (now - ts).total_seconds() / 3600)
    return max(0.0, min(1.0, (float(window_hours) - age_hours) / max(1.0, float(window_hours))))


def headline_freshness_score(record: dict[str, Any], now: datetime, half_life_hours: float = 48.0) -> float:
    ts = event_time(record)
    if not ts:
        return 0.0
    age_hours = max(0.0, (now - ts).total_seconds() / 3600)
    return max(0.0, min(1.0, 0.5 ** (age_hours / max(1.0, half_life_hours))))


def ai_relevance_score(record: dict[str, Any]) -> float:
    value = record.get("ai_relevance_score")
    if value is None:
        value = record.get("ai_score")
    if value is None and isinstance(record.get("ai_relevance"), dict):
        value = record["ai_relevance"].get("score")
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 1.0 if record.get("ai_is_related") else 0.0


def add_creator_ranking_fields(record: dict[str, Any], now: datetime) -> dict[str, Any]:
    out = dict(record)
    metrics = record.get("creator_metrics") if isinstance(record.get("creator_metrics"), dict) else {}
    likes = creator_metric_count(metrics.get("likes"))
    comments = creator_metric_count(metrics.get("comments"))
    collects = creator_metric_count(metrics.get("collects"))
    shares = creator_metric_count(metrics.get("shares"))
    weighted_engagement = likes + (comments * 2.0) + (collects * 1.5) + (shares * 2.0)

    # Xiaohongshu engagement is smaller in absolute terms than Douyin, so use
    # separate fixed log scales instead of pretending raw counts are comparable.
    scale = 22.0 if str(record.get("site_id") or "") == "tikhub_xiaohongshu" else 20.0
    heat_score = min(100.0, scale * math.log10(1.0 + weighted_engagement))
    published = event_time(record)
    age_hours = (now - published).total_seconds() / 3600 if published else float("inf")
    freshness_bonus = CREATOR_FRESHNESS_BONUS_POINTS if 0 <= age_hours <= CREATOR_FRESHNESS_BONUS_HOURS else 0.0
    hot_score = min(100.0, (heat_score * 0.85) + freshness_bonus)

    out["creator_metrics"] = {
        "likes": likes,
        "comments": comments,
        "collects": collects,
        "shares": shares,
    }
    out["creator_engagement_total"] = round(weighted_engagement, 1)
    out["creator_heat_score"] = round(heat_score, 1)
    out["creator_freshness_bonus"] = round(freshness_bonus, 1)
    out["creator_hot_score"] = round(hot_score, 1)
    return out


def is_subscription_record(record: dict[str, Any]) -> bool:
    site_id = str(record.get("site_id") or "").strip().lower()
    if site_id in CREATOR_SITE_IDS:
        return True
    url = str(record.get("url") or "").strip().lower()
    if any(marker in url for marker in SUBSCRIPTION_URL_MARKERS):
        return True
    hay = " ".join(
        str(record.get(key) or "")
        for key in ("site_name", "source", "source_kind", "search_surface", "platform")
    ).lower()
    return any(marker in hay for marker in SUBSCRIPTION_TEXT_MARKERS)


def editorial_score(record: dict[str, Any]) -> float:
    """External or internal editorial strength used by the headline ranker."""
    value = record.get("aihot_score")
    try:
        if value is not None:
            score = float(value)
            return max(0.0, min(1.0, score / 100 if score > 1 else score))
    except Exception:
        pass
    site_id = str(record.get("site_id") or "")
    if site_id == "official_ai":
        return 0.9
    if site_id == "aihot":
        return 0.78
    if record.get("ai_is_related"):
        return max(0.45, ai_relevance_score(record) * 0.72)
    return ai_relevance_score(record) * 0.6


def story_id_for_item(item: dict[str, Any]) -> str:
    url = canonical_story_url(str(item.get("url") or ""))
    title = normalized_story_title(item)
    basis = url or title or str(item.get("id") or "")
    return "story_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def calculate_item_importance(
    item: dict[str, Any],
    now: datetime,
    window_hours: int,
    duplicate_count: int = 1,
) -> dict[str, Any]:
    tier = str(item.get("source_tier") or source_tier_for_site(str(item.get("site_id") or "")).get("source_tier"))
    source_score = SOURCE_TIER_IMPORTANCE.get(tier, SOURCE_TIER_IMPORTANCE["other"])
    relevance = ai_relevance_score(item)
    recency = headline_freshness_score(item, now)
    editorial = editorial_score(item)
    heat = min(1.0, max(0, duplicate_count - 1) / 4)
    score = (editorial * 0.3) + (source_score * 0.22) + (relevance * 0.2) + (recency * 0.18) + (heat * 0.1)
    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "breakdown": {
            "editorial": round(editorial, 4),
            "source_tier": round(source_score, 4),
            "ai_relevance": round(relevance, 4),
            "recency": round(recency, 4),
            "story_heat": round(heat, 4),
        },
    }


def story_category(score: float, primary_item: dict[str, Any], duplicate_count: int) -> str:
    tier = str(primary_item.get("source_tier") or source_tier_for_site(str(primary_item.get("site_id") or "")).get("source_tier"))
    if tier == "official":
        return "official"
    if duplicate_count >= 3:
        return "multi_source"
    if score >= 0.72:
        return "industry"
    return "watch"


def importance_label(category: str) -> str:
    return {
        "official": "官方更新",
        "multi_source": "多源热议",
        "industry": "行业动态",
        "watch": "值得关注",
    }.get(category, "值得关注")


def choose_primary_story_item(
    items: list[dict[str, Any]],
    now: datetime,
    window_hours: int,
) -> dict[str, Any]:
    def key(item: dict[str, Any]) -> tuple[int, float, float, str]:
        tier_rank = int(source_tier_for_site(str(item.get("site_id") or "")).get("source_tier_rank", 9))
        importance = calculate_item_importance(item, now, window_hours, duplicate_count=len(items))["score"]
        ts = event_time(item)
        return (tier_rank, -importance, -(ts.timestamp() if ts else 0), str(item.get("title") or ""))

    return min(items, key=key)


def story_item_link(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "title": item.get("title_bilingual") or item.get("title"),
        "url": item.get("url"),
        "source": item.get("source"),
        "source_name": item.get("site_name"),
        "site_id": item.get("site_id"),
        "published_at": item.get("published_at"),
    }


def story_reasons(primary: dict[str, Any], score: float, duplicate_count: int) -> list[str]:
    reasons: list[str] = []
    tier = source_tier_for_site(str(primary.get("site_id") or ""))
    if tier["source_tier"] == "official":
        reasons.append("official_source")
    if duplicate_count >= 2:
        reasons.append("multi_source")
    if ai_relevance_score(primary) >= 0.8:
        reasons.append("high_ai_relevance")
    if score >= 0.75:
        reasons.append("high_importance")
    if not reasons:
        reasons.append("recent_ai_signal")
    return reasons


def build_story_record(
    story_id: str,
    items: list[dict[str, Any]],
    now: datetime,
    window_hours: int,
) -> dict[str, Any]:
    sorted_items = sorted(items, key=source_tier_sort_key)
    primary = choose_primary_story_item(sorted_items, now, window_hours)
    importance = calculate_item_importance(primary, now, window_hours, duplicate_count=len(items))
    score = importance["score"]
    category = story_category(score, primary, len(items))
    times = [ts for ts in (event_time(item) for item in sorted_items) if ts]
    source_refs = [story_item_link(item) for item in sorted_items]
    source_names = sorted({str(item.get("source") or item.get("site_name") or "") for item in sorted_items if item.get("source") or item.get("site_name")})
    title = primary.get("title_bilingual") or primary.get("title")
    url = primary.get("url")
    return {
        "story_id": story_id,
        "title": title,
        "url": url,
        "primary_url": url,
        "source": primary.get("source"),
        "source_name": primary.get("site_name"),
        "sources": source_refs,
        "source_count": len(source_refs),
        "source_names": source_names,
        "items": source_refs,
        "item_count": len(sorted_items),
        "duplicate_count": len(sorted_items),
        "score": score,
        "importance": score,
        "importance_score": score,
        "importance_label": importance_label(category),
        "importance_breakdown": importance["breakdown"],
        "category": category,
        "reasons": story_reasons(primary, score, len(sorted_items)),
        "earliest_at": iso(min(times)) if times else None,
        "latest_at": iso(max(times)) if times else None,
        "primary_item": {
            "id": primary.get("id"),
            "title": title,
            "url": url,
            "source": primary.get("source"),
            "source_name": primary.get("site_name"),
        },
    }


def merge_story_items(
    items: list[dict[str, Any]],
    now: datetime,
    window_hours: int,
    title_window_hours: int = 6,
    title_threshold: float = 0.86,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    group_titles: dict[str, str] = {}
    group_times: dict[str, datetime | None] = {}
    canonical_to_story: dict[str, str] = {}
    events: list[dict[str, Any]] = []

    ordered = sorted(items, key=lambda item: event_time(item) or datetime.min.replace(tzinfo=UTC))
    for item in ordered:
        item_id = str(item.get("id") or "")
        canonical_url = canonical_story_url(str(item.get("url") or ""))
        title = normalized_story_title(item)
        item_time = event_time(item)
        story_id: str | None = None
        reason = ""
        similarity = 0.0

        if canonical_url and canonical_url in canonical_to_story:
            story_id = canonical_to_story[canonical_url]
            reason = "canonical_url"
            similarity = 1.0
        elif title_is_mergeable(title):
            for candidate_id, candidate_title in group_titles.items():
                candidate_time = group_times.get(candidate_id)
                if item_time and candidate_time:
                    delta_hours = abs((item_time - candidate_time).total_seconds()) / 3600
                    if delta_hours > title_window_hours:
                        continue
                sim = title_similarity(title, candidate_title)
                if sim >= title_threshold and story_titles_can_merge(title, candidate_title):
                    story_id = candidate_id
                    reason = "title_similarity"
                    similarity = sim
                    break

        if story_id is None:
            story_id = story_id_for_item(item)
            groups[story_id] = []
            group_titles[story_id] = title
            group_times[story_id] = item_time
            if canonical_url:
                canonical_to_story[canonical_url] = story_id
        else:
            events.append(
                {
                    "story_id": story_id,
                    "item_id": item_id,
                    "merged_into": story_id,
                    "reason": reason,
                    "similarity": round(similarity, 4),
                }
            )
            if canonical_url:
                canonical_to_story[canonical_url] = story_id

        groups.setdefault(story_id, []).append(item)

    stories = [build_story_record(story_id, group_items, now, window_hours) for story_id, group_items in groups.items()]
    stories.sort(key=lambda story: (-float(story.get("score") or 0), str(story.get("latest_at") or ""), str(story.get("title") or "")))
    return stories, events


BRIEF_SCORE_GATE = 0.72


def story_passes_brief_gate(story: dict[str, Any]) -> bool:
    """宁缺毋滥: a story earns a brief slot via multi-source confirmation or a
    strong score. Quiet days produce a short (possibly empty) brief instead of
    a padded one."""
    try:
        sources = int(story.get("source_count") or 1)
    except Exception:
        sources = 1
    try:
        score = float(story.get("score") or 0)
    except Exception:
        score = 0.0
    return sources >= 2 or score >= BRIEF_SCORE_GATE


def select_diverse_stories(
    stories: list[dict[str, Any]],
    limit: int,
    same_source_penalty: float = 0.03,
) -> list[dict[str, Any]]:
    """Greedy top-N by score with a per-source decay so one prolific source
    cannot fill the brief, plus same-cluster suppression across the whole
    window: a story whose title near-duplicates an already picked one is
    skipped, so an event reposted hours apart (outside the merge window)
    still occupies only one slot."""
    candidates = sorted(stories, key=lambda story: (-float(story.get("score") or 0), str(story.get("title") or "")))
    picked: list[dict[str, Any]] = []
    picked_titles: list[tuple[str, set[str]]] = []
    picked_per_source: dict[str, int] = {}
    remaining = list(candidates)

    def near_duplicate_of_picked(story: dict[str, Any]) -> bool:
        title = normalized_story_title(story)
        if not title_is_mergeable(title):
            return False
        tokens = title_tokens(title)
        for other_title, other_tokens in picked_titles:
            if not tokens or not other_tokens:
                continue
            if len(tokens & other_tokens) / len(tokens | other_tokens) < 0.4:
                continue
            if title_similarity(title, other_title) >= 0.86 and story_titles_can_merge(title, other_title):
                return True
        return False

    while remaining and len(picked) < limit:
        best_idx = -1
        best_eff = float("-inf")
        for idx, story in enumerate(remaining):
            source = str(story.get("source") or story.get("source_name") or "")
            eff = float(story.get("score") or 0) - same_source_penalty * picked_per_source.get(source, 0)
            if eff > best_eff:
                best_eff = eff
                best_idx = idx
        if best_idx < 0:
            break
        chosen = remaining.pop(best_idx)
        if near_duplicate_of_picked(chosen):
            continue
        source = str(chosen.get("source") or chosen.get("source_name") or "")
        picked_per_source[source] = picked_per_source.get(source, 0) + 1
        picked.append(chosen)
        picked_titles.append((normalized_story_title(chosen), title_tokens(normalized_story_title(chosen))))
    return picked


def build_daily_brief_payload(
    stories: list[dict[str, Any]],
    generated_at: str,
    window_hours: int,
    max_items: int = 20,
) -> dict[str, Any]:
    gated = [story for story in stories if story_passes_brief_gate(story)]
    items = select_diverse_stories(gated, max_items)
    return {
        "generated_at": generated_at,
        "window_hours": window_hours,
        "total_items": len(items),
        "items": items,
    }


def build_stories_payload(
    stories: list[dict[str, Any]],
    generated_at: str,
    window_hours: int,
) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "window_hours": window_hours,
        "total_stories": len(stories),
        "stories": stories,
    }


def build_merge_log_payload(events: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "merge_strategy": "url_or_title_similarity_v0_6",
        "total_events": len(events),
        "events": events,
    }


def build_creator_hot_items(
    archive: dict[str, dict[str, Any]],
    now: datetime,
    *,
    ai_only: bool,
    window_days: int | None = CREATOR_HOT_WINDOW_DAYS,
    window_hours: int | None = None,
) -> list[dict[str, Any]]:
    if window_hours is not None:
        window_start = now - timedelta(hours=window_hours) if window_hours > 0 else None
    else:
        window_start = now - timedelta(days=window_days) if window_days and window_days > 0 else None
    items: list[dict[str, Any]] = []
    for record in archive.values():
        if not is_subscription_record(record):
            continue
        if window_hours is not None and not parse_iso(record.get("published_at")):
            continue
        published = event_time(record)
        if not published or published > now:
            continue
        if window_start and published < window_start:
            continue
        normalized = dict(record)
        normalized["title"] = maybe_fix_mojibake(str(normalized.get("title") or ""))
        normalized["source"] = maybe_fix_mojibake(normalize_source_for_display(
            str(normalized.get("site_id") or ""),
            str(normalized.get("source") or ""),
            str(normalized.get("url") or ""),
        ))
        if not isinstance(normalized.get("creator_metrics"), dict):
            normalized["creator_metrics"] = {}
        normalized = add_ai_relevance_fields(normalized)
        if ai_only and not normalized.get("ai_is_related", is_ai_related_record(normalized)):
            continue
        normalized = add_source_tier_fields(normalized)
        if is_subscription_record(normalized):
            normalized["source_tier"] = "self_media"
            normalized["source_tier_label"] = "我的订阅"
            normalized["source_tier_rank"] = 4
        items.append(add_creator_ranking_fields(normalized, now))

    deduped = suppress_near_duplicate_items(dedupe_items_by_title_url(items, random_pick=False))
    deduped.sort(
        key=lambda item: (
            float(item.get("creator_hot_score") or 0),
            event_time(item) or datetime.min.replace(tzinfo=UTC),
        ),
        reverse=True,
    )
    return deduped


def build_latest_payloads(latest_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split initial AI payload from bulky all-mode lists for lazy browser loading."""
    slim_payload = dict(latest_payload)
    all_payload = {
        "generated_at": latest_payload.get("generated_at"),
        "window_hours": latest_payload.get("window_hours"),
        "time_scope": latest_payload.get("time_scope"),
        "source_scope": latest_payload.get("source_scope"),
        "collection_window_hours": latest_payload.get("collection_window_hours"),
        "topic_filter": latest_payload.get("topic_filter"),
        "ai_relevance_threshold": latest_payload.get("ai_relevance_threshold"),
        "total_items_raw": latest_payload.get("total_items_raw"),
        "total_items_all_mode": latest_payload.get("total_items_all_mode"),
        "creator_window_days": latest_payload.get("creator_window_days"),
        "creator_window_hours": latest_payload.get("creator_window_hours"),
        "creator_time_scope": latest_payload.get("creator_time_scope"),
        "creator_ranking": latest_payload.get("creator_ranking"),
        "creator_items_all": latest_payload.get("creator_items_all", []),
        "items_all": latest_payload.get("items_all", []),
        "items_all_raw": latest_payload.get("items_all_raw", []),
    }
    slim_payload.pop("items_all", None)
    slim_payload.pop("items_all_raw", None)
    slim_payload["all_mode_data_url"] = "data/latest-24h-all.json"
    slim_payload["stories_data_url"] = "data/stories-merged.json"
    return slim_payload, all_payload



