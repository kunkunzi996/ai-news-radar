#!/usr/bin/env python3
"""Aggregate updates from multiple AI news sites and produce 24h snapshot data."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parseaddr
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from scripts.ai_relevance import add_ai_relevance_fields, score_ai_relevance
except ModuleNotFoundError:  # pragma: no cover - direct `python scripts/update_news.py`
    from ai_relevance import add_ai_relevance_fields, score_ai_relevance

try:
    import feedparser
except ModuleNotFoundError:
    feedparser = None

UTC = timezone.utc
DROP_QUERY_PARAMS = {
    "ref",
    "spm",
    "fbclid",
    "gclid",
    "igshid",
    "mkt_tok",
    "mc_cid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
    "xsec_token",
    "xsec_source",
}
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
SH_TZ = ZoneInfo("Asia/Shanghai")
WAYTOAGI_DEFAULT = (
    "https://waytoagi.feishu.cn/wiki/QPe5w5g7UisbEkkow8XcDmOpn8e?fromScene=spaceOverview"
)
WAYTOAGI_HISTORY_FALLBACK = "https://waytoagi.feishu.cn/wiki/FjiOwWp2giA7hRk6jjfcPioCnAc"

RSS_FEED_REPLACEMENTS: dict[str, str] = {
    "https://rsshub.app/infoq/recommend": "https://www.infoq.cn/feed",
    "https://rsshub.app/huggingface/blog-zh": "https://huggingface.co/blog/feed.xml",
    "https://rsshub.app/readhub/daily": "https://readhub.cn/rss",
    "https://rsshub.app/36kr/hot-list": "https://36kr.com/feed",
    "https://rsshub.app/sspai/index": "https://sspai.com/feed",
    "https://rsshub.app/sspai/matrix": "https://sspai.com/feed",
    "https://rsshub.app/meituan/tech": "https://tech.meituan.com/feed",
    "https://mjg59.dreamwidth.org/data/rss": "http://mjg59.dreamwidth.org/data/rss",
}

RSS_FEED_SKIP_PREFIXES: tuple[str, ...] = (
    "https://rsshub.app/telegram/channel/",
    "https://rsshub.app/jike/",
    "https://rsshub.app/bilibili/",
    "https://rsshub.app/zhihu/",
    "https://rsshub.app/xiaoyuzhou/podcast/",
    "https://rsshub.app/xyzrank",
    "https://rsshub.app/mittrchina/hot",
    "https://wechat2rss.bestblogs.dev/",
    "https://werss.bestblogs.dev/",
    "http://47.122.94.119:18080/",
)

RSS_FEED_SKIP_EXACT: set[str] = {
    "https://rachelbythebay.com/w/atom.xml",
    "https://flak.tedunangst.com/rss",
}

OFFICIAL_AI_FEEDS: tuple[dict[str, str], ...] = (
    {
        "title": "OpenAI News",
        "xml_url": "https://openai.com/news/rss.xml",
        "html_url": "https://openai.com/news",
    },
    {
        "title": "Google DeepMind",
        "xml_url": "https://deepmind.google/blog/rss.xml",
        "html_url": "https://deepmind.google/blog",
    },
    {
        "title": "Google AI Blog",
        "xml_url": "https://blog.google/innovation-and-ai/technology/ai/rss/",
        "html_url": "https://blog.google/innovation-and-ai/technology/ai/",
    },
    {
        "title": "Hugging Face Blog",
        "xml_url": "https://huggingface.co/blog/feed.xml",
        "html_url": "https://huggingface.co/blog",
    },
    {
        "title": "GitHub AI & ML",
        "xml_url": "https://github.blog/ai-and-ml/feed/",
        "html_url": "https://github.blog/ai-and-ml/",
    },
    {
        "title": "GitHub Changelog",
        "xml_url": "https://github.blog/changelog/feed/",
        "html_url": "https://github.blog/changelog/",
    },
    {
        "title": "OpenAI Skills",
        "xml_url": "https://github.com/openai/skills/commits/main.atom",
        "html_url": "https://github.com/openai/skills",
        "include_keywords": "hatch,pet,migrate-to-codex",
    },
)
OFFICIAL_AI_MAX_AGE_DAYS = 45
CURATED_AI_MEDIA_MAX_AGE_DAYS = 30
CURATED_AI_MEDIA_FEEDS: tuple[dict[str, Any], ...] = (
    {
        "title": "The Decoder AI News",
        "xml_url": "https://the-decoder.com/feed/",
        "html_url": "https://the-decoder.com/",
        "max_entries": 10,
    },
    {
        "title": "TechCrunch AI",
        "xml_url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "html_url": "https://techcrunch.com/category/artificial-intelligence/",
        "max_entries": 8,
    },
    {
        # The Verge's AI topic RSS endpoint is not currently public/stable;
        # keep the all-site RSS behind strict title-level AI filtering.
        "title": "The Verge",
        "xml_url": "https://www.theverge.com/rss/index.xml",
        "html_url": "https://www.theverge.com/ai-artificial-intelligence",
        "include_keywords": "ai,artificial intelligence,openai,anthropic,claude,chatgpt,gpt,gemini,llm,agent,copilot",
        "max_entries": 6,
        "strict_title_filter": True,
    },
    {
        "title": "MarkTechPost Research",
        "xml_url": "https://www.marktechpost.com/feed/",
        "html_url": "https://www.marktechpost.com/",
        "include_keywords": "paper,research,arxiv,benchmark,dataset,model,llm,agent,diffusion,transformer,multimodal,reasoning,inference,training,open-source",
        "max_entries": 6,
        "strict_title_filter": True,
        "research_only": True,
    },
    {
        "title": "VentureBeat AI",
        "xml_url": "https://venturebeat.com/category/ai/feed",
        "html_url": "https://venturebeat.com/category/ai/",
        "max_entries": 8,
    },
    {
        "title": "Artificial Intelligence News",
        "xml_url": "https://www.artificialintelligence-news.com/feed/",
        "html_url": "https://www.artificialintelligence-news.com/",
        "max_entries": 8,
    },
    {
        "title": "Claude Code Releases",
        "xml_url": "https://github.com/anthropics/claude-code/releases.atom",
        "html_url": "https://github.com/anthropics/claude-code/releases",
        "max_entries": 6,
    },
)
AIBREAKFAST_JINA_URL = "https://r.jina.ai/https://aibreakfast.beehiiv.com/"
AIHOT_ITEMS_API_URL = "https://aihot.virxact.com/api/public/items"
AIHOT_MIN_SCORE = 60
AIHOT_API_TAKE = 100
AIHOT_API_MAX_PAGES = 5
AIHOT_API_UA = f"{BROWSER_UA} aihot-skill/0.2.0 AI-News-Radar/0.7"
AIHOT_FEED_URL = "https://aihot.virxact.com/feed.xml"
AIHOT_FALLBACK_FEED_URLS = (
    "https://aihot.virxact.com/rss.xml",
    "https://aihot.virxact.com/feed",
    "https://aihot.virxact.com/feed/daily.xml",
)
FOLLOW_BUILDERS_FEED_BASE = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main"
HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_ALGOLIA_QUERIES: tuple[str, ...] = (
    "OpenAI",
    "Anthropic",
    "Claude Code",
    "Claude",
    "Gemini",
    "Google AI",
    "DeepSeek",
    "Qwen",
    "AI agent",
    "AI coding",
    "Codex",
    "Cursor",
    "MCP",
    "LLM",
    "GPT",
    "Sora",
    "Copilot",
    "Nvidia AI",
)
HN_ALGOLIA_KEYWORDS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "claude",
    "claude code",
    "codex",
    "cursor",
    "mcp",
    "gemini",
    "deepseek",
    "qwen",
    "llm",
    "gpt",
    "sora",
    "copilot",
    "agent",
    "ai coding",
    "benchmark",
    "eval",
    "paper",
    "model",
    "inference",
)
HN_ALGOLIA_HITS_PER_QUERY = 35
HN_ALGOLIA_MIN_KEYWORD_SCORE = 0.38
HN_ALGOLIA_MIN_COMMENTS = 2
HN_ALGOLIA_MIN_POINTS = 10
HN_ALGOLIA_QUERY_PAUSE_SECONDS = 0.1
BILIBILI_DYNAMIC_API_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/feed/space"
BILIBILI_DYNAMIC_FULL_API_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
BILIBILI_NAV_API_URL = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_DYNAMIC_DEFAULT_UID = "505301413"
BILIBILI_DYNAMIC_DEFAULT_SOURCE_NAME = "Koji杨远骋at十字路口"
BILIBILI_DYNAMIC_DEFAULT_ACCOUNTS = (
    (BILIBILI_DYNAMIC_DEFAULT_UID, BILIBILI_DYNAMIC_DEFAULT_SOURCE_NAME),
    ("316183842", "技术爬爬虾"),
)
BILIBILI_DYNAMIC_DEFAULT_MAX_ITEMS = 20
BILIBILI_DYNAMIC_DEFAULT_MAX_PAGES = 5
MEDIACRAWLER_DOUYIN_SITE_ID = "mediacrawler_douyin"
MEDIACRAWLER_DOUYIN_SITE_NAME = "MediaCrawler Douyin"
MEDIACRAWLER_XHS_SITE_ID = "mediacrawler_xhs"
MEDIACRAWLER_XHS_SITE_NAME = "MediaCrawler Xiaohongshu"
GITHUB_REPO_SUBSCRIPTION_SITE_ID = "github_foundation_sunshine_releases"
GITHUB_REPO_SUBSCRIPTION_SITE_NAME = "GitHub Foundation Sunshine"
GITHUB_REPO_SUBSCRIPTION_API_URL = "https://api.github.com/repos/AlkaidLab/foundation-sunshine/releases"
GITHUB_REPO_SUBSCRIPTION_HTML_URL = "https://github.com/AlkaidLab/foundation-sunshine"
GITHUB_REPO_SUBSCRIPTION_MAX_ITEMS = 5
MAOBIDAO_WECHAT_SITE_ID = "maobidao_wudaolu_backup"
MAOBIDAO_WECHAT_SITE_NAME = "Maobidao Wudaolu Backup"
MAOBIDAO_WECHAT_API_URL = "https://wudaolu.com/c/dav/7.json"
MAOBIDAO_WECHAT_HOME_URL = "https://wudaolu.com/c/dav/7"
MAOBIDAO_WECHAT_MAX_ITEMS = 2
WEWE_RSS_SITE_ID = "wewe_rss"
WEWE_RSS_SITE_NAME = "WeWe RSS"
WEWE_RSS_BASE_URL_DEFAULT = "http://127.0.0.1:4000"
WEWE_RSS_DEFAULT_MAX_ITEMS = 20
BILIBILI_WBI_MIXIN_KEY_ENC_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32,
    15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19,
    29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63,
    57, 62, 11, 36, 20, 34, 44, 52,
)
AGENTMAIL_API_BASE_DEFAULT = "https://api.agentmail.to"
AGENTMAIL_DIGEST_FILE = "email-digest.json"
AGENTMAIL_DEFAULT_LIMIT = 50
PAID_SOURCE_STATE_FILE = "paid-source-state.json"
PAID_SOURCE_DEFAULT_INTERVAL_HOURS = 24
PAID_SOURCE_DEFAULT_INTERVAL_HOURS_BY_PREFIX = {
    "SOCIALDATA": 12,
    "TIKHUB": 24,
}
PAID_SOURCE_MAX_INTERVAL_HOURS = 24 * 14
X_API_BASE_DEFAULT = "https://api.x.com"
X_API_POST_READ_COST_USD = 0.005
X_API_DEFAULT_QUERY = '(AI OR "artificial intelligence" OR "large language model" OR LLM) lang:en -is:retweet has:links'
X_API_DEFAULT_MAX_RESULTS = 20
X_API_MAX_QUERY_CHARS = 512
SOCIALDATA_API_BASE_DEFAULT = "https://api.socialdata.tools"
SOCIALDATA_TWEET_READ_COST_USD = 0.0002
SOCIALDATA_DEFAULT_QUERY = '(AI OR "artificial intelligence" OR LLM OR "large language model" OR 人工智能 OR 大模型 OR 大语言模型 OR AIGC OR 智能体 OR Agent) (lang:en OR lang:zh) -filter:retweets'
SOCIALDATA_DEFAULT_MAX_RESULTS = 20
SOCIALDATA_MAX_QUERY_CHARS = 512
# Curated X list "AI is cool, i guess" (owner @aiwarts). The list timeline pulls
# each member's own posts by identity, which is far higher-signal than the broad
# keyword search. No member is excluded by default; set SOCIALDATA_LIST_EXCLUDE
# (comma-separated handles) to drop specific accounts if needed.
SOCIALDATA_LIST_ID_DEFAULT = "1695376776867062037"
SOCIALDATA_LIST_DEFAULT_MAX_RESULTS = 50
SOCIALDATA_LIST_DEFAULT_EXCLUDE = ""
# Hard cap on list pagination so a heavily-filtered list can't page (and bill)
# without bound. Each page is a paid read.
SOCIALDATA_LIST_MAX_PAGES = 10
# Exact recency window for SocialData results, in days (search + list). Kept
# consistent with TikHub. Tweets older than this are dropped after fetch.
SOCIALDATA_RECENCY_DAYS = 4
# Keep only first-party posts; drop retweets and replies (conversational noise).
SOCIALDATA_LIST_ALLOWED_TYPES = frozenset({"tweet", "quote"})
TIKHUB_API_BASE_DEFAULT = "https://api.tikhub.io"
TIKHUB_DEFAULT_QUERY = "OpenAI,Claude,大模型,Agent,AI工具,人工智能,AI"
TIKHUB_DEFAULT_PLATFORMS = "douyin,xiaohongshu"
TIKHUB_DEFAULT_MAX_RESULTS = 20
TIKHUB_MAX_QUERY_CHARS = 256
TIKHUB_RESPONSE_SCAN_LIMIT = 100
CREATOR_HOT_WINDOW_DAYS = 7
CREATOR_FRESHNESS_BONUS_HOURS = 24
CREATOR_FRESHNESS_BONUS_POINTS = 15.0
CREATOR_SITE_IDS = frozenset({
    "tikhub_douyin",
    "tikhub_xiaohongshu",
    "bilibili_dynamic",
    MEDIACRAWLER_DOUYIN_SITE_ID,
    MEDIACRAWLER_XHS_SITE_ID,
    GITHUB_REPO_SUBSCRIPTION_SITE_ID,
    MAOBIDAO_WECHAT_SITE_ID,
    WEWE_RSS_SITE_ID,
})
SUBSCRIPTION_URL_MARKERS = (
    "bilibili.com",
    "youtube.com",
    "youtu.be",
    "douyin.com",
    "xiaohongshu.com",
    "wudaolu.com",
    "mp.weixin.qq.com",
)
SUBSCRIPTION_TEXT_MARKERS = (
    "bilibili",
    "youtube",
    "youtu.be",
    "douyin",
    "xiaohongshu",
    "b站",
    "油管",
    "抖音",
    "小红书",
    "公众号",
    "猫笔刀",
    "wewe",
)
SOURCE_SCOPE_ALL = "all_sources"
SOURCE_SCOPE_TESTED_CREATORS = "tested_creator_sources"
SOURCE_SCOPE_BILIBILI_ONLY = "bilibili_only"
SOURCE_SCOPE_CONFIGURED = "configured_sources"
DEPLOYED_SOURCE_SCOPE_DEFAULT = SOURCE_SCOPE_TESTED_CREATORS
TESTED_CREATOR_SOURCE_IDS = frozenset({
    "bilibili_dynamic",
    MEDIACRAWLER_DOUYIN_SITE_ID,
    MEDIACRAWLER_XHS_SITE_ID,
    GITHUB_REPO_SUBSCRIPTION_SITE_ID,
    MAOBIDAO_WECHAT_SITE_ID,
    WEWE_RSS_SITE_ID,
})
BUILTIN_COLLECT_SOURCE_IDS = frozenset({
    "official_ai",
    "curated_media",
    "aibreakfast",
    "followbuilders",
    "techurls",
    "buzzing",
    "iris",
    "bestblogs",
    "tophub",
    "zeli",
    "hackernews",
    "aihubtoday",
    "aibase",
    "aihot",
    "newsnow",
})
SOURCE_CONFIG_DEFAULT_FILENAMES = ("sources.config.json", "data/sources.config.json")
SOURCE_CONFIG_ID_SITE_IDS: dict[str, tuple[str, ...]] = {
    "official_ai_sources": ("official_ai",),
    "curated_ai_media_sources": ("curated_media",),
    "tikhub_social_sources": ("tikhub_douyin", "tikhub_xiaohongshu"),
    "github_foundation_sunshine": (GITHUB_REPO_SUBSCRIPTION_SITE_ID,),
    "wewe_rss_maobidao": (WEWE_RSS_SITE_ID,),
    "maobidao_wudaolu_backup": (MAOBIDAO_WECHAT_SITE_ID,),
}
SOURCE_CONFIG_TYPE_SITE_IDS: dict[str, tuple[str, ...]] = {
    "official_ai": ("official_ai",),
    "curated_media": ("curated_media",),
    "aibreakfast": ("aibreakfast",),
    "followbuilders": ("followbuilders",),
    "techurls": ("techurls",),
    "buzzing": ("buzzing",),
    "iris": ("iris",),
    "bestblogs": ("bestblogs",),
    "tophub": ("tophub",),
    "zeli": ("zeli",),
    "hackernews": ("hackernews",),
    "aihubtoday": ("aihubtoday",),
    "aibase": ("aibase",),
    "aihot": ("aihot",),
    "newsnow": ("newsnow",),
    "opmlrss": ("opmlrss",),
    "xapi": ("xapi",),
    "socialdata_x": ("socialdata_x",),
    "tikhub_douyin": ("tikhub_douyin", "tikhub_xiaohongshu"),
    "tikhub_xiaohongshu": ("tikhub_xiaohongshu",),
    "bilibili_dynamic": ("bilibili_dynamic",),
    "mediacrawler_douyin": (MEDIACRAWLER_DOUYIN_SITE_ID,),
    "mediacrawler_xhs": (MEDIACRAWLER_XHS_SITE_ID,),
    "github_release": (GITHUB_REPO_SUBSCRIPTION_SITE_ID,),
    "wewe_rss": (WEWE_RSS_SITE_ID,),
}
# --- TikHub search ranking / time-window tuning (edit here, no env var needed) ---
# Exact recency window for TikHub results, in days. Douyin/Xiaohongshu search
# only expose coarse buckets (不限/一天内/一周内/半年内), so we ask the API for
# 一周内 and then enforce the exact current-week window in code.
TIKHUB_RECENCY_DAYS = 7              # keep only current-week posts
# Douyin fetch_general_search_v2 enums (standard Douyin search filter):
#   sort_type:    0=综合, 1=最多点赞(most likes), 2=最新
#   publish_time: 0=不限, 1=一天内, 7=一周内, 180=半年内
TIKHUB_DOUYIN_SORT_TYPE = "1"        # 最多点赞 / most likes
TIKHUB_DOUYIN_PUBLISH_TIME = "7"     # 一周内; real cap = TIKHUB_RECENCY_DAYS
# Xiaohongshu search. app_v2 uses the app's filter labels; sort uses the
# popularity/time/general tokens (web_v3 already takes "time_descending").
#   sort:        general(综合) / time_descending(最新) / popularity_descending(最多点赞/最热)
#   note_type:   "不限"(app_v2, all) ; web_v3 uses 0 for "all"
#   time_filter: "不限" / "一天内" / "一周内" / "半年内"
TIKHUB_XHS_SORT = "popularity_descending"  # 最多点赞 / most likes
TIKHUB_XHS_NOTE_TYPE = "不限"               # all note types
TIKHUB_XHS_TIME_FILTER = "一周内"           # 一周内; real cap = TIKHUB_RECENCY_DAYS


@dataclass
class RawItem:
    site_id: str
    site_name: str
    source: str
    title: str
    url: str
    published_at: datetime | None
    meta: dict[str, Any]


PUBLIC_RAW_META_FIELDS: tuple[str, ...] = (
    "aihot_score",
    "aihot_category",
    "aihot_selected",
    "creator_metrics",
    "search_surface",
    "summary",
)


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        dt = dtparser.parse(dt_str)
    except Exception:
        return None
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def normalize_url(raw_url: str) -> str:
    try:
        parsed = urlparse(raw_url.strip())
        if not parsed.scheme:
            return raw_url.strip()
        query = []
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            lk = k.lower()
            if lk.startswith("utm_"):
                continue
            if lk in DROP_QUERY_PARAMS:
                continue
            query.append((k, v))
        parsed = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            fragment="",
            query=urlencode(query, doseq=True),
        )
        normalized = urlunparse(parsed)
        return normalized.rstrip("/")
    except Exception:
        return raw_url.strip()


def host_of_url(raw_url: str) -> str:
    try:
        return urlparse(raw_url).netloc.lower()
    except Exception:
        return ""


def first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        s = str(value).strip()
        if s:
            return s
    return ""


def maybe_fix_mojibake(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return s
    # Common mojibake signature from UTF-8 bytes decoded as Latin-1.
    if re.search(r"[Ãâåèæïð]|[\x80-\x9f]|æ|ç|å|é", s) is None:
        return s
    for enc in ("latin1", "cp1252"):
        try:
            fixed = s.encode(enc).decode("utf-8")
            if fixed and fixed != s:
                return fixed
        except Exception:
            continue
    return s


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def is_mostly_english(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if has_cjk(s):
        return False
    letters = re.findall(r"[A-Za-z]", s)
    return len(letters) >= max(6, len(s) // 4)


def parse_feed_entries_via_xml(feed_xml: bytes) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    try:
        root = ET.fromstring(feed_xml)
    except Exception:
        return out

    for tag in (".//item", ".//{*}item", ".//entry", ".//{*}entry"):
        for node in root.findall(tag):
            title = (
                node.findtext("title")
                or node.findtext("{*}title")
                or ""
            ).strip()
            link = ""
            link_node = node.find("link")
            if link_node is None:
                link_node = node.find("{*}link")
            if link_node is not None:
                link = (link_node.get("href") or link_node.text or "").strip()
            if not link:
                link = (node.findtext("{*}link") or node.findtext("link") or "").strip()
            published = (
                node.findtext("pubDate")
                or node.findtext("{*}pubDate")
                or node.findtext("published")
                or node.findtext("{*}published")
                or node.findtext("updated")
                or node.findtext("{*}updated")
            )
            if title and link:
                key = (title, link)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"title": title, "link": link, "published": published})
    return out


def make_item_id(site_id: str, source: str, title: str, url: str) -> str:
    key = "||".join(
        [
            site_id.strip().lower(),
            source.strip().lower(),
            title.strip().lower(),
            normalize_url(url),
        ]
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def parse_unix_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        n = float(value)
    except Exception:
        return None
    if n > 10_000_000_000:
        n /= 1000.0
    try:
        return datetime.fromtimestamp(n, tz=UTC)
    except Exception:
        return None


def parse_relative_time_zh(text: str, now: datetime) -> datetime | None:
    text = (text or "").strip()
    if not text:
        return None

    m = re.search(r"(\d+)\s*分钟前", text)
    if m:
        return now - timedelta(minutes=int(m.group(1)))

    m = re.search(r"(\d+)\s*小时前", text)
    if m:
        return now - timedelta(hours=int(m.group(1)))

    m = re.search(r"(\d+)\s*天前", text)
    if m:
        return now - timedelta(days=int(m.group(1)))

    if "刚刚" in text:
        return now

    if "昨天" in text:
        return now - timedelta(days=1)

    m = re.fullmatch(r"(?:今天)?\s*(\d{1,2}):(\d{2})", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > now + timedelta(minutes=5):
            candidate -= timedelta(days=1)
        return candidate

    m = re.fullmatch(r"昨天\s*(\d{1,2}):(\d{2})", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        return (now - timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)

    m = re.fullmatch(r"(?:\d{4}年\s*)?(\d{1,2})月(\d{1,2})日", text)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        year = now.year
        try:
            candidate = datetime(year, month, day, tzinfo=UTC)
            if candidate > now + timedelta(days=2):
                candidate = datetime(year - 1, month, day, tzinfo=UTC)
            return candidate
        except Exception:
            return None

    return None


def parse_date_any(value: Any, now: datetime) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.astimezone(UTC)

    if isinstance(value, (int, float)):
        return parse_unix_timestamp(value)

    s = str(value).strip()
    if not s:
        return None

    if s.startswith("$D"):
        s = s[2:]

    if re.fullmatch(r"\d{12,}", s):
        return parse_unix_timestamp(int(s))

    if re.fullmatch(r"\d{9,11}", s):
        return parse_unix_timestamp(int(s))

    dt = parse_relative_time_zh(s, now)
    if dt:
        return dt

    # TechURLs format: 2026-02-19 11:54:21AM UTC
    m = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}:\d{2}[AP]M)\s+UTC", s)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%Y-%m-%d %I:%M:%S%p")
            return dt.replace(tzinfo=UTC)
        except Exception:
            pass

    try:
        dt = dtparser.parse(s, tzinfos={"UT": 0, "UTC": 0, "GMT": 0})
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def apply_public_raw_meta(record: dict[str, Any], raw: RawItem) -> None:
    """Promote safe source metadata needed by public scoring and UI ranking."""
    meta = raw.meta if isinstance(raw.meta, dict) else {}
    for key in PUBLIC_RAW_META_FIELDS:
        if key in meta and meta.get(key) is not None:
            record[key] = sanitize_public_value(meta.get(key))


def decode_escaped_json(raw: str) -> dict[str, Any] | None:
    s = raw.replace('\\"', '"').replace("\\/", "/")
    try:
        return json.loads(s)
    except Exception:
        return None


def extract_waytoagi_history_url(root_html: str) -> str:
    pattern = r'\{\\"id\\":\\"[^\"]+\\",\\"type\\":\\"mention_doc\\",\\"data\\":\{[^\}]+\}\}'
    for raw in re.findall(pattern, root_html):
        obj = decode_escaped_json(raw)
        if not obj:
            continue
        data = obj.get("data", {})
        title = str(data.get("title") or "")
        if "历史更新" in title or "更新日志" in title:
            raw_url = str(data.get("raw_url") or "").strip()
            if raw_url:
                return raw_url
    return WAYTOAGI_HISTORY_FALLBACK


def extract_feishu_client_vars(page_html: str) -> dict[str, Any]:
    marker = "window.DATA = Object.assign({}, window.DATA, { clientVars: Object("
    idx = page_html.find(marker)
    if idx == -1:
        raise ValueError("Cannot locate Feishu clientVars marker")

    start = idx + len(marker)
    depth = 1
    in_str = False
    escaped = False
    end = None

    for i, ch in enumerate(page_html[start:], start):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end is None:
        raise ValueError("Cannot parse Feishu clientVars payload")

    payload = page_html[start:end]
    return json.loads(payload)


def block_text(block_data: dict[str, Any]) -> str:
    text_obj = block_data.get("text", {}) if isinstance(block_data, dict) else {}
    initial = text_obj.get("initialAttributedTexts", {}).get("text", {}) if isinstance(text_obj, dict) else {}
    if not isinstance(initial, dict):
        return ""

    def key_int(k: Any) -> int:
        try:
            return int(k)
        except Exception:
            return 0

    return "".join(str(v) for k, v in sorted(initial.items(), key=lambda kv: key_int(kv[0]))).strip()


def clean_update_title(text: str) -> str:
    text = text.replace("《 》", "").replace("《》", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_ym_heading(text: str) -> tuple[int, int] | None:
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_md_heading(text: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def infer_shanghai_year_for_month_day(now_sh: datetime, month: int, day: int) -> int | None:
    year = now_sh.year
    try:
        candidate = date(year, month, day)
    except Exception:
        return None
    if candidate > (now_sh.date() + timedelta(days=2)):
        year -= 1
    return year


def extract_waytoagi_recent_updates_from_block_map(
    block_map: dict[str, Any],
    now_sh: datetime,
    page_url: str,
) -> list[dict[str, Any]]:
    if not isinstance(block_map, dict) or not block_map:
        return []

    ym_by_heading2: dict[str, tuple[int, int]] = {}
    near_log_parent_ids: set[str] = set()

    for bid, block in block_map.items():
        bd = block.get("data", {})
        btype = bd.get("type")
        if btype not in {"heading1", "heading2", "heading3"}:
            continue
        heading_text = block_text(bd)
        if "近7日更新日志" in heading_text or "近 7 日更新日志" in heading_text:
            parent_id = str(bd.get("parent_id") or "").strip()
            if parent_id:
                near_log_parent_ids.add(parent_id)

    heading3_dates: dict[str, date] = {}

    for bid, block in block_map.items():
        bd = block.get("data", {})
        if bd.get("type") != "heading2":
            continue
        ym = parse_ym_heading(block_text(bd))
        if ym:
            ym_by_heading2[bid] = ym

    for bid, block in block_map.items():
        bd = block.get("data", {})
        if bd.get("type") != "heading3":
            continue
        md = parse_md_heading(block_text(bd))
        if not md:
            continue
        month, day = md
        parent = bd.get("parent_id")
        if near_log_parent_ids and parent not in near_log_parent_ids:
            continue
        year = ym_by_heading2.get(parent, (now_sh.year, month))[0]
        inferred = infer_shanghai_year_for_month_day(now_sh, month, day)
        if inferred is not None:
            year = inferred
        try:
            heading3_dates[bid] = date(year, month, day)
        except Exception:
            continue

    parent_map: dict[str, str] = {}
    for bid, block in block_map.items():
        bd = block.get("data", {})
        parent = str(bd.get("parent_id") or "").strip()
        if parent:
            parent_map[bid] = parent

    def nearest_heading_date(block_id: str) -> date | None:
        cur = parent_map.get(block_id)
        hops = 0
        while cur and hops < 20:
            if cur in heading3_dates:
                return heading3_dates[cur]
            cur = parent_map.get(cur)
            hops += 1
        return None

    updates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for bid, block in block_map.items():
        bd = block.get("data", {})
        if bd.get("type") not in {"bullet", "text", "todo", "ordered"}:
            continue

        day = nearest_heading_date(bid)
        if not day:
            continue
        title = clean_update_title(block_text(bd))
        if not title:
            continue
        key = (day.isoformat(), title)
        if key in seen:
            continue
        seen.add(key)
        updates.append({"date": day.isoformat(), "title": title, "url": page_url})

    return updates


def fetch_waytoagi_recent_7d(session: requests.Session, now_utc: datetime, root_url: str) -> dict[str, Any]:
    now_sh = now_utc.astimezone(SH_TZ)
    root_html = session.get(root_url, timeout=30).text
    history_url = extract_waytoagi_history_url(root_html)

    root_client_vars = extract_feishu_client_vars(root_html)
    root_block_map = root_client_vars.get("data", {}).get("block_map", {})
    updates: list[dict[str, Any]] = extract_waytoagi_recent_updates_from_block_map(root_block_map, now_sh, root_url)

    if history_url and history_url != root_url:
        try:
            history_html = session.get(history_url, timeout=30).text
            history_client_vars = extract_feishu_client_vars(history_html)
            history_block_map = history_client_vars.get("data", {}).get("block_map", {})
            updates.extend(
                extract_waytoagi_recent_updates_from_block_map(history_block_map, now_sh, history_url)
            )
        except Exception:
            pass

    dedup_updates: dict[tuple[str, str], dict[str, Any]] = {}
    for item in updates:
        key = (str(item.get("date") or ""), str(item.get("title") or ""))
        if key[0] and key[1] and key not in dedup_updates:
            dedup_updates[key] = item

    start_date = now_sh.date() - timedelta(days=6)
    end_date = now_sh.date()
    recent = [
        u
        for u in dedup_updates.values()
        if start_date <= date.fromisoformat(str(u.get("date") or "1970-01-01")) <= end_date
    ]
    recent.sort(key=lambda x: (x["date"], x["title"]), reverse=True)
    latest_date = recent[0]["date"] if recent else None
    updates_today = [u for u in recent if u.get("date") == latest_date] if latest_date else []

    warning = "近7日未解析到更新条目" if not recent else None
    return {
        "generated_at": iso(now_utc),
        "timezone": "Asia/Shanghai",
        "root_url": root_url,
        "history_url": history_url,
        "window_days": 7,
        "latest_date": latest_date,
        "count_today": len(updates_today),
        "updates_today": updates_today,
        "count_7d": len(recent),
        "updates_7d": recent,
        "warning": warning,
        "has_error": False,
        "error": None,
    }


def waytoagi_updates_to_raw_items(payload: dict[str, Any], now: datetime) -> list[RawItem]:
    updates = payload.get("updates_today")
    if not isinstance(updates, list):
        updates = []
    out: list[RawItem] = []
    for update in updates:
        if not isinstance(update, dict):
            continue
        title = str(update.get("title") or "").strip()
        url = str(update.get("url") or payload.get("root_url") or WAYTOAGI_DEFAULT).strip()
        if not title or not url:
            continue
        update_date = str(update.get("date") or payload.get("latest_date") or "").strip()
        source = f"社区更新 · {update_date}" if update_date else "社区更新"
        out.append(
            RawItem(
                site_id="waytoagi",
                site_name="WaytoAGI",
                source=source,
                title=title,
                url=url,
                # WaytoAGI update logs only expose a date. Treat currently
                # visible latest-date entries as fresh community signals for
                # the 24h board while the 7d payload keeps exact date context.
                published_at=now,
                meta={"summary": title},
            )
        )
    return out


def create_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    return session


def extract_next_f_merged(html: str) -> str:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    if not chunks:
        return ""
    merged = "".join(chunks)
    try:
        return bytes(merged, "utf-8").decode("unicode_escape")
    except Exception:
        return merged


def extract_balanced_json(decoded: str, key: str) -> Any:
    idx = decoded.find(key)
    if idx == -1:
        raise ValueError(f"Key not found: {key}")

    start = idx + len(key)
    while start < len(decoded) and decoded[start] != ":":
        start += 1
    start += 1
    while start < len(decoded) and decoded[start] not in "[{":
        start += 1

    open_ch = decoded[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    end = None

    for i, ch in enumerate(decoded[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

    if end is None:
        raise ValueError(f"Cannot parse JSON block for key: {key}")

    snippet = decoded[start:end]
    snippet = snippet.replace("$undefined", "null")
    snippet = re.sub(r'"\$D([^\"]+)"', r'"\1"', snippet)
    return json.loads(snippet)


def extract_next_data_payload(html: str) -> dict[str, Any] | None:
    m = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>\s*(\{.*?\})\s*</script>',
        html,
        re.S,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def fetch_techurls(session: requests.Session, now: datetime) -> list[RawItem]:
    site_id = "techurls"
    site_name = "TechURLs"
    r = session.get("https://techurls.com/", timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out: list[RawItem] = []
    for block in soup.select("div.publisher-block"):
        primary = (
            block.select_one(".publisher-text .primary").get_text(strip=True)
            if block.select_one(".publisher-text .primary")
            else block.get("data-publisher", "unknown")
        )
        secondary = (
            block.select_one(".publisher-text .secondary").get_text(strip=True)
            if block.select_one(".publisher-text .secondary")
            else ""
        )
        source = f"{primary} · {secondary}" if secondary and secondary != primary else primary

        for link_row in block.select("div.publisher-link"):
            a = link_row.select_one("a.article-link")
            if not a or not a.get("href"):
                continue
            title = a.get_text(" ", strip=True)
            url = a["href"].strip()

            time_hint = ""
            aside = link_row.select_one(".aside .text")
            if aside:
                time_hint = aside.get("title", "") or aside.get_text(" ", strip=True)

            published = parse_date_any(time_hint, now)
            out.append(
                RawItem(
                    site_id=site_id,
                    site_name=site_name,
                    source=source,
                    title=title,
                    url=url,
                    published_at=published,
                    meta={"time_hint": time_hint},
                )
            )

    return out


def fetch_buzzing(session: requests.Session, now: datetime) -> list[RawItem]:
    site_id = "buzzing"
    site_name = "Buzzing"
    r = session.get("https://www.buzzing.cc/feed.json", timeout=30)
    r.raise_for_status()
    payload = r.json()
    items = payload.get("items", [])

    out: list[RawItem] = []
    for it in items:
        title = (it.get("title") or "").strip()
        url = (it.get("url") or "").strip()
        if not title or not url:
            continue
        source = first_non_empty(
            it.get("source"),
            it.get("site_name"),
            it.get("channel"),
            it.get("category"),
            host_of_url(url),
            site_name,
        )
        published = parse_date_any(it.get("date_published") or it.get("date_modified"), now)
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source=source,
                title=title,
                url=url,
                published_at=published,
                meta={"raw": {k: it.get(k) for k in ("source", "site_name", "channel", "category")}},
            )
        )
    return out


def fetch_iris(session: requests.Session, now: datetime) -> list[RawItem]:
    site_id = "iris"
    site_name = "Info Flow"

    r = session.get("https://iris.findtruman.io/web/info_flow", timeout=30)
    r.raise_for_status()
    html = r.text

    m = re.search(r"const\s+feeds\s*=\s*\[(.*?)\]\s*;", html, re.S)
    if not m:
        return []

    section = m.group(1)
    feeds = re.findall(
        r"\{\s*name:\s*'([^']+)'\s*,\s*url:\s*'([^']+)'\s*\}",
        section,
        re.S,
    )

    out: list[RawItem] = []
    for feed_name, feed_url in feeds:
        try:
            if feedparser is not None:
                parsed = feedparser.parse(feed_url)
                source_name = str(feed_name or getattr(parsed, "feed", {}).get("title") or "Iris Feed")
                for entry in parsed.entries:
                    title = str(entry.get("title", "")).strip()
                    url = str(entry.get("link", "")).strip()
                    if not title or not url:
                        continue
                    published = (
                        parse_date_any(entry.get("published"), now)
                        or parse_date_any(entry.get("updated"), now)
                        or parse_date_any(entry.get("pubDate"), now)
                    )
                    out.append(
                        RawItem(
                            site_id=site_id,
                            site_name=site_name,
                            source=source_name,
                            title=title,
                            url=url,
                            published_at=published,
                            meta={"feed_url": feed_url},
                        )
                    )
                continue

            feed_resp = session.get(feed_url, timeout=30)
            feed_resp.raise_for_status()
            entries = parse_feed_entries_via_xml(feed_resp.content)
            source_name = str(feed_name or "Iris Feed")
            for entry in entries:
                out.append(
                    RawItem(
                        site_id=site_id,
                        site_name=site_name,
                        source=source_name,
                        title=entry["title"],
                        url=entry["link"],
                        published_at=parse_date_any(entry.get("published"), now),
                        meta={"feed_url": feed_url},
                    )
                )
        except Exception:
            # Skip blocked/broken sub feeds and keep remaining feeds.
            continue
    return out


def fetch_bestblogs(session: requests.Session, now: datetime) -> list[RawItem]:
    site_id = "bestblogs"
    site_name = "BestBlogs"

    api = "https://api.bestblogs.dev/api/newsletter/list"
    out: list[RawItem] = []
    seen: set[str] = set()

    try:
        current_page = 1
        page_count = 1

        while current_page <= page_count and current_page <= 12:
            payload = {
                "currentPage": current_page,
                "pageSize": 20,
                "userLanguage": "en",
            }
            r = session.post(api, json=payload, timeout=30)
            r.raise_for_status()
            body = r.json()
            data = body.get("data", {})
            page_count = int(data.get("pageCount", 1) or 1)

            for issue in data.get("dataList", []):
                issue_id = str(issue.get("id", "")).strip()
                title = str(issue.get("title", "")).strip()
                if not issue_id or not title:
                    continue
                url = f"https://www.bestblogs.dev/en/newsletter#{issue_id}"
                if url in seen:
                    continue
                seen.add(url)

                published = parse_unix_timestamp(issue.get("createdTimestamp"))
                out.append(
                    RawItem(
                        site_id=site_id,
                        site_name=site_name,
                        source="Weekly Newsletter",
                        title=title,
                        url=url,
                        published_at=published,
                        meta={
                            "issue_id": issue_id,
                            "article_count": issue.get("articleCount"),
                        },
                    )
                )
            current_page += 1
    except Exception:
        pass

    if out:
        return out

    r = session.get("https://www.bestblogs.dev/en/newsletter", timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    for a in soup.select("a[href*='/newsletter']"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        url = href if href.startswith("http") else urljoin("https://www.bestblogs.dev", href)
        title = a.get_text(" ", strip=True)
        if len(title) < 8:
            continue
        if url in seen:
            continue
        seen.add(url)
        dt = None
        time_tag = a.select_one("time")
        if time_tag:
            dt = parse_date_any(time_tag.get("datetime") or time_tag.get_text(" ", strip=True), now)
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source="Weekly Newsletter",
                title=title,
                url=url,
                published_at=dt,
                meta={},
            )
        )

    return out


def fetch_tophub(session: requests.Session, now: datetime) -> list[RawItem]:
    site_id = "tophub"
    site_name = "TopHub"

    r = session.get("https://tophub.today/", timeout=30)
    r.raise_for_status()
    html = r.content.decode("utf-8", errors="replace")
    if "�" in html:
        for enc in ("gb18030", "utf-8"):
            try:
                candidate = r.content.decode(enc, errors="replace")
                if candidate.count("�") < html.count("�"):
                    html = candidate
            except Exception:
                continue
    soup = BeautifulSoup(html, "html.parser")

    out: list[RawItem] = []
    for block in soup.select(".cc-cd"):
        source_name_tag = block.select_one(".cc-cd-lb span")
        board_tag = block.select_one(".cc-cd-sb-st")
        source_name = source_name_tag.get_text(" ", strip=True) if source_name_tag else "TopHub"
        board_name = board_tag.get_text(" ", strip=True) if board_tag else ""
        source_name = maybe_fix_mojibake(source_name)
        board_name = maybe_fix_mojibake(board_name)
        source = f"{source_name} · {board_name}" if board_name else source_name

        for a in block.select(".cc-cd-cb-l a"):
            href = a.get("href", "").strip()
            row = a.select_one(".cc-cd-cb-ll")
            title_tag = row.select_one(".t") if row else None
            metric_tag = row.select_one(".e") if row else None

            title = (
                title_tag.get_text(" ", strip=True)
                if title_tag
                else a.get_text(" ", strip=True)
            )
            title = maybe_fix_mojibake(title)
            if not title or not href:
                continue

            full_url = href if href.startswith("http") else urljoin("https://tophub.today", href)
            row_text = row.get_text(" ", strip=True) if row else title
            published = parse_relative_time_zh(row_text, now)

            out.append(
                RawItem(
                    site_id=site_id,
                    site_name=site_name,
                    source=source,
                    title=title,
                    url=full_url,
                    published_at=published,
                    meta={"metric": metric_tag.get_text(" ", strip=True) if metric_tag else ""},
                )
            )

    return out


def fetch_zeli(session: requests.Session, now: datetime) -> list[RawItem]:
    site_id = "zeli"
    site_name = "Zeli"
    out: list[RawItem] = []

    url = "https://zeli.app/api/hacker-news?type=hot24h"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    body = r.json()
    posts = body.get("posts", [])
    for p in posts:
        title = str(p.get("title", "")).strip()
        link = str(p.get("url", "")).strip()
        if not title or not link:
            continue
        published = parse_unix_timestamp(p.get("time")) or now
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source="Hacker News · 24h最热",
                title=title,
                url=link,
                published_at=published,
                meta={"hn_id": p.get("id")},
            )
        )

    return out


def hn_algolia_keyword_score(title: str) -> float:
    blob = title.lower()
    hits = 0
    for keyword in HN_ALGOLIA_KEYWORDS:
        if re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", blob):
            hits += 1
    return min(1.0, hits / 3)


def parse_hn_algolia_hits(payloads: list[tuple[str, dict[str, Any]]], now: datetime) -> list[RawItem]:
    seen_ids: set[str] = set()
    out: list[RawItem] = []

    for query, payload in payloads:
        hits = payload.get("hits")
        if not isinstance(hits, list):
            continue

        for hit in hits:
            if not isinstance(hit, dict):
                continue
            object_id = str(hit.get("objectID") or "").strip()
            if not object_id or object_id in seen_ids:
                continue
            seen_ids.add(object_id)

            title = maybe_fix_mojibake(str(first_non_empty(hit.get("title"), hit.get("story_title"))))
            if not title or hn_algolia_keyword_score(title) < HN_ALGOLIA_MIN_KEYWORD_SCORE:
                continue

            try:
                comments = int(hit.get("num_comments") or 0)
            except Exception:
                comments = 0
            try:
                points = int(hit.get("points") or 0)
            except Exception:
                points = 0
            if comments < HN_ALGOLIA_MIN_COMMENTS and points < HN_ALGOLIA_MIN_POINTS:
                continue

            item_url = str(hit.get("url") or "").strip()
            hn_url = f"https://news.ycombinator.com/item?id={object_id}"
            published = parse_date_any(hit.get("created_at"), now) or parse_unix_timestamp(hit.get("created_at_i")) or now

            out.append(
                RawItem(
                    site_id="hackernews",
                    site_name="Hacker News",
                    source="HN Algolia · AI 24h",
                    title=title,
                    url=item_url or hn_url,
                    published_at=published,
                    meta={
                        "hn_id": object_id,
                        "hn_url": hn_url,
                        "hn_query": query,
                        "hn_comments": comments,
                        "hn_points": points,
                    },
                )
            )

    out.sort(
        key=lambda item: (
            int(item.meta.get("hn_comments") or 0),
            int(item.meta.get("hn_points") or 0),
            item.published_at or datetime.min.replace(tzinfo=UTC),
        ),
        reverse=True,
    )
    return out


def fetch_hacker_news_algolia(session: requests.Session, now: datetime) -> list[RawItem]:
    start_ts = int((now - timedelta(hours=24)).timestamp())
    payloads: list[tuple[str, dict[str, Any]]] = []
    errors: list[str] = []

    for query in HN_ALGOLIA_QUERIES:
        try:
            response = session.get(
                HN_ALGOLIA_URL,
                params={
                    "query": query,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{start_ts}",
                    "hitsPerPage": HN_ALGOLIA_HITS_PER_QUERY,
                },
                headers={"Accept": "application/json"},
                timeout=16,
            )
            response.raise_for_status()
            payloads.append((query, response.json()))
        except Exception as exc:
            errors.append(f"{query}: {exc}")
        time.sleep(HN_ALGOLIA_QUERY_PAUSE_SECONDS)

    if not payloads and errors:
        raise ValueError(f"HN Algolia queries failed: {'; '.join(errors[:3])}")

    return parse_hn_algolia_hits(payloads, now)


def parse_anthropic_news_items(page_html: str, now: datetime) -> list[RawItem]:
    site_id = "official_ai"
    site_name = "Official AI Updates"
    soup = BeautifulSoup(page_html, "html.parser")
    out: list[RawItem] = []
    seen: set[str] = set()

    for a in soup.select('a[href^="/news/"]'):
        href = str(a.get("href") or "").strip()
        if not href or href == "/news/" or href == "/news":
            continue

        title_tag = a.select_one("h1, h2, h3, h4")
        title = title_tag.get_text(" ", strip=True) if title_tag else ""
        title = maybe_fix_mojibake(title)
        if not title or title.lower() == "news":
            continue

        url = urljoin("https://www.anthropic.com", href)
        if url in seen:
            continue
        seen.add(url)

        time_tag = a.select_one("time")
        published = None
        if time_tag:
            published = parse_date_any(time_tag.get("datetime") or time_tag.get_text(" ", strip=True), now)
        if not published:
            continue
        if now and published < now - timedelta(days=OFFICIAL_AI_MAX_AGE_DAYS):
            continue

        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source="Anthropic News",
                title=title,
                url=url,
                published_at=published,
                meta={"provider": "Anthropic"},
            )
        )

    return out


def parse_openai_codex_changelog_items(page_html: str, now: datetime) -> list[RawItem]:
    site_id = "official_ai"
    site_name = "Official AI Updates"
    soup = BeautifulSoup(page_html, "html.parser")
    out: list[RawItem] = []
    seen: set[str] = set()

    for node in soup.select("#codex-changelog-content li[id], li[id]"):
        item_id = str(node.get("id") or "").strip()
        if not item_id or item_id in seen:
            continue

        time_tag = node.select_one("time")
        title_tag = node.select_one("h3")
        if not time_tag or not title_tag:
            continue

        title = maybe_fix_mojibake(title_tag.get_text(" ", strip=True))
        published = parse_date_any(time_tag.get("datetime") or time_tag.get_text(" ", strip=True), now)
        if not title or not published:
            continue
        if now and published < now - timedelta(days=OFFICIAL_AI_MAX_AGE_DAYS):
            continue

        seen.add(item_id)
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source="OpenAI Codex Changelog",
                title=title,
                url=f"https://developers.openai.com/codex/changelog#{item_id}",
                published_at=published,
                meta={"provider": "OpenAI"},
            )
        )

    return out


def fetch_feed_as_official_items(
    session: requests.Session,
    feed: dict[str, str],
    now: datetime,
) -> list[RawItem]:
    site_id = "official_ai"
    site_name = "Official AI Updates"
    feed_url = feed["xml_url"]
    feed_title = feed["title"]

    resp = session.get(
        feed_url,
        timeout=20,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    resp.raise_for_status()

    entries: list[dict[str, Any]]
    if feedparser is not None:
        parsed = feedparser.parse(resp.content)
        entries = list(parsed.entries)
    else:
        entries = parse_feed_entries_via_xml(resp.content)

    out: list[RawItem] = []
    include_keywords = [
        keyword.strip().lower()
        for keyword in str(feed.get("include_keywords") or "").split(",")
        if keyword.strip()
    ]
    for entry in entries:
        title = str(entry.get("title", "")).strip()
        link = str(entry.get("link", "")).strip()
        if not title or not link:
            continue
        if include_keywords:
            haystack = f"{title} {link}".lower()
            if not any(keyword in haystack for keyword in include_keywords):
                continue
        published = (
            parse_date_any(entry.get("published"), now)
            or parse_date_any(entry.get("updated"), now)
            or parse_date_any(entry.get("pubDate"), now)
        )
        if not published:
            continue
        if published < now - timedelta(days=OFFICIAL_AI_MAX_AGE_DAYS):
            continue

        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source=feed_title,
                title=maybe_fix_mojibake(title),
                url=link,
                published_at=published,
                meta={
                    "feed_url": feed_url,
                    "feed_home": feed.get("html_url") or "",
                },
            )
        )

    return out


def feed_entry_title_link_published(entry: dict[str, Any], now: datetime) -> tuple[str, str, datetime | None]:
    title = maybe_fix_mojibake(str(entry.get("title", "")).strip())
    link = str(entry.get("link", "")).strip()
    published = (
        parse_date_any(entry.get("published"), now)
        or parse_date_any(entry.get("updated"), now)
        or parse_date_any(entry.get("pubDate"), now)
    )
    return title, link, published


def feed_keywords(feed: dict[str, Any]) -> list[str]:
    return [
        keyword.strip().lower()
        for keyword in str(feed.get("include_keywords") or "").split(",")
        if keyword.strip()
    ]


def curated_feed_entry_allowed(feed: dict[str, Any], title: str, link: str) -> bool:
    include_keywords = feed_keywords(feed)
    if not include_keywords:
        return True
    haystack = title.lower()
    if not feed.get("strict_title_filter"):
        haystack = f"{haystack} {link.lower()} {feed.get('title', '').lower()}"
    return any(keyword in haystack for keyword in include_keywords)


def parse_curated_ai_media_feed_items(
    feed_content: bytes,
    feed: dict[str, Any],
    now: datetime,
) -> list[RawItem]:
    site_id = "curated_media"
    site_name = "Curated Media"
    feed_url = str(feed["xml_url"])
    feed_title = str(feed["title"])

    if feedparser is not None:
        parsed = feedparser.parse(feed_content)
        entries = list(parsed.entries)
    else:
        entries = parse_feed_entries_via_xml(feed_content)

    out: list[RawItem] = []
    seen_urls: set[str] = set()
    max_entries = max(1, int(feed.get("max_entries") or 8))
    for entry in entries:
        title, link, published = feed_entry_title_link_published(entry, now)
        if not title or not link or not published:
            continue
        if published < now - timedelta(days=CURATED_AI_MEDIA_MAX_AGE_DAYS):
            continue
        if not curated_feed_entry_allowed(feed, title, link):
            continue
        normalized_url = normalize_url(link)
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source=feed_title,
                title=title,
                url=link,
                published_at=published,
                meta={
                    "feed_url": feed_url,
                    "feed_home": feed.get("html_url") or "",
                    "research_only": bool(feed.get("research_only")),
                    "strict_title_filter": bool(feed.get("strict_title_filter")),
                },
            )
        )
        if len(out) >= max_entries:
            break

    return out


def fetch_curated_ai_media(session: requests.Session, now: datetime) -> list[RawItem]:
    out: list[RawItem] = []
    failures: list[str] = []

    for feed in CURATED_AI_MEDIA_FEEDS:
        try:
            resp = session.get(
                str(feed["xml_url"]),
                timeout=20,
                headers={
                    "User-Agent": BROWSER_UA,
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
                },
            )
            resp.raise_for_status()
            out.extend(parse_curated_ai_media_feed_items(resp.content, feed, now))
        except Exception:
            failures.append(str(feed.get("title") or feed.get("xml_url") or "unknown"))

    if not out and failures:
        raise ValueError(f"No curated media items parsed; failed feeds: {', '.join(failures[:4])}")
    return out


def fetch_official_ai_updates(session: requests.Session, now: datetime) -> list[RawItem]:
    out: list[RawItem] = []

    for feed in OFFICIAL_AI_FEEDS:
        try:
            out.extend(fetch_feed_as_official_items(session, feed, now))
        except Exception:
            continue

    try:
        r = session.get("https://www.anthropic.com/news", timeout=20)
        r.raise_for_status()
        out.extend(parse_anthropic_news_items(r.text, now))
    except Exception:
        pass

    try:
        r = session.get("https://developers.openai.com/codex/changelog", timeout=20)
        r.raise_for_status()
        out.extend(parse_openai_codex_changelog_items(r.text, now))
    except Exception:
        pass

    if not out:
        raise ValueError("No official AI update sources returned items")

    return out


def parse_ai_breakfast_items(markdown_text: str, now: datetime) -> list[RawItem]:
    site_id = "aibreakfast"
    site_name = "AI Breakfast"
    out: list[RawItem] = []
    seen: set[str] = set()
    pattern = re.compile(
        r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\s+•\s+\d+\s+min read\s+###\s+\*\*(.*?)\*\*.*?"
        r"\]\((https?://aibreakfast\.beehiiv\.com/p/[^)]+)\)",
        re.S,
    )

    for date_text, title_text, url in pattern.findall(markdown_text or ""):
        url = url.strip()
        if not url or url in seen:
            continue
        published = parse_date_any(date_text, now)
        if not published:
            continue
        if now and published < now - timedelta(days=OFFICIAL_AI_MAX_AGE_DAYS):
            continue

        seen.add(url)
        title = re.sub(r"\s+", " ", title_text).strip()
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source="AI Breakfast",
                title=maybe_fix_mojibake(title),
                url=url,
                published_at=published,
                meta={"feed_home": "https://aibreakfast.beehiiv.com/"},
            )
        )

    return out


def fetch_ai_breakfast(session: requests.Session, now: datetime) -> list[RawItem]:
    resp = session.get(
        AIBREAKFAST_JINA_URL,
        timeout=25,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/plain, */*",
        },
    )
    resp.raise_for_status()
    out = parse_ai_breakfast_items(resp.text, now)
    if not out:
        raise ValueError("No AI Breakfast items parsed")
    return out


def parse_follow_builders_items(feeds: dict[str, dict[str, Any]], now: datetime) -> list[RawItem]:
    site_id = "followbuilders"
    site_name = "Follow Builders"
    out: list[RawItem] = []

    for builder in feeds.get("x", {}).get("x", []) or []:
        name = str(builder.get("name") or builder.get("handle") or "").strip()
        handle = str(builder.get("handle") or "").strip()
        source = f"Follow Builders · X · {name or handle}".strip(" ·")
        for tweet in builder.get("tweets", []) or []:
            text = str(tweet.get("text") or "").strip()
            url = str(tweet.get("url") or "").strip()
            published = parse_date_any(tweet.get("createdAt"), now)
            if not text or not url or not published:
                continue
            title = re.sub(r"\s+", " ", text)
            if len(title) > 220:
                title = title[:217].rstrip() + "..."
            out.append(
                RawItem(
                    site_id=site_id,
                    site_name=site_name,
                    source=source,
                    title=maybe_fix_mojibake(title),
                    url=url,
                    published_at=published,
                    meta={"handle": handle, "feed": "feed-x.json"},
                )
            )

    for article in feeds.get("blogs", {}).get("blogs", []) or []:
        title = str(article.get("title") or "").strip()
        url = str(article.get("url") or "").strip()
        published = parse_date_any(article.get("publishedAt"), now) or parse_date_any(
            feeds.get("blogs", {}).get("generatedAt"), now
        )
        if not title or not url or not published:
            continue
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source=f"Follow Builders · Blog · {article.get('name') or 'Blog'}",
                title=maybe_fix_mojibake(title),
                url=url,
                published_at=published,
                meta={"feed": "feed-blogs.json"},
            )
        )

    for episode in feeds.get("podcasts", {}).get("podcasts", []) or []:
        title = str(episode.get("title") or "").strip()
        url = str(episode.get("url") or "").strip()
        published = parse_date_any(episode.get("publishedAt"), now) or parse_date_any(
            feeds.get("podcasts", {}).get("generatedAt"), now
        )
        if not title or not url or not published:
            continue
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source=f"Follow Builders · Podcast · {episode.get('name') or 'Podcast'}",
                title=maybe_fix_mojibake(title),
                url=url,
                published_at=published,
                meta={"feed": "feed-podcasts.json"},
            )
        )

    return out


def fetch_follow_builders(session: requests.Session, now: datetime) -> list[RawItem]:
    feeds: dict[str, dict[str, Any]] = {}
    for key, filename in (
        ("x", "feed-x.json"),
        ("blogs", "feed-blogs.json"),
        ("podcasts", "feed-podcasts.json"),
    ):
        resp = session.get(
            f"{FOLLOW_BUILDERS_FEED_BASE}/{filename}",
            timeout=20,
            headers={
                "User-Agent": BROWSER_UA,
                "Accept": "application/json, */*",
            },
        )
        resp.raise_for_status()
        feeds[key] = resp.json()

    out = parse_follow_builders_items(feeds, now)
    if not out:
        raise ValueError("No Follow Builders items parsed")
    return out


def is_hubtoday_placeholder_title(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    if "详情见官方介绍" in t:
        return True
    return t in {"原文链接", "查看详情", "点击查看", "详情"}


def is_hubtoday_generic_anchor_title(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    if is_hubtoday_placeholder_title(t):
        return True
    return bool(re.search(r"\(AI资讯\)\s*$", t))


def normalize_aihubtoday_records(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, list[dict[str, Any]]] = {}
    keep: list[dict[str, Any]] = []

    for item in items:
        if str(item.get("site_id") or "") != "aihubtoday":
            keep.append(item)
            continue
        url = normalize_url(str(item.get("url") or ""))
        if not url:
            continue
        by_url.setdefault(url, []).append(item)

    for group in by_url.values():
        if not group:
            continue
        preferred = [g for g in group if not is_hubtoday_generic_anchor_title(str(g.get("title") or ""))]
        source = preferred if preferred else group
        best = max(
            source,
            key=lambda x: (
                event_time(x) or datetime.min.replace(tzinfo=UTC),
                str(x.get("id") or ""),
            ),
        )
        keep.append(best)

    keep.sort(key=lambda x: event_time(x) or datetime.min.replace(tzinfo=UTC), reverse=True)
    return keep


AIHUBTODAY_RSS_URL = "https://hex2077.dev/rss-zh-CN.xml"


def fetch_ai_hubtoday(session: requests.Session, now: datetime) -> list[RawItem]:
    site_id = "aihubtoday"
    site_name = "AI HubToday"
    # ai.hubtoday.app migrated to hex2077.dev (a Next.js SPA), so the old HTML
    # selectors no longer match and produced 0 usable items. Read the site's
    # structured RSS feed instead: every entry has a real title, link and date,
    # which is far more robust than scraping a client-rendered page.
    r = session.get(AIHUBTODAY_RSS_URL, timeout=30)
    r.raise_for_status()
    if feedparser is not None:
        entries = list(feedparser.parse(r.content).entries)
    else:
        entries = parse_feed_entries_via_xml(r.content)

    out: list[RawItem] = []
    seen_urls: set[str] = set()
    for entry in entries:
        title, link, published = feed_entry_title_link_published(entry, now)
        if len(title) < 5 or not link.startswith("http"):
            continue
        if is_hubtoday_placeholder_title(title):
            continue
        key_url = normalize_url(link)
        if key_url in seen_urls:
            continue
        seen_urls.add(key_url)
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source="Daily Digest",
                title=title,
                url=link,
                published_at=published,
                meta={"feed_url": AIHUBTODAY_RSS_URL},
            )
        )
    return out

def fetch_aibase(session: requests.Session, now: datetime) -> list[RawItem]:
    site_id = "aibase"
    site_name = "AIbase"

    r = session.get("https://www.aibase.com/zh/news", timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out: list[RawItem] = []
    for a in soup.select("a[href^='/news/']"):
        h3 = a.select_one("h3")
        if not h3:
            continue
        title = h3.get_text(" ", strip=True)
        href = a.get("href", "").strip()
        if not title or not href:
            continue

        time_text = ""
        time_tag = a.select_one("div.text-sm.text-gray-400 span")
        if time_tag:
            time_text = time_tag.get_text(" ", strip=True)

        published = parse_date_any(time_text, now)
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source=site_name,
                title=title,
                url=urljoin("https://www.aibase.com", href),
                published_at=published,
                meta={"time_hint": time_text},
            )
        )

    return out


def parse_aihot_feed_items(feed_content: bytes, now: datetime, feed_url: str = AIHOT_FEED_URL) -> list[RawItem]:
    site_id = "aihot"
    site_name = "AI HOT"
    source_name = site_name
    if feedparser is not None:
        parsed = feedparser.parse(feed_content)
        entries = list(parsed.entries)
        source_name = first_non_empty(getattr(parsed, "feed", {}).get("title"), site_name)
    else:
        entries = parse_feed_entries_via_xml(feed_content)

    out: list[RawItem] = []
    seen_urls: set[str] = set()
    for entry in entries:
        title = maybe_fix_mojibake(str(entry.get("title") or "").strip())
        link = str(entry.get("link") or "").strip()
        if not title or not link:
            continue
        normalized_url = normalize_url(link)
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        published = (
            parse_date_any(entry.get("published"), now)
            or parse_date_any(entry.get("updated"), now)
            or parse_date_any(entry.get("pubDate"), now)
        )
        if not published:
            continue
        author_detail = entry.get("author_detail") or {}
        entry_source = first_non_empty(
            author_detail.get("name") if isinstance(author_detail, dict) else "",
            entry.get("author"),
            source_name,
        )
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source=maybe_fix_mojibake(entry_source),
                title=title,
                url=link,
                published_at=published,
                meta={"feed_url": feed_url},
            )
        )

    return out


def parse_aihot_api_items(payload: dict[str, Any], now: datetime | None = None) -> list[RawItem]:
    site_id = "aihot"
    site_name = "AI HOT"
    out: list[RawItem] = []
    seen_urls: set[str] = set()

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return out

    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        raw_score = entry.get("score")
        if isinstance(raw_score, bool):
            continue
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if score < AIHOT_MIN_SCORE:
            continue

        title = maybe_fix_mojibake(str(first_non_empty(entry.get("title"), entry.get("title_en")) or "").strip())
        link = str(entry.get("url") or "").strip()
        if not title or not link:
            continue
        normalized_url = normalize_url(link)
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)

        published = parse_iso(str(entry.get("publishedAt") or "")) or parse_date_any(entry.get("publishedAt"), now)
        source = maybe_fix_mojibake(str(first_non_empty(entry.get("source"), site_name)))
        score_value: int | float = int(score) if score.is_integer() else score
        out.append(
            RawItem(
                site_id=site_id,
                site_name=site_name,
                source=source,
                title=title,
                url=link,
                published_at=published,
                meta={
                    "api_url": AIHOT_ITEMS_API_URL,
                    "aihot_id": entry.get("id"),
                    "aihot_score": score_value,
                    "aihot_category": entry.get("category"),
                    "aihot_selected": bool(entry.get("selected")),
                    "summary": entry.get("summary"),
                },
            )
        )

    return out


def fetch_aihot(session: requests.Session, now: datetime) -> list[RawItem]:
    out: list[RawItem] = []
    cursor = ""
    for _ in range(AIHOT_API_MAX_PAGES):
        params: dict[str, Any] = {"mode": "selected", "take": AIHOT_API_TAKE}
        if cursor:
            params["cursor"] = cursor
        r = session.get(
            AIHOT_ITEMS_API_URL,
            timeout=30,
            params=params,
            headers={
                "User-Agent": AIHOT_API_UA,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept": "application/json",
            },
        )
        r.raise_for_status()
        payload = r.json()
        out.extend(parse_aihot_api_items(payload, now))
        cursor = str(payload.get("nextCursor") or "")
        if not payload.get("hasNext") or not cursor:
            break
    return out




def extract_newsnow_source_ids(js: str) -> list[str]:
    marker = "{v2ex:vL"
    start = js.find(marker)
    if start == -1:
        return ["hackernews", "producthunt", "github", "sspai", "juejin", "36kr"]

    # Locate beginning "{" and parse until matching "}"
    block_start = start
    depth = 0
    end = None
    in_str = False
    esc = False

    for i, ch in enumerate(js[block_start:], block_start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end is None:
        return ["hackernews", "producthunt", "github", "sspai", "juejin", "36kr"]

    obj = js[block_start:end]
    all_keys = [m.group(2) for m in re.finditer(r'(["\']?)([a-zA-Z0-9_-]+)\1\s*:', obj)]

    ignore = {
        "name",
        "column",
        "home",
        "https",
        "color",
        "interval",
        "title",
        "type",
        "redirect",
        "desc",
    }

    source_ids: list[str] = []
    for key in all_keys:
        if key in ignore:
            continue
        if key not in source_ids:
            source_ids.append(key)

    # API currently returns around 57 source ids successfully.
    return source_ids


def fetch_newsnow(session: requests.Session, now: datetime) -> list[RawItem]:
    site_id = "newsnow"
    site_name = "NewsNow"

    home = session.get("https://newsnow.busiyi.world/", timeout=30)
    home.raise_for_status()
    soup = BeautifulSoup(home.text, "html.parser")

    bundle = None
    for script in soup.select("script[src]"):
        src = script.get("src", "")
        if "/assets/index-" in src and src.endswith(".js"):
            bundle = urljoin("https://newsnow.busiyi.world/", src)
            break

    source_ids = ["hackernews", "producthunt", "github", "sspai", "juejin", "36kr"]
    if bundle:
        js = session.get(bundle, timeout=30).text
        source_ids = extract_newsnow_source_ids(js)

    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://newsnow.busiyi.world",
        "Referer": "https://newsnow.busiyi.world/",
    }

    response = session.post(
        "https://newsnow.busiyi.world/api/s/entire",
        json={"sources": source_ids},
        headers=headers,
        timeout=45,
    )

    if response.status_code != 200:
        # fallback to per-source API
        source_blocks = []
        for sid in source_ids:
            rr = session.get(f"https://newsnow.busiyi.world/api/s?id={sid}", headers=headers, timeout=20)
            if rr.status_code == 200:
                try:
                    source_blocks.append(rr.json())
                except Exception:
                    pass
    else:
        body = response.json()
        source_blocks = body.get("data") if isinstance(body, dict) else body
    if not isinstance(source_blocks, list):
        source_blocks = []

    out: list[RawItem] = []
    for block in source_blocks:
        sid = str(block.get("id") or "unknown")
        source_title = first_non_empty(block.get("title"), block.get("name"), block.get("desc"), sid)
        source_label = f"{source_title} ({sid})" if source_title != sid else sid
        updated = parse_unix_timestamp(block.get("updatedTime")) or now
        items = block.get("items") or []
        for it in items:
            title = str(it.get("title") or "").strip()
            url = str(it.get("url") or "").strip()
            if not title or not url:
                continue

            published = None
            published = published or parse_date_any(it.get("pubDate"), now)
            if not published:
                extra = it.get("extra") or {}
                if isinstance(extra, dict):
                    published = parse_date_any(extra.get("date"), now)
            if not published:
                published = updated

            out.append(
                RawItem(
                    site_id=site_id,
                    site_name=site_name,
                    source=source_label,
                    title=title,
                    url=url,
                    published_at=published,
                    meta={},
                )
            )

    return out


def fetch_github_repo_subscription(
    session: requests.Session,
    now: datetime,
    *,
    api_url: str = GITHUB_REPO_SUBSCRIPTION_API_URL,
    max_items: int = GITHUB_REPO_SUBSCRIPTION_MAX_ITEMS,
) -> list[RawItem]:
    params = {"per_page": max(1, min(10, int(max_items or 1)))}
    resp = session.get(
        api_url,
        params=params,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "AI-News-Radar/0.7 github-release-subscription",
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list):
        return []

    out: list[RawItem] = []
    seen: set[str] = set()
    for release in payload[:max_items]:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = str(release.get("tag_name") or "").strip()
        name = str(release.get("name") or "").strip() or tag
        url = str(release.get("html_url") or "").strip()
        if not url and tag:
            url = f"{GITHUB_REPO_SUBSCRIPTION_HTML_URL}/releases/tag/{tag}"
        if not name or not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        published = parse_date_any(release.get("published_at") or release.get("created_at"), now) or now
        release_type = "预发布" if release.get("prerelease") else "正式发布"
        title = f"AlkaidLab/foundation-sunshine {release_type}: {name}"
        out.append(
            RawItem(
                site_id=GITHUB_REPO_SUBSCRIPTION_SITE_ID,
                site_name=GITHUB_REPO_SUBSCRIPTION_SITE_NAME,
                source="GitHub版本订阅",
                title=title,
                url=url,
                published_at=published,
                meta={
                    "summary": title,
                    "source_kind": "github_release_subscription",
                    "repo": "AlkaidLab/foundation-sunshine",
                    "tag_name": tag,
                    "release_name": name,
                    "prerelease": bool(release.get("prerelease")),
                },
            )
        )
    return out


def clean_wp_rendered_text(value: Any, max_chars: int = 220) -> str:
    if isinstance(value, dict):
        value = value.get("rendered")
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def fetch_maobidao_wechat_subscription(
    session: requests.Session,
    now: datetime,
    *,
    api_url: str = MAOBIDAO_WECHAT_API_URL,
    max_items: int = MAOBIDAO_WECHAT_MAX_ITEMS,
) -> list[RawItem]:
    resp = session.get(
        api_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AI-News-Radar/0.7 maobidao-wudaolu-backup",
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = json.loads(resp.content.decode("utf-8"))
    topics = payload.get("topic_list", {}).get("topics", []) if isinstance(payload, dict) else []
    if not isinstance(topics, list):
        return []

    out: list[RawItem] = []
    seen: set[str] = set()
    for topic in topics:
        if len(out) >= max_items:
            break
        if not isinstance(topic, dict):
            continue
        title = first_non_empty(topic.get("title"))
        if "猫笔刀" not in title:
            continue
        topic_id = first_non_empty(topic.get("id"))
        url = normalize_url(f"https://wudaolu.com/t/topic/{topic_id}" if topic_id else "")
        if not title or not url or url in seen:
            continue
        seen.add(url)
        published = parse_date_any(topic.get("created_at") or topic.get("last_posted_at"), now) or now
        out.append(
            RawItem(
                site_id=MAOBIDAO_WECHAT_SITE_ID,
                site_name=MAOBIDAO_WECHAT_SITE_NAME,
                source="猫笔刀公众号",
                title=title,
                url=url,
                published_at=published,
                meta={
                    "summary": title,
                    "source_kind": "wechat_public_account_backup",
                    "wechat_account": "maobidao",
                    "source_origin": MAOBIDAO_WECHAT_HOME_URL,
                    "discourse_topic_id": topic_id,
                },
            )
        )
    return out


def wewe_rss_base_url() -> str:
    return (os.environ.get("WEWE_RSS_BASE_URL") or WEWE_RSS_BASE_URL_DEFAULT).strip().rstrip("/")


def wewe_rss_feeds_from_env(raw: str | None) -> list[dict[str, str]]:
    feeds: list[dict[str, str]] = []
    for part in re.split(r"[,\n;]+", raw or ""):
        value = part.strip()
        if not value:
            continue
        if ":" in value:
            source_name, feed_id = value.split(":", 1)
        else:
            source_name, feed_id = "", value
        feed_id = feed_id.strip()
        if not feed_id:
            continue
        feeds.append({"id": feed_id, "name": source_name.strip() or feed_id})
    return feeds


def parse_wewe_rss_json_feed_items(
    payload: dict[str, Any],
    now: datetime,
    *,
    source_name: str,
    feed_id: str,
    max_items: int,
) -> list[RawItem]:
    items = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []

    out: list[RawItem] = []
    seen: set[str] = set()
    for item in items:
        if len(out) >= max_items:
            break
        if not isinstance(item, dict):
            continue
        title = clean_wp_rendered_text(item.get("title"), max_chars=160)
        url = normalize_url(first_non_empty(item.get("url"), item.get("external_url")))
        item_id = first_non_empty(item.get("id"))
        if not title or not url:
            continue
        key = url or item_id or title
        if key in seen:
            continue
        seen.add(key)
        published = parse_date_any(
            first_non_empty(item.get("date_published"), item.get("date_modified")),
            now,
        ) or now
        summary = clean_wp_rendered_text(
            first_non_empty(item.get("summary"), item.get("content_text"), item.get("content_html")),
            max_chars=220,
        )
        out.append(
            RawItem(
                site_id=WEWE_RSS_SITE_ID,
                site_name=WEWE_RSS_SITE_NAME,
                source=source_name or "WeWe RSS",
                title=title,
                url=url,
                published_at=published,
                meta={
                    "summary": summary or title,
                    "source_kind": "wewe_rss_wechat_subscription",
                    "wechat_account": source_name,
                    "wewe_feed_id": feed_id,
                    "wewe_item_id": item_id,
                    "search_surface": "wewe_rss_json_feed",
                },
            )
        )
    return out


def fetch_wewe_rss_subscription(
    session: requests.Session,
    now: datetime,
    *,
    base_url: str | None = None,
    feeds_config: str | None = None,
    max_items: int | None = None,
) -> tuple[list[RawItem], dict[str, Any]]:
    start = time.perf_counter()
    base = (base_url or wewe_rss_base_url()).strip().rstrip("/")
    max_items_per_feed = max(1, min(100, int(max_items or env_int("WEWE_RSS_MAX_ITEMS", WEWE_RSS_DEFAULT_MAX_ITEMS))))
    status: dict[str, Any] = {
        "enabled": True,
        "ok": False,
        "item_count": 0,
        "duration_ms": 0,
        "error": None,
        "source_kind": "wewe_rss_wechat_subscription",
        "base_url": base,
        "max_items_per_feed": max_items_per_feed,
        "feeds": [],
        "coverage_note": "reads_local_wewe_rss_json_feed_without_wechat_login_state",
        "privacy": "local_sidecar_no_cookies_in_radar_repo",
    }
    if not base:
        status["error"] = "missing_wewe_rss_base_url"
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)
        return [], status

    configured_feeds = wewe_rss_feeds_from_env(feeds_config if feeds_config is not None else os.environ.get("WEWE_RSS_FEEDS"))
    try:
        feeds = configured_feeds
        if not feeds:
            feed_list_resp = session.get(
                f"{base}/feeds",
                headers={"Accept": "application/json", "User-Agent": "AI-News-Radar/0.7 wewe-rss-bridge"},
                timeout=15,
            )
            feed_list_resp.raise_for_status()
            payload = json.loads(feed_list_resp.content.decode("utf-8"))
            if isinstance(payload, list):
                feeds = [
                    {
                        "id": first_non_empty(row.get("id")),
                        "name": first_non_empty(row.get("name"), row.get("mpName"), row.get("id")),
                    }
                    for row in payload
                    if isinstance(row, dict) and first_non_empty(row.get("id"))
                ]
        if not feeds:
            status["ok"] = True
            status["error"] = "wewe_rss_no_feeds"
            return [], status

        all_items: list[RawItem] = []
        feed_statuses: list[dict[str, Any]] = []
        for feed in feeds:
            feed_id = feed["id"]
            source_name = feed.get("name") or feed_id
            feed_status = {"id": feed_id, "name": source_name, "ok": False, "item_count": 0, "error": None}
            try:
                resp = session.get(
                    f"{base}/feeds/{feed_id}.json",
                    params={"limit": max_items_per_feed},
                    headers={"Accept": "application/feed+json, application/json", "User-Agent": "AI-News-Radar/0.7 wewe-rss-bridge"},
                    timeout=20,
                )
                resp.raise_for_status()
                feed_payload = json.loads(resp.content.decode("utf-8"))
                items = parse_wewe_rss_json_feed_items(
                    feed_payload,
                    now,
                    source_name=source_name,
                    feed_id=feed_id,
                    max_items=max_items_per_feed,
                )
                all_items.extend(items)
                feed_status.update({"ok": True, "item_count": len(items)})
            except Exception as exc:
                feed_status["error"] = str(exc)
            feed_statuses.append(feed_status)

        status["feeds"] = feed_statuses
        status["item_count"] = len(all_items)
        status["ok"] = all(feed.get("ok") for feed in feed_statuses)
        failed = [feed for feed in feed_statuses if not feed.get("ok")]
        if failed:
            status["error"] = f"failed_wewe_rss_feeds:{len(failed)}"
        return all_items, status
    except Exception as exc:
        status["error"] = str(exc)
        return [], status
    finally:
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)


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


def parse_opml_subscriptions(opml_path: Path) -> list[dict[str, str]]:
    root = ET.parse(opml_path).getroot()
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    for outline in root.findall(".//outline"):
        xml_url = str(outline.attrib.get("xmlUrl") or "").strip()
        if not xml_url:
            continue
        if xml_url in seen:
            continue
        seen.add(xml_url)
        title = first_non_empty(
            outline.attrib.get("title"),
            outline.attrib.get("text"),
            host_of_url(xml_url),
            xml_url,
        )
        html_url = str(outline.attrib.get("htmlUrl") or "").strip()
        out.append(
            {
                "title": title,
                "xml_url": xml_url,
                "html_url": html_url,
            }
        )
    return out


def resolve_official_rss_url(feed_url: str) -> tuple[str | None, str | None]:
    src = (feed_url or "").strip()
    if not src:
        return None, "empty_url"
    if src in RSS_FEED_SKIP_EXACT:
        return None, "no_official_rss_or_unreachable"
    for prefix in RSS_FEED_SKIP_PREFIXES:
        if src.startswith(prefix):
            return None, "no_official_rss_for_source_type"
    replaced = RSS_FEED_REPLACEMENTS.get(src)
    if replaced:
        return replaced, "official_replacement"
    return src, None


def resolve_opml_bridge_source(feed_url: str, html_url: str = "") -> dict[str, str] | None:
    src = (feed_url or "").strip()
    parsed = urlparse(src)
    path = parsed.path.strip("/")
    parts = [p for p in path.split("/") if p]

    if parsed.netloc == "rsshub.app" and len(parts) >= 3 and parts[:2] == ["telegram", "channel"]:
        slug = parts[2]
        return {
            "bridge_type": "telegram",
            "bridge_slug": slug,
            "url": f"https://t.me/s/{slug}",
        }

    if parsed.netloc == "rsshub.app" and len(parts) >= 3 and parts[0] == "jike":
        kind = parts[1]
        ident = parts[2]
        if kind == "topic":
            return {
                "bridge_type": "jike",
                "bridge_kind": "topic",
                "bridge_slug": ident,
                "url": f"https://m.okjike.com/topics/{ident}",
            }
        if kind == "user":
            return {
                "bridge_type": "jike",
                "bridge_kind": "user",
                "bridge_slug": ident,
                "url": f"https://m.okjike.com/users/{ident}",
            }

    html = (html_url or "").strip()
    if html.startswith("https://t.me/s/"):
        slug = html.rstrip("/").split("/")[-1]
        return {"bridge_type": "telegram", "bridge_slug": slug, "url": html}
    if html.startswith("https://m.okjike.com/topics/"):
        ident = html.rstrip("/").split("/")[-1]
        return {"bridge_type": "jike", "bridge_kind": "topic", "bridge_slug": ident, "url": html}
    if html.startswith("https://m.okjike.com/users/"):
        ident = html.rstrip("/").split("/")[-1]
        return {"bridge_type": "jike", "bridge_kind": "user", "bridge_slug": ident, "url": html}

    return None


def compact_title(text: str, limit: int = 96) -> str:
    s = re.sub(r"\s+", " ", text or "").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def parse_telegram_public_items(
    html: str,
    *,
    now: datetime,
    source_name: str,
    slug: str,
) -> list[RawItem]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[RawItem] = []
    for msg in soup.select(".tgme_widget_message"):
        data_post = str(msg.get("data-post") or "").strip()
        if not data_post:
            continue
        text_node = msg.select_one(".tgme_widget_message_text")
        text = text_node.get_text(" ", strip=True) if text_node else ""
        if not text:
            preview_title = msg.select_one(".tgme_widget_message_link_preview_title")
            text = preview_title.get_text(" ", strip=True) if preview_title else ""
        if not text:
            continue
        time_node = msg.select_one("time[datetime]")
        published = parse_date_any(time_node.get("datetime") if time_node else None, now)
        if not published:
            continue
        url = f"https://t.me/{data_post}"
        out.append(
            RawItem(
                site_id="opmlrss",
                site_name="OPML RSS",
                source=source_name,
                title=compact_title(text),
                url=url,
                published_at=published,
                meta={"bridge_type": "telegram", "bridge_slug": slug, "feed_home": f"https://t.me/s/{slug}"},
            )
        )
    return out


def parse_jike_public_items(
    html: str,
    *,
    now: datetime,
    source_name: str,
    source_url: str,
) -> list[RawItem]:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        return []
    try:
        payload = json.loads(script.string)
    except Exception:
        return []
    page_props = payload.get("props", {}).get("pageProps", {})
    posts = page_props.get("posts") or []
    out: list[RawItem] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        post_id = str(post.get("id") or "").strip()
        text = str(post.get("content") or "").strip()
        if not post_id or not text:
            continue
        published = parse_date_any(post.get("createdAt") or post.get("actionTime"), now)
        if not published:
            continue
        out.append(
            RawItem(
                site_id="opmlrss",
                site_name="OPML RSS",
                source=source_name,
                title=compact_title(text),
                url=f"https://m.okjike.com/originalPosts/{post_id}",
                published_at=published,
                meta={"bridge_type": "jike", "feed_home": source_url},
            )
        )
    return out


def fetch_opml_rss(
    now: datetime,
    opml_path: Path,
    max_feeds: int = 0,
) -> tuple[list[RawItem], dict[str, Any], list[dict[str, Any]]]:
    feeds = parse_opml_subscriptions(opml_path)
    if max_feeds > 0:
        feeds = feeds[:max_feeds]

    out: list[RawItem] = []
    feed_statuses: list[dict[str, Any]] = []
    resolved_feeds: list[dict[str, str]] = []

    for feed in feeds:
        original_url = feed["xml_url"]
        bridge = resolve_opml_bridge_source(original_url, feed.get("html_url") or "")
        if bridge:
            record = dict(feed)
            record["xml_url_original"] = original_url
            record["xml_url"] = bridge["url"]
            record["replaced"] = True
            record.update(bridge)
            resolved_feeds.append(record)
            continue

        resolved_url, skip_reason = resolve_official_rss_url(original_url)
        if not resolved_url:
            feed_id = hashlib.sha1(original_url.encode("utf-8")).hexdigest()[:10]
            feed_statuses.append(
                {
                    "site_id": f"opmlrss:{feed_id}",
                    "site_name": "OPML RSS",
                    "feed_title": feed["title"],
                    "feed_url": original_url,
                    "effective_feed_url": None,
                    "ok": True,
                    "item_count": 0,
                    "duration_ms": 0,
                    "error": None,
                    "skipped": True,
                    "skip_reason": skip_reason or "skipped",
                    "replaced": False,
                }
            )
            continue
        record = dict(feed)
        record["xml_url_original"] = original_url
        record["xml_url"] = resolved_url
        record["replaced"] = bool(resolved_url != original_url)
        resolved_feeds.append(record)

    def fetch_single_feed(feed: dict[str, str]) -> tuple[list[RawItem], dict[str, Any]]:
        feed_url = feed["xml_url"]
        original_feed_url = str(feed.get("xml_url_original") or feed_url)
        feed_title = feed["title"]
        feed_id = hashlib.sha1(feed_url.encode("utf-8")).hexdigest()[:10]
        start = time.perf_counter()
        error = None
        local_items: list[RawItem] = []

        try:
            resp = requests.get(
                feed_url,
                timeout=12,
                headers={
                    "User-Agent": BROWSER_UA,
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            resp.raise_for_status()

            bridge_type = str(feed.get("bridge_type") or "")
            if bridge_type == "telegram":
                local_items = parse_telegram_public_items(
                    resp.text,
                    now=now,
                    source_name=feed_title,
                    slug=str(feed.get("bridge_slug") or ""),
                )
            elif bridge_type == "jike":
                local_items = parse_jike_public_items(
                    resp.text,
                    now=now,
                    source_name=feed_title,
                    source_url=feed_url,
                )
            elif feedparser is not None:
                parsed = feedparser.parse(resp.content)
                source_name = first_non_empty(
                    feed_title,
                    getattr(parsed, "feed", {}).get("title"),
                    host_of_url(feed_url),
                )
                entries = parsed.entries
                for entry in entries:
                    title = str(entry.get("title", "")).strip()
                    link = str(entry.get("link", "")).strip()
                    if not title or not link:
                        continue
                    published = (
                        parse_date_any(entry.get("published"), now)
                        or parse_date_any(entry.get("updated"), now)
                        or parse_date_any(entry.get("pubDate"), now)
                    )
                    if not published:
                        continue
                    local_items.append(
                        RawItem(
                            site_id="opmlrss",
                            site_name="OPML RSS",
                            source=source_name,
                            title=title,
                            url=link,
                            published_at=published,
                            meta={
                                "feed_url": feed_url,
                                "feed_home": feed.get("html_url") or "",
                            },
                        )
                    )
            else:
                source_name = first_non_empty(feed_title, host_of_url(feed_url))
                entries = parse_feed_entries_via_xml(resp.content)
                for entry in entries:
                    published = parse_date_any(entry.get("published"), now)
                    if not published:
                        continue
                    local_items.append(
                        RawItem(
                            site_id="opmlrss",
                            site_name="OPML RSS",
                            source=source_name,
                            title=entry.get("title", ""),
                            url=entry.get("link", ""),
                            published_at=published,
                            meta={
                                "feed_url": feed_url,
                                "feed_home": feed.get("html_url") or "",
                            },
                        )
                    )
        except Exception as exc:
            error = str(exc)

        duration_ms = int((time.perf_counter() - start) * 1000)
        status = {
            "site_id": f"opmlrss:{feed_id}",
            "site_name": "OPML RSS",
            "feed_title": feed_title,
            "feed_url": original_feed_url,
            "effective_feed_url": feed_url,
            "ok": error is None,
            "item_count": len(local_items),
            "duration_ms": duration_ms,
            "error": error,
            "skipped": False,
            "skip_reason": None,
            "replaced": bool(original_feed_url != feed_url),
            "bridge_type": feed.get("bridge_type"),
        }
        return local_items, status

    if resolved_feeds:
        worker_count = min(20, max(4, len(resolved_feeds)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(fetch_single_feed, feed) for feed in resolved_feeds]
            for future in as_completed(futures):
                items, status = future.result()
                out.extend(items)
                feed_statuses.append(status)

    feed_statuses.sort(key=lambda x: str(x.get("feed_title") or x.get("feed_url") or ""))
    total_duration_ms = sum(int(s.get("duration_ms") or 0) for s in feed_statuses)
    ok_feeds = sum(1 for s in feed_statuses if s["ok"])
    failed_feeds = sum(1 for s in feed_statuses if not s["ok"])
    skipped_feeds = sum(1 for s in feed_statuses if s.get("skipped"))
    replaced_feeds = sum(1 for s in feed_statuses if s.get("replaced"))

    summary_status = {
        "site_id": "opmlrss",
        "site_name": "OPML RSS",
        "ok": ok_feeds > 0,
        "partial_failures": failed_feeds,
        "item_count": len(out),
        "duration_ms": total_duration_ms,
        "error": None if failed_feeds == 0 else f"{failed_feeds} feeds failed",
        "feed_count": len(feeds),
        "effective_feed_count": len(resolved_feeds),
        "ok_feed_count": ok_feeds,
        "failed_feed_count": failed_feeds,
        "skipped_feed_count": skipped_feeds,
        "replaced_feed_count": replaced_feeds,
    }
    return out, summary_status, feed_statuses


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


def normalize_source_scope(raw_scope: str | None) -> str:
    raw = str(raw_scope or "").strip().lower().replace("-", "_")
    if raw in {"", "tested", "tested_creators", "tested_creator_sources", "creator_sources", "social_sources"}:
        return SOURCE_SCOPE_TESTED_CREATORS
    if raw in {"all", "all_sources", "legacy_all_sources"}:
        return SOURCE_SCOPE_ALL
    if raw in {"bilibili", "bilibili_only"}:
        return SOURCE_SCOPE_BILIBILI_ONLY
    return DEPLOYED_SOURCE_SCOPE_DEFAULT


def source_ids_for_scope(source_scope: str) -> frozenset[str] | None:
    if source_scope == SOURCE_SCOPE_BILIBILI_ONLY:
        return frozenset({"bilibili_dynamic"})
    if source_scope == SOURCE_SCOPE_TESTED_CREATORS:
        return TESTED_CREATOR_SOURCE_IDS
    return None


def source_config_candidate_paths(raw_path: str | None, output_dir: Path | None = None) -> list[Path]:
    if raw_path:
        return [Path(raw_path).expanduser()]
    env_path = str(os.environ.get("RADAR_SOURCE_CONFIG") or "").strip()
    if env_path:
        return [Path(env_path).expanduser()]
    candidates = [Path(name) for name in SOURCE_CONFIG_DEFAULT_FILENAMES]
    if output_dir is not None:
        candidates.append(output_dir / "sources.config.json")
    return candidates


def load_source_config(raw_path: str | None, output_dir: Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    candidates = source_config_candidate_paths(raw_path, output_dir=output_dir)
    explicit = bool(raw_path or os.environ.get("RADAR_SOURCE_CONFIG"))
    status: dict[str, Any] = {
        "enabled": False,
        "ok": None,
        "path": None,
        "candidate_paths": [str(path) for path in candidates],
        "error": None,
    }
    for path in candidates:
        if not path.exists():
            continue
        status["enabled"] = True
        status["path"] = str(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("source config root must be a JSON object")
            sources = payload.get("sources")
            if not isinstance(sources, list):
                raise ValueError("source config must contain a sources array")
            status["ok"] = True
            status["source_count"] = len(sources)
            return payload, status
        except Exception as exc:
            status["ok"] = False
            status["error"] = str(exc)
            return None, status
    if explicit:
        status["enabled"] = True
        status["ok"] = False
        status["error"] = "source_config_not_found"
    return None, status


def source_config_record_site_ids(record: dict[str, Any]) -> tuple[str, ...]:
    raw_id = str(record.get("id") or "").strip()
    raw_type = str(record.get("type") or "").strip()
    if raw_id in SOURCE_CONFIG_ID_SITE_IDS:
        return SOURCE_CONFIG_ID_SITE_IDS[raw_id]
    if raw_id in SOURCE_CONFIG_TYPE_SITE_IDS:
        return SOURCE_CONFIG_TYPE_SITE_IDS[raw_id]
    if raw_type == "mediacrawler_jsonl":
        channel = str(record.get("channel") or "").lower()
        target = str(record.get("target") or "").lower()
        locator = str(record.get("locator") or "").lower()
        haystack = f"{raw_id} {channel} {target} {locator}"
        if "xhs" in haystack or "xiaohongshu" in haystack or "小红书" in haystack:
            return (MEDIACRAWLER_XHS_SITE_ID,)
        if "douyin" in haystack or "抖音" in haystack:
            return (MEDIACRAWLER_DOUYIN_SITE_ID,)
    return SOURCE_CONFIG_TYPE_SITE_IDS.get(raw_type, ())


def source_config_enabled_sources(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not config:
        return []
    sources = config.get("sources")
    if not isinstance(sources, list):
        return []
    return [
        source
        for source in sources
        if isinstance(source, dict) and source.get("enabled") is not False
    ]


def source_config_enabled_site_ids(config: dict[str, Any] | None) -> frozenset[str]:
    enabled: set[str] = set()
    for source in source_config_enabled_sources(config):
        enabled.update(source_config_record_site_ids(source))
    return frozenset(enabled)


def set_env_from_source_config(name: str, value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    os.environ[name] = value
    return True


def apply_source_config_runtime(config: dict[str, Any] | None) -> dict[str, Any]:
    enabled_sources = source_config_enabled_sources(config)
    enabled_site_ids = source_config_enabled_site_ids(config)
    applied_env: list[str] = []
    bilibili_uids: list[str] = []
    bilibili_names: list[str] = []
    wewe_feeds: list[str] = []
    opml_path = ""

    for source in enabled_sources:
        site_ids = source_config_record_site_ids(source)
        locator = str(source.get("locator") or "").strip()
        name = str(source.get("name") or source.get("target") or "").strip()
        target = str(source.get("target") or name).strip()

        if "bilibili_dynamic" in site_ids and locator:
            bilibili_uids.append(locator)
            bilibili_names.append(target or name or f"Bilibili {locator}")
        if WEWE_RSS_SITE_ID in site_ids and locator:
            wewe_feeds.append(f"{target or name or locator}:{locator}")
        if "opmlrss" in site_ids and locator:
            opml_path = locator
        if MEDIACRAWLER_DOUYIN_SITE_ID in site_ids:
            applied_env.append("MEDIACRAWLER_DOUYIN_ENABLED")
            os.environ["MEDIACRAWLER_DOUYIN_ENABLED"] = "1"
            if set_env_from_source_config("MEDIACRAWLER_DOUYIN_JSONL", locator):
                applied_env.append("MEDIACRAWLER_DOUYIN_JSONL")
            if set_env_from_source_config("MEDIACRAWLER_DOUYIN_SOURCE_NAME", target or name):
                applied_env.append("MEDIACRAWLER_DOUYIN_SOURCE_NAME")
        if MEDIACRAWLER_XHS_SITE_ID in site_ids:
            applied_env.append("MEDIACRAWLER_XHS_ENABLED")
            os.environ["MEDIACRAWLER_XHS_ENABLED"] = "1"
            if set_env_from_source_config("MEDIACRAWLER_XHS_JSONL", locator):
                applied_env.append("MEDIACRAWLER_XHS_JSONL")
            if set_env_from_source_config("MEDIACRAWLER_XHS_SOURCE_NAME", target or name):
                applied_env.append("MEDIACRAWLER_XHS_SOURCE_NAME")

    if bilibili_uids:
        os.environ["BILIBILI_DYNAMIC_ENABLED"] = "1"
        os.environ["BILIBILI_DYNAMIC_UIDS"] = ",".join(bilibili_uids)
        os.environ["BILIBILI_DYNAMIC_SOURCE_NAMES"] = ",".join(bilibili_names)
        applied_env.extend(["BILIBILI_DYNAMIC_ENABLED", "BILIBILI_DYNAMIC_UIDS", "BILIBILI_DYNAMIC_SOURCE_NAMES"])
    if WEWE_RSS_SITE_ID in enabled_site_ids:
        os.environ["WEWE_RSS_ENABLED"] = "1"
        applied_env.append("WEWE_RSS_ENABLED")
        if wewe_feeds:
            os.environ["WEWE_RSS_FEEDS"] = ";".join(wewe_feeds)
            applied_env.append("WEWE_RSS_FEEDS")
    if "xapi" in enabled_site_ids:
        os.environ["X_API_ENABLED"] = "1"
        applied_env.append("X_API_ENABLED")
    if "socialdata_x" in enabled_site_ids:
        os.environ["SOCIALDATA_ENABLED"] = "1"
        applied_env.append("SOCIALDATA_ENABLED")
    if enabled_site_ids.intersection({"tikhub_douyin", "tikhub_xiaohongshu"}):
        os.environ["TIKHUB_ENABLED"] = "1"
        applied_env.append("TIKHUB_ENABLED")
    if "agentmail" in enabled_site_ids:
        os.environ["EMAIL_DIGEST_ENABLED"] = "1"
        applied_env.append("EMAIL_DIGEST_ENABLED")

    return {
        "enabled_source_count": len(enabled_sources),
        "enabled_site_ids": sorted(enabled_site_ids),
        "applied_env": sorted(set(applied_env)),
        "rss_opml": opml_path,
    }


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


def event_time(record: dict[str, Any]) -> datetime | None:
    # RSS sources must rely on the source's publish time only.
    # first_seen_at is fetch time and would falsely mark historical items as "24h".
    if str(record.get("site_id") or "") == "opmlrss":
        return parse_iso(record.get("published_at"))
    return parse_iso(record.get("published_at")) or parse_iso(record.get("first_seen_at"))


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


def contains_any_keyword(haystack: str, keywords: list[str]) -> bool:
    h = haystack.lower()
    return any(k in h for k in keywords)


def contains_meaningful_ai_signal(haystack: str) -> bool:
    h = haystack.lower()
    if MEANINGFUL_EN_SIGNAL_RE.search(h):
        return True
    return any(k in h for k in AI_KEYWORDS if k not in BROAD_AI_TERMS)


def redact_public_text(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    text = EMAIL_RE.sub("[redacted-email]", text)
    text = URL_IN_TEXT_RE.sub(lambda match: normalize_url(match.group(0)), text)
    return SECRET_LIKE_RE.sub("[redacted-secret]", text)


def sanitize_public_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_public_text(value)
    if isinstance(value, list):
        return [sanitize_public_value(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_public_value(val) for key, val in value.items()}
    return value


def sanitize_public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return sanitize_public_value(payload)


def compact_public_snippet(text: str, max_chars: int = 240) -> str:
    """Return a short redacted snippet suitable for public/static JSON."""
    snippet = re.sub(r"\s+", " ", str(text or "")).strip()
    snippet = redact_public_text(snippet)
    if len(snippet) <= max_chars:
        return snippet
    return snippet[: max_chars - 1].rstrip() + "…"


def sender_domain_from_address(raw_sender: str) -> str | None:
    """Extract only the sender domain; never expose the raw email address."""
    _, email_addr = parseaddr(str(raw_sender or ""))
    if "@" not in email_addr:
        return None
    domain = email_addr.rsplit("@", 1)[-1].strip().lower().strip(">")
    return domain or None


def parse_domain_filter(raw: str) -> list[str]:
    """Parse a comma-separated sender-domain allowlist for private newsletter demos."""
    domains: list[str] = []
    for part in re.split(r"[,\s]+", str(raw or "")):
        domain = part.strip().lower().lstrip("@")
        if domain and re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", domain):
            domains.append(domain)
    return sorted(set(domains))


def domain_matches_filter(sender_domain: str | None, allowed_domains: list[str]) -> bool:
    if not allowed_domains:
        return True
    domain = str(sender_domain or "").lower().strip()
    return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in allowed_domains)


def filter_agentmail_messages_by_domain(
    messages: list[dict[str, Any]],
    allowed_domains: list[str],
) -> list[dict[str, Any]]:
    if not allowed_domains:
        return messages
    return [
        msg
        for msg in messages
        if domain_matches_filter(sender_domain_from_address(str(msg.get("from") or "")), allowed_domains)
    ]


def safe_agentmail_item(message: dict[str, Any]) -> dict[str, Any]:
    """Convert an AgentMail MessageItem into a metadata-only public digest item."""
    message_id = str(message.get("message_id") or "")
    stable_id = hashlib.sha1(message_id.encode("utf-8")).hexdigest()[:12] if message_id else "unknown"
    domain = sender_domain_from_address(str(message.get("from") or ""))
    attachments = message.get("attachments") or []
    return {
        "id": f"agentmail:{stable_id}",
        "source_type": "email_newsletter",
        "source": f"AgentMail · {domain}" if domain else "AgentMail",
        "sender_domain": domain,
        "subject": compact_public_snippet(str(message.get("subject") or ""), max_chars=180),
        "preview": compact_public_snippet(str(message.get("preview") or ""), max_chars=240),
        "received_at": message.get("timestamp") or message.get("created_at"),
        "has_attachments": bool(attachments),
        "attachment_count": len(attachments) if isinstance(attachments, list) else 0,
    }


def build_agentmail_digest_payload(
    messages: list[dict[str, Any]],
    generated_at: str,
    window_hours: int,
    allowed_sender_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Build a privacy-preserving digest from AgentMail list-message results."""
    filtered_messages = filter_agentmail_messages_by_domain(messages, allowed_sender_domains or [])
    items = [safe_agentmail_item(msg) for msg in filtered_messages]
    return sanitize_public_payload(
        {
            "generated_at": generated_at,
            "source": "agentmail",
            "enabled": True,
            "window_hours": window_hours,
            "privacy": "metadata_only_no_body",
            "allowed_sender_domains": allowed_sender_domains or [],
            "total_messages": len(items),
            "items": items,
        }
    )


def fetch_agentmail_digest(
    session: requests.Session,
    api_key: str,
    inbox_id: str,
    generated_at: str,
    after: str,
    limit: int = AGENTMAIL_DEFAULT_LIMIT,
    base_url: str = AGENTMAIL_API_BASE_DEFAULT,
    window_hours: int = 24,
    allowed_sender_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch AgentMail MessageItem metadata; deliberately does not request bodies or raw .eml."""
    base = (base_url or AGENTMAIL_API_BASE_DEFAULT).rstrip("/")
    url = f"{base}/v0/inboxes/{inbox_id}/messages"
    response = session.get(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        params={
            "limit": max(1, min(int(limit or AGENTMAIL_DEFAULT_LIMIT), 100)),
            "after": after,
            "ascending": "false",
            "include_spam": "false",
            "include_trash": "false",
            "include_blocked": "false",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    messages = payload.get("messages") if isinstance(payload, dict) else []
    if not isinstance(messages, list):
        messages = []
    return build_agentmail_digest_payload(
        messages,
        generated_at=generated_at,
        window_hours=window_hours,
        allowed_sender_domains=allowed_sender_domains,
    )


def env_flag(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def env_flag_default(name: str, default: bool) -> bool:
    """Three-state toggle: unset/blank -> default; explicit truthy/falsey wins.

    Used for the *_ENABLED switches so API-key presence is the primary driver
    (key in env -> source runs) while ENABLED stays available as an explicit
    kill switch: set it to 0/false/no/off to force a paid source off even when a
    key is present."""
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name) or default).strip() or default)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name) or default).strip() or default)
    except ValueError:
        return default


def load_paid_source_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        sources = {}
    return {"schema_version": 1, "sources": sources}


def paid_source_interval_hours(prefix: str) -> int:
    default = PAID_SOURCE_DEFAULT_INTERVAL_HOURS_BY_PREFIX.get(prefix, PAID_SOURCE_DEFAULT_INTERVAL_HOURS)
    interval = env_int(f"{prefix}_RUN_INTERVAL_HOURS", default)
    return max(1, min(interval, PAID_SOURCE_MAX_INTERVAL_HOURS))


def paid_source_state_entry(state: dict[str, Any] | None, source_key: str) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    sources = state.get("sources")
    if not isinstance(sources, dict):
        return {}
    entry = sources.get(source_key)
    return entry if isinstance(entry, dict) else {}


def paid_source_run_gate(
    prefix: str,
    source_key: str,
    now: datetime,
    state: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    if env_flag(f"{prefix}_FORCE_RUN"):
        return True, None

    current = now.astimezone(UTC)
    interval_hours = paid_source_interval_hours(prefix)
    entry = paid_source_state_entry(state, source_key)
    last_run = parse_iso(str(entry.get("last_run_at") or ""))
    if last_run:
        due_at = last_run.astimezone(UTC) + timedelta(hours=interval_hours)
        if current < due_at:
            return False, f"before_{source_key}_run_interval"
        return True, None

    run_hour = max(0, min(env_int(f"{prefix}_RUN_UTC_HOUR", 0), 23))
    minute_max = max(0, min(env_int(f"{prefix}_RUN_UTC_MINUTE_MAX", 10), 59))
    if current.hour == run_hour and current.minute <= minute_max:
        return True, None
    return False, f"outside_{source_key}_initial_window"


def update_paid_source_state(
    state: dict[str, Any],
    source_key: str,
    status: dict[str, Any],
    now: datetime,
) -> None:
    if not status.get("attempted"):
        return
    sources = state.setdefault("sources", {})
    if not isinstance(sources, dict):
        sources = {}
        state["sources"] = sources
    entry = sources.setdefault(source_key, {})
    if not isinstance(entry, dict):
        entry = {}
        sources[source_key] = entry
    entry["last_run_at"] = iso(now)
    entry["last_ok"] = bool(status.get("ok"))
    entry["last_item_count"] = int(status.get("item_count") or 0)
    if status.get("ok"):
        entry["last_success_at"] = iso(now)
        entry.pop("last_error", None)
    elif status.get("error"):
        entry["last_error"] = status.get("error")


def sync_paid_source_status_timestamps(
    status: dict[str, Any],
    state: dict[str, Any],
    source_key: str,
) -> None:
    """Keep the published status aligned with the state used by the run gate."""
    entry = paid_source_state_entry(state, source_key)
    status["last_run_at"] = entry.get("last_run_at")
    status["last_success_at"] = entry.get("last_success_at")


def split_env_list(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;\n]+", str(value or "")) if part.strip()]


def bilibili_dynamic_accounts_from_env() -> list[dict[str, str]]:
    uid_list = split_env_list(str(os.environ.get("BILIBILI_DYNAMIC_UIDS") or ""))
    if uid_list:
        source_names = split_env_list(str(os.environ.get("BILIBILI_DYNAMIC_SOURCE_NAMES") or ""))
        return [
            {
                "uid": uid,
                "source_name": source_names[index] if index < len(source_names) else f"Bilibili {uid}",
            }
            for index, uid in enumerate(uid_list)
        ]

    single_uid = str(os.environ.get("BILIBILI_DYNAMIC_UID") or "").strip()
    if single_uid:
        return [
            {
                "uid": single_uid,
                "source_name": str(
                    os.environ.get("BILIBILI_DYNAMIC_SOURCE_NAME")
                    or f"Bilibili {single_uid}"
                ).strip(),
            }
        ]

    return [
        {"uid": uid, "source_name": source_name}
        for uid, source_name in BILIBILI_DYNAMIC_DEFAULT_ACCOUNTS
    ]


def bilibili_dynamic_status_base() -> dict[str, Any]:
    accounts = bilibili_dynamic_accounts_from_env()
    uids = [account["uid"] for account in accounts if account.get("uid")]
    max_items = max(1, min(env_int("BILIBILI_DYNAMIC_MAX_ITEMS", BILIBILI_DYNAMIC_DEFAULT_MAX_ITEMS), 200))
    max_pages = max(1, min(env_int("BILIBILI_DYNAMIC_MAX_PAGES", BILIBILI_DYNAMIC_DEFAULT_MAX_PAGES), 20))
    cookie_present = bool(bilibili_cookie_header_from_env())
    return {
        "enabled": env_flag("BILIBILI_DYNAMIC_ENABLED"),
        "ok": None,
        "item_count": 0,
        "uid": ",".join(uids),
        "uids": uids,
        "uid_count": len(uids),
        "accounts": accounts,
        "max_items": max_items,
        "max_items_per_account": max_items,
        "max_pages": max_pages,
        "source_kind": "bilibili_dynamic",
        "cookie_present": cookie_present,
        "privacy": "cookie_env_only_not_logged",
        "coverage_note": "tries_cookie_full_dynamic_then_public_opus_fallback",
    }


def bilibili_dynamic_item_title(content: str, opus_id: str) -> str:
    text = re.sub(r"\s+", " ", (content or "").strip())
    if not text:
        return f"B站动态 {opus_id}".strip()
    if len(text) > 90:
        text = text[:87].rstrip() + "..."
    return text


def apply_cookie_header(session: requests.Session, cookie_header: str) -> None:
    for part in str(cookie_header or "").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            session.cookies.set(name, value, domain=".bilibili.com")


def bilibili_cookie_header_from_file_text(cookie_text: str, now_ts: int | None = None) -> str:
    now_ts = now_ts or int(time.time())
    cookies: dict[str, str] = {}

    def keep_cookie(name: str, value: str, domain: str = "", expires: Any = None) -> None:
        if not name or value is None:
            return
        if domain and "bilibili.com" not in domain:
            return
        try:
            exp = float(expires) if expires not in (None, "") else 0
            if exp > 20_000_000_000:
                exp = exp / 1000
            if exp > 0 and exp < now_ts:
                return
        except (TypeError, ValueError):
            pass
        cookies[str(name).strip()] = str(value).strip()

    text = str(cookie_text or "").strip()
    if not text:
        return ""

    try:
        payload = json.loads(text)
        raw_items = payload.get("cookies") if isinstance(payload, dict) else payload
        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                keep_cookie(
                    str(item.get("name") or ""),
                    str(item.get("value") or ""),
                    str(item.get("domain") or ""),
                    item.get("expirationDate") or item.get("expires") or item.get("expiry"),
                )
            if cookies:
                return "; ".join(f"{name}={value}" for name, value in cookies.items())
    except json.JSONDecodeError:
        pass

    # Netscape cookie.txt format: domain, include_subdomains, path, secure,
    # expiry, name, value separated by tabs.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#HttpOnly_"):
            stripped = stripped[len("#HttpOnly_") :]
        elif stripped.startswith("#"):
            continue
        parts = stripped.split("\t")
        if len(parts) >= 7:
            keep_cookie(parts[5], parts[6], parts[0], parts[4])
    if cookies:
        return "; ".join(f"{name}={value}" for name, value in cookies.items())

    if "=" in text:
        return text
    return ""


def bilibili_cookie_header_from_env() -> str:
    cookie = str(os.environ.get("BILIBILI_COOKIE") or os.environ.get("BILIBILI_DYNAMIC_COOKIE") or "").strip()
    if cookie:
        return bilibili_cookie_header_from_file_text(cookie).strip() or cookie
    cookie_file = str(os.environ.get("BILIBILI_COOKIE_FILE") or os.environ.get("BILIBILI_DYNAMIC_COOKIE_FILE") or "").strip()
    if not cookie_file:
        return ""
    try:
        return bilibili_cookie_header_from_file_text(Path(cookie_file).read_text(encoding="utf-8", errors="ignore")).strip()
    except OSError:
        return ""


def bilibili_mixin_key(img_key: str, sub_key: str) -> str:
    raw = f"{img_key}{sub_key}"
    return "".join(raw[i] for i in BILIBILI_WBI_MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def bilibili_wbi_keys(session: requests.Session) -> tuple[str, str]:
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.bilibili.com/",
    }
    resp = session.get(BILIBILI_NAV_API_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"bilibili_nav_code_{payload.get('code')}")
    wbi_img = data.get("wbi_img")
    if not isinstance(wbi_img, dict):
        raise ValueError("bilibili_nav_missing_wbi_img")
    img_key = str(wbi_img.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
    sub_key = str(wbi_img.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
    if not (img_key and sub_key):
        raise ValueError("bilibili_nav_missing_wbi_keys")
    return img_key, sub_key


def sign_bilibili_wbi_params(params: dict[str, Any], img_key: str, sub_key: str, now_ts: int | None = None) -> dict[str, str]:
    signed = {k: str(v) for k, v in params.items() if v is not None}
    signed["wts"] = str(now_ts or int(time.time()))
    cleaned = {
        k: re.sub(r"[!'()*]", "", v)
        for k, v in signed.items()
    }
    query = urlencode(sorted(cleaned.items()))
    cleaned["w_rid"] = hashlib.md5(f"{query}{bilibili_mixin_key(img_key, sub_key)}".encode("utf-8")).hexdigest()
    return cleaned


def first_text_value(obj: Any, keys: tuple[str, ...] = ("text", "title", "desc", "content")) -> str:
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in obj.values():
            found = first_text_value(value, keys)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = first_text_value(value, keys)
            if found:
                return found
    return ""


def parse_bilibili_full_dynamic_items(
    payload: dict[str, Any],
    *,
    now: datetime,
    uid: str,
    source_name: str,
    max_items: int,
) -> list[RawItem]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return []

    out: list[RawItem] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        dynamic_id = str(item.get("id_str") or item.get("id") or "").strip()
        modules = item.get("modules") if isinstance(item.get("modules"), dict) else {}
        author = modules.get("module_author") if isinstance(modules.get("module_author"), dict) else {}
        dynamic = modules.get("module_dynamic") if isinstance(modules.get("module_dynamic"), dict) else {}
        major = dynamic.get("major") if isinstance(dynamic.get("major"), dict) else {}

        published = parse_unix_timestamp(author.get("pub_ts"))
        dyn_type = str(item.get("type") or "").strip()
        content = first_text_value(dynamic) or first_text_value(item)

        url = ""
        if isinstance(major, dict):
            url = str(major.get("jump_url") or "").strip()
            if not url:
                for value in major.values():
                    if isinstance(value, dict) and value.get("jump_url"):
                        url = str(value.get("jump_url") or "").strip()
                        break
        if not url and dynamic_id:
            url = f"https://t.bilibili.com/{dynamic_id}"
        url = urljoin("https://www.bilibili.com", url)
        if not url or not content:
            continue
        key = dynamic_id or normalize_url(url)
        if key in seen:
            continue
        seen.add(key)

        out.append(
            RawItem(
                site_id="bilibili_dynamic",
                site_name="Bilibili Dynamic",
                source=source_name,
                title=bilibili_dynamic_item_title(content, dynamic_id),
                url=url,
                published_at=published or now,
                meta={
                    "summary": content,
                    "bilibili_uid": uid,
                    "bilibili_dynamic_id": dynamic_id,
                    "bilibili_dynamic_type": dyn_type,
                    "timestamp_source": "bilibili_pub_ts" if published else "fetch_time",
                },
            )
        )
        if len(out) >= max_items:
            break
    return out


def parse_bilibili_dynamic_items(
    payload: dict[str, Any],
    *,
    now: datetime,
    uid: str,
    source_name: str,
    max_items: int,
) -> list[RawItem]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return []

    out: list[RawItem] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        opus_id = str(item.get("opus_id") or "").strip()
        content = str(item.get("content") or "").strip()
        jump_url = str(item.get("jump_url") or "").strip()
        if not opus_id and not jump_url:
            continue
        url = urljoin("https://www.bilibili.com", jump_url or f"/opus/{opus_id}")
        key = opus_id or normalize_url(url)
        if key in seen:
            continue
        seen.add(key)

        stat = item.get("stat")
        like_count = None
        if isinstance(stat, dict):
            like_count = stat.get("like")
        cover = item.get("cover") if isinstance(item.get("cover"), dict) else {}

        out.append(
            RawItem(
                site_id="bilibili_dynamic",
                site_name="Bilibili Dynamic",
                source=source_name,
                title=bilibili_dynamic_item_title(content, opus_id),
                url=url,
                # This public endpoint does not expose a reliable publish time.
                # Use first_seen_at in the archive as the refresh time instead.
                published_at=None,
                meta={
                    "summary": content,
                    "creator_metrics": {"like_count": like_count} if like_count is not None else None,
                    "bilibili_uid": uid,
                    "bilibili_opus_id": opus_id,
                    "cover_url": cover.get("url") if isinstance(cover, dict) else None,
                    "timestamp_source": "first_seen_at",
                },
            )
        )
        if len(out) >= max_items:
            break
    return out


def fetch_bilibili_dynamic(
    session: requests.Session,
    now: datetime,
    *,
    uid: str,
    source_name: str,
    max_items: int,
    api_url: str = BILIBILI_DYNAMIC_API_URL,
) -> list[RawItem]:
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://space.bilibili.com",
        "Referer": f"https://space.bilibili.com/{uid}/dynamic",
    }
    resp = session.get(
        api_url,
        params={
            "host_mid": uid,
            "page": 1,
            "type": "all",
            "web_location": "333.1387",
        },
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if int(payload.get("code") or 0) != 0:
        raise ValueError(f"bilibili_dynamic_api_code_{payload.get('code')}")
    items = parse_bilibili_dynamic_items(
        payload,
        now=now,
        uid=uid,
        source_name=source_name,
        max_items=max_items,
    )
    if not items:
        raise ValueError("bilibili_dynamic_no_items")
    return items


def fetch_bilibili_full_dynamic(
    session: requests.Session,
    now: datetime,
    *,
    uid: str,
    source_name: str,
    max_items: int,
    max_pages: int = 1,
    api_url: str = BILIBILI_DYNAMIC_FULL_API_URL,
) -> list[RawItem]:
    img_key, sub_key = bilibili_wbi_keys(session)
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://space.bilibili.com",
        "Referer": f"https://space.bilibili.com/{uid}/dynamic",
    }
    out: list[RawItem] = []
    seen: set[str] = set()
    offset = ""
    for page_index in range(max(1, max_pages)):
        raw_params: dict[str, Any] = {
            "host_mid": uid,
            "timezone_offset": -480,
            "features": "itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,decorationCard,forwardListHidden,ugcDelete",
            "web_location": "333.1387",
        }
        if offset:
            raw_params["offset"] = offset
        params = sign_bilibili_wbi_params(raw_params, img_key, sub_key)
        resp = session.get(api_url, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        if int(payload.get("code") or 0) != 0:
            raise ValueError(f"bilibili_full_dynamic_api_code_{payload.get('code')}")

        remaining = max_items - len(out)
        items = parse_bilibili_full_dynamic_items(
            payload,
            now=now,
            uid=uid,
            source_name=source_name,
            max_items=remaining,
        )
        for item in items:
            key = str(item.meta.get("bilibili_dynamic_id") if isinstance(item.meta, dict) else "") or normalize_url(item.url)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        if len(out) >= max_items:
            break

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not data.get("has_more"):
            break
        next_offset = str(data.get("offset") or "").strip()
        if not next_offset or next_offset == offset:
            break
        offset = next_offset
        if page_index + 1 < max_pages:
            time.sleep(0.25)

    if not out:
        raise ValueError("bilibili_full_dynamic_no_items")
    return out


def maybe_fetch_bilibili_dynamic(
    session: requests.Session,
    now: datetime,
) -> tuple[list[RawItem], dict[str, Any]]:
    status = bilibili_dynamic_status_base()
    if not status["enabled"]:
        status["disabled_reason"] = "disabled_by_toggle"
        return [], status
    accounts = [
        account
        for account in status.get("accounts", [])
        if isinstance(account, dict) and str(account.get("uid") or "").strip()
    ]
    if not accounts:
        status["ok"] = False
        status["error"] = "missing_bilibili_dynamic_uid"
        return [], status

    api_url = str(os.environ.get("BILIBILI_DYNAMIC_API_URL") or BILIBILI_DYNAMIC_API_URL).strip()
    full_api_url = str(os.environ.get("BILIBILI_DYNAMIC_FULL_API_URL") or BILIBILI_DYNAMIC_FULL_API_URL).strip()
    cookie = bilibili_cookie_header_from_env()
    status["source_name"] = ", ".join(str(account.get("source_name") or account["uid"]) for account in accounts)
    status["attempted"] = True
    start = time.perf_counter()
    try:
        if cookie:
            apply_cookie_header(session, cookie)

        all_items: list[RawItem] = []
        account_statuses: list[dict[str, Any]] = []
        for account in accounts:
            uid = str(account.get("uid") or "").strip()
            source_name = str(account.get("source_name") or f"Bilibili {uid}").strip()
            account_status: dict[str, Any] = {
                "uid": uid,
                "source_name": source_name,
                "ok": False,
                "item_count": 0,
            }
            try:
                errors: list[str] = []
                if cookie:
                    try:
                        items = fetch_bilibili_full_dynamic(
                            session,
                            now,
                            uid=uid,
                            source_name=source_name,
                            max_items=int(status["max_items_per_account"]),
                            max_pages=int(status["max_pages"]),
                            api_url=full_api_url,
                        )
                        account_status["fetch_mode"] = "cookie_full_dynamic"
                        account_status["ok"] = True
                        account_status["item_count"] = len(items)
                        all_items.extend(items)
                        account_statuses.append(account_status)
                        continue
                    except Exception as exc:
                        errors.append(f"cookie_full_dynamic_failed:{type(exc).__name__}")

                items = fetch_bilibili_dynamic(
                    session,
                    now,
                    uid=uid,
                    source_name=source_name,
                    max_items=int(status["max_items_per_account"]),
                    api_url=api_url,
                )
                account_status["fetch_mode"] = "public_opus_fallback" if errors else "public_opus"
                if errors:
                    account_status["fallback_reason"] = errors[-1]
                account_status["ok"] = True
                account_status["item_count"] = len(items)
                all_items.extend(items)
            except Exception as exc:
                account_status["error"] = str(exc)
            account_statuses.append(account_status)

        status["accounts"] = account_statuses
        status["item_count"] = len(all_items)
        successful_accounts = [account for account in account_statuses if account.get("ok")]
        failed_accounts = [account for account in account_statuses if not account.get("ok")]
        status["ok"] = bool(successful_accounts)
        status["partial_failure_count"] = len(failed_accounts) if successful_accounts else 0

        fetch_modes = sorted(
            {
                str(account.get("fetch_mode"))
                for account in successful_accounts
                if account.get("fetch_mode")
            }
        )
        if len(fetch_modes) == 1:
            status["fetch_mode"] = fetch_modes[0]
        elif fetch_modes:
            status["fetch_mode"] = "mixed"
        fallback_reasons = [
            f"{account.get('uid')}:{account.get('fallback_reason')}"
            for account in account_statuses
            if account.get("fallback_reason")
        ]
        if fallback_reasons:
            status["fallback_reason"] = "; ".join(fallback_reasons)
        if not successful_accounts:
            status["error"] = "; ".join(
                f"{account.get('uid')}:{account.get('error') or 'no_items'}"
                for account in failed_accounts
            ) or "bilibili_dynamic_no_items"
        return all_items, status
    except Exception as exc:
        status["ok"] = False
        status["error"] = str(exc)
        return [], status
    finally:
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)


def mediacrawler_douyin_title(text: str, aweme_id: str) -> str:
    title = re.sub(r"\s+", " ", (text or "").strip())
    if not title:
        return f"抖音作品 {aweme_id}".strip()
    if len(title) > 90:
        title = title[:87].rstrip() + "..."
    return title


def mediacrawler_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def mediacrawler_xhs_title(text: str, note_id: str) -> str:
    title = re.sub(r"\s+", " ", (text or "").strip())
    if not title:
        return f"小红书笔记 {note_id}".strip()
    if len(title) > 90:
        title = title[:87].rstrip() + "..."
    return title


def mediacrawler_env_first(*names: str) -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def mediacrawler_env_flag_any(*names: str) -> bool:
    return any(env_flag(name) for name in names)


def mediacrawler_env_int_any(default: int, *names: str) -> int:
    for name in names:
        if str(os.environ.get(name) or "").strip():
            return env_int(name, default)
    return default


def parse_mediacrawler_douyin_jsonl(
    text: str,
    *,
    now: datetime,
    source_name: str = "",
    max_items: int | None = None,
) -> list[RawItem]:
    out: list[RawItem] = []
    seen: set[str] = set()
    for line in str(text or "").splitlines():
        raw_line = line.strip()
        if not raw_line:
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue

        aweme_id = first_non_empty(row.get("aweme_id"), row.get("id"))
        content = first_non_empty(row.get("desc"), row.get("title"))
        url = first_non_empty(row.get("aweme_url"), row.get("share_url"), row.get("url"))
        if not url and aweme_id:
            url = f"https://www.douyin.com/video/{aweme_id}"
        if not url.startswith("http") or not (content or aweme_id):
            continue

        key = aweme_id or normalize_url(url)
        if key in seen:
            continue
        seen.add(key)

        creator = first_non_empty(
            source_name,
            row.get("nickname"),
            row.get("user_nickname"),
            row.get("user_unique_id"),
            row.get("sec_user_id"),
            "Douyin Creator",
        )
        published = (
            parse_unix_timestamp(row.get("create_time"))
            or parse_unix_timestamp(row.get("create_timestamp"))
            or parse_date_any(row.get("publish_time"), now)
        )
        metrics = {
            "likes": mediacrawler_int(first_non_empty(row.get("liked_count"), row.get("digg_count"))),
            "collects": mediacrawler_int(first_non_empty(row.get("collected_count"), row.get("collect_count"))),
            "comments": mediacrawler_int(row.get("comment_count")),
            "shares": mediacrawler_int(row.get("share_count")),
        }
        sec_user_id = first_non_empty(row.get("sec_user_id"), row.get("user_id"))
        out.append(
            RawItem(
                site_id=MEDIACRAWLER_DOUYIN_SITE_ID,
                site_name=MEDIACRAWLER_DOUYIN_SITE_NAME,
                source=creator,
                title=mediacrawler_douyin_title(content, aweme_id),
                url=url,
                published_at=published or now,
                meta={
                    "summary": content,
                    "creator_metrics": metrics,
                    "search_surface": "mediacrawler_douyin_creator_jsonl",
                    "douyin_aweme_id": aweme_id,
                    "douyin_sec_user_id": sec_user_id,
                },
            )
        )
        if max_items and len(out) >= max_items:
            break
    return out


def maybe_fetch_mediacrawler_douyin(now: datetime) -> tuple[list[RawItem], dict[str, Any]]:
    jsonl_path_raw = str(os.environ.get("MEDIACRAWLER_DOUYIN_JSONL") or "").strip()
    max_items = max(1, min(env_int("MEDIACRAWLER_DOUYIN_MAX_ITEMS", 200), 1000))
    status: dict[str, Any] = {
        "enabled": env_flag("MEDIACRAWLER_DOUYIN_ENABLED"),
        "ok": None,
        "item_count": 0,
        "source_kind": MEDIACRAWLER_DOUYIN_SITE_ID,
        "privacy": "local_jsonl_only_no_cookies",
        "coverage_note": "reads_mediacrawler_douyin_creator_jsonl",
        "jsonl_path_configured": bool(jsonl_path_raw),
        "jsonl_file": Path(jsonl_path_raw).name if jsonl_path_raw else None,
        "max_items": max_items,
    }
    if not status["enabled"]:
        status["disabled_reason"] = "disabled_by_toggle"
        return [], status
    if not jsonl_path_raw:
        status["ok"] = False
        status["error"] = "missing_mediacrawler_douyin_jsonl"
        return [], status

    start = time.perf_counter()
    try:
        jsonl_path = Path(jsonl_path_raw).expanduser()
        if not jsonl_path.exists():
            status["ok"] = False
            status["error"] = "mediacrawler_douyin_jsonl_not_found"
            return [], status
        source_name = str(os.environ.get("MEDIACRAWLER_DOUYIN_SOURCE_NAME") or "").strip()
        items = parse_mediacrawler_douyin_jsonl(
            jsonl_path.read_text(encoding="utf-8", errors="ignore"),
            now=now,
            source_name=source_name,
            max_items=max_items,
        )
        status["ok"] = bool(items)
        status["item_count"] = len(items)
        if source_name:
            status["source_name"] = source_name
        if not items:
            status["error"] = "mediacrawler_douyin_no_items"
        return items, status
    except Exception as exc:
        status["ok"] = False
        status["error"] = str(exc)
        return [], status
    finally:
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)


def parse_mediacrawler_xhs_jsonl(
    text: str,
    *,
    now: datetime,
    source_name: str = "",
    max_items: int | None = None,
) -> list[RawItem]:
    out: list[RawItem] = []
    seen: set[str] = set()
    for line in str(text or "").splitlines():
        raw_line = line.strip()
        if not raw_line:
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue

        note_id = first_non_empty(row.get("note_id"), row.get("id"))
        content = first_non_empty(row.get("title"), row.get("desc"))
        summary = first_non_empty(row.get("desc"), row.get("title"))
        url = first_non_empty(row.get("note_url"), row.get("url"), row.get("share_url"))
        if not url and note_id:
            url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if not url.startswith("http") or not (content or note_id):
            continue

        key = note_id or normalize_url(url)
        if key in seen:
            continue
        seen.add(key)

        creator = first_non_empty(
            source_name,
            row.get("nickname"),
            row.get("user_nickname"),
            row.get("user_id"),
            "Xiaohongshu Creator",
        )
        published = (
            parse_unix_timestamp(row.get("time"))
            or parse_unix_timestamp(row.get("create_time"))
            or parse_unix_timestamp(row.get("last_update_time"))
            or parse_date_any(row.get("publish_time"), now)
        )
        metrics = {
            "likes": mediacrawler_int(row.get("liked_count")),
            "collects": mediacrawler_int(first_non_empty(row.get("collected_count"), row.get("collect_count"))),
            "comments": mediacrawler_int(row.get("comment_count")),
            "shares": mediacrawler_int(row.get("share_count")),
        }
        out.append(
            RawItem(
                site_id=MEDIACRAWLER_XHS_SITE_ID,
                site_name=MEDIACRAWLER_XHS_SITE_NAME,
                source=creator,
                title=mediacrawler_xhs_title(content, note_id),
                url=url,
                published_at=published or now,
                meta={
                    "summary": summary,
                    "creator_metrics": metrics,
                    "search_surface": "mediacrawler_xhs_creator_jsonl",
                    "xiaohongshu_note_id": note_id,
                    "xiaohongshu_user_id": first_non_empty(row.get("user_id"), row.get("sec_user_id")),
                    "xiaohongshu_note_type": first_non_empty(row.get("type"), row.get("note_type")),
                },
            )
        )
        if max_items and len(out) >= max_items:
            break
    return out


def maybe_fetch_mediacrawler_xhs(now: datetime) -> tuple[list[RawItem], dict[str, Any]]:
    jsonl_path_raw = mediacrawler_env_first("MEDIACRAWLER_XHS_JSONL", "MEDIACRAWLER_XIAOHONGSHU_JSONL")
    max_items = max(1, min(mediacrawler_env_int_any(200, "MEDIACRAWLER_XHS_MAX_ITEMS", "MEDIACRAWLER_XIAOHONGSHU_MAX_ITEMS"), 1000))
    status: dict[str, Any] = {
        "enabled": mediacrawler_env_flag_any("MEDIACRAWLER_XHS_ENABLED", "MEDIACRAWLER_XIAOHONGSHU_ENABLED"),
        "ok": None,
        "item_count": 0,
        "source_kind": MEDIACRAWLER_XHS_SITE_ID,
        "privacy": "local_jsonl_only_no_cookies",
        "coverage_note": "reads_mediacrawler_xhs_creator_jsonl",
        "jsonl_path_configured": bool(jsonl_path_raw),
        "jsonl_file": Path(jsonl_path_raw).name if jsonl_path_raw else None,
        "max_items": max_items,
    }
    if not status["enabled"]:
        status["disabled_reason"] = "disabled_by_toggle"
        return [], status
    if not jsonl_path_raw:
        status["ok"] = False
        status["error"] = "missing_mediacrawler_xhs_jsonl"
        return [], status

    start = time.perf_counter()
    try:
        jsonl_path = Path(jsonl_path_raw).expanduser()
        if not jsonl_path.exists():
            status["ok"] = False
            status["error"] = "mediacrawler_xhs_jsonl_not_found"
            return [], status
        source_name = mediacrawler_env_first("MEDIACRAWLER_XHS_SOURCE_NAME", "MEDIACRAWLER_XIAOHONGSHU_SOURCE_NAME")
        items = parse_mediacrawler_xhs_jsonl(
            jsonl_path.read_text(encoding="utf-8", errors="ignore"),
            now=now,
            source_name=source_name,
            max_items=max_items,
        )
        status["ok"] = bool(items)
        status["item_count"] = len(items)
        if source_name:
            status["source_name"] = source_name
        if not items:
            status["error"] = "mediacrawler_xhs_no_items"
        return items, status
    except Exception as exc:
        status["ok"] = False
        status["error"] = str(exc)
        return [], status
    finally:
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)


def maybe_fetch_agentmail_digest(
    session: requests.Session,
    generated_at: str,
    after: str,
    window_hours: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Fetch AgentMail only when explicitly enabled and fully configured."""
    status: dict[str, Any] = {
        "enabled": env_flag("EMAIL_DIGEST_ENABLED"),
        "ok": None,
        "item_count": 0,
        "privacy": "metadata_only_no_body",
        "published_by_default": False,
    }
    if not status["enabled"]:
        return None, status

    agentmail_api_key = str(os.environ.get("AGENTMAIL_API_KEY") or "").strip()
    agentmail_inbox_id = str(os.environ.get("AGENTMAIL_INBOX_ID") or "").strip()
    agentmail_base_url = str(os.environ.get("AGENTMAIL_API_BASE_URL") or AGENTMAIL_API_BASE_DEFAULT).strip()
    agentmail_limit = env_int("AGENTMAIL_LIMIT", AGENTMAIL_DEFAULT_LIMIT)
    allowed_sender_domains = parse_domain_filter(str(os.environ.get("AGENTMAIL_ALLOWED_SENDER_DOMAINS") or ""))
    status["allowed_sender_domains"] = allowed_sender_domains
    if not (agentmail_api_key and agentmail_inbox_id):
        status["ok"] = False
        status["error"] = "missing_agentmail_credentials"
        return None, status

    try:
        payload = fetch_agentmail_digest(
            session,
            api_key=agentmail_api_key,
            inbox_id=agentmail_inbox_id,
            generated_at=generated_at,
            after=after,
            limit=agentmail_limit,
            base_url=agentmail_base_url,
            window_hours=window_hours,
            allowed_sender_domains=allowed_sender_domains,
        )
        status["ok"] = True
        status["item_count"] = int(payload.get("total_messages") or 0)
        return payload, status
    except Exception as exc:
        status["ok"] = False
        status["error"] = type(exc).__name__
        return None, status


def x_api_should_run_now(now: datetime) -> bool:
    """Gate paid X API reads so a 30-minute cron does not spend every run."""
    if env_flag("X_API_FORCE_RUN"):
        return True
    run_hour = max(0, min(env_int("X_API_RUN_UTC_HOUR", 0), 23))
    minute_max = max(0, min(env_int("X_API_RUN_UTC_MINUTE_MAX", 10), 59))
    return now.astimezone(UTC).hour == run_hour and now.astimezone(UTC).minute <= minute_max


def x_api_status_base(now: datetime) -> dict[str, Any]:
    daily_post_limit = max(0, env_int("X_API_DAILY_POST_LIMIT", X_API_DEFAULT_MAX_RESULTS))
    max_results = max(10, min(env_int("X_API_MAX_RESULTS", X_API_DEFAULT_MAX_RESULTS), 100))
    effective_cap = min(max_results, daily_post_limit) if daily_post_limit else 0
    enable_toggle = env_flag_default("X_API_ENABLED", True)
    token_present = bool(
        str(os.environ.get("X_BEARER_TOKEN") or os.environ.get("X_API_BEARER_TOKEN") or "").strip()
    )
    return {
        "enabled": enable_toggle and token_present,
        "enable_toggle": enable_toggle,
        "api_key_present": token_present,
        "ok": None,
        "item_count": 0,
        "privacy": "public_posts_metadata_only",
        "published_by_default": False,
        "official_free_read_quota": False,
        "unit_cost_usd_per_post_read": X_API_POST_READ_COST_USD,
        "daily_post_limit": daily_post_limit,
        "max_results_per_run": max_results,
        "effective_result_cap": effective_cap,
        "estimated_max_cost_usd_per_run": round(effective_cap * X_API_POST_READ_COST_USD, 4),
        "run_utc_hour": max(0, min(env_int("X_API_RUN_UTC_HOUR", 0), 23)),
        "generated_date_utc": now.astimezone(UTC).date().isoformat(),
    }


def fetch_x_api_recent_search(
    session: requests.Session,
    bearer_token: str,
    query: str,
    now: datetime,
    max_results: int,
    base_url: str = X_API_BASE_DEFAULT,
) -> list[RawItem]:
    """Fetch public recent-search Posts from X API v2; no writes and no DMs."""
    query = re.sub(r"\s+", " ", (query or X_API_DEFAULT_QUERY).strip())
    if len(query) > X_API_MAX_QUERY_CHARS:
        raise ValueError("x_query_too_long")
    capped_max_results = max(10, min(int(max_results or X_API_DEFAULT_MAX_RESULTS), 100))
    url = f"{(base_url or X_API_BASE_DEFAULT).rstrip('/')}/2/tweets/search/recent"
    response = session.get(
        url,
        headers={"Authorization": f"Bearer {bearer_token}"},
        params={
            "query": query,
            "max_results": capped_max_results,
            "tweet.fields": "created_at,author_id,public_metrics,lang",
            "expansions": "author_id",
            "user.fields": "username,name,verified",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    users = {
        str(user.get("id")): user
        for user in (payload.get("includes", {}) or {}).get("users", [])
        if isinstance(user, dict) and user.get("id")
    }
    out: list[RawItem] = []
    for post in payload.get("data") or []:
        if not isinstance(post, dict):
            continue
        post_id = str(post.get("id") or "").strip()
        text = compact_public_snippet(str(post.get("text") or ""), max_chars=220)
        if not (post_id and text):
            continue
        user = users.get(str(post.get("author_id") or ""), {})
        username = str(user.get("username") or "i/web").strip() or "i/web"
        published = parse_iso(str(post.get("created_at") or "")) or now
        out.append(
            RawItem(
                site_id="xapi",
                site_name="X API",
                source=f"@{username}",
                title=text,
                url=f"https://x.com/{username}/status/{post_id}",
                published_at=published,
                meta={
                    "post_id": post_id,
                    "lang": post.get("lang"),
                    "public_metrics": post.get("public_metrics") or {},
                },
            )
        )
    return out


def maybe_fetch_x_api_updates(
    session: requests.Session,
    now: datetime,
) -> tuple[list[RawItem], dict[str, Any]]:
    """Fetch X when a bearer token is present and ENABLED is not turned off, then
    only if scheduled and capped. The token is the primary switch; ENABLED is an
    optional kill switch (set it to 0 to force off)."""
    status = x_api_status_base(now)
    if not status["enable_toggle"]:
        status["disabled_reason"] = "disabled_by_toggle"
        return [], status
    if not status["api_key_present"]:
        status["disabled_reason"] = "no_bearer_token"
        return [], status

    if status["effective_result_cap"] < 10:
        status["ok"] = False
        status["error"] = "x_daily_post_limit_below_api_minimum"
        return [], status

    if not x_api_should_run_now(now):
        status["skipped"] = True
        status["skip_reason"] = "outside_x_api_daily_window"
        return [], status

    bearer_token = str(os.environ.get("X_BEARER_TOKEN") or os.environ.get("X_API_BEARER_TOKEN") or "").strip()

    query = str(os.environ.get("X_API_QUERY") or X_API_DEFAULT_QUERY).strip()
    base_url = str(os.environ.get("X_API_BASE_URL") or X_API_BASE_DEFAULT).strip()
    try:
        items = fetch_x_api_recent_search(
            session,
            bearer_token=bearer_token,
            query=query,
            now=now,
            max_results=int(status["effective_result_cap"]),
            base_url=base_url,
        )
        status["ok"] = True
        status["item_count"] = len(items)
        status["estimated_cost_usd"] = round(len(items) * X_API_POST_READ_COST_USD, 4)
        return items, status
    except Exception as exc:
        status["ok"] = False
        status["error"] = type(exc).__name__
        return [], status


def socialdata_should_run_now(now: datetime, paid_source_state: dict[str, Any] | None = None) -> tuple[bool, str | None]:
    """Gate paid SocialData reads so a 30-minute cron does not spend every run."""
    return paid_source_run_gate("SOCIALDATA", "socialdata", now, paid_source_state)


def socialdata_status_base(now: datetime, paid_source_state: dict[str, Any] | None = None) -> dict[str, Any]:
    daily_tweet_limit = max(0, env_int("SOCIALDATA_DAILY_TWEET_LIMIT", SOCIALDATA_DEFAULT_MAX_RESULTS))
    max_results = max(1, min(env_int("SOCIALDATA_MAX_RESULTS", SOCIALDATA_DEFAULT_MAX_RESULTS), 100))
    effective_cap = min(max_results, daily_tweet_limit) if daily_tweet_limit else 0
    state_entry = paid_source_state_entry(paid_source_state, "socialdata")
    enable_toggle = env_flag_default("SOCIALDATA_ENABLED", True)
    api_key_present = bool(str(os.environ.get("SOCIALDATA_API_KEY") or "").strip())
    # The curated KOL list is a SECOND paid path on top of the keyword search,
    # so the per-run cost ceiling must include it (search cap + list cap).
    list_id = str(os.environ.get("SOCIALDATA_LIST_ID") or SOCIALDATA_LIST_ID_DEFAULT).strip()
    list_enabled = bool(list_id) and env_flag_default("SOCIALDATA_LIST_ENABLED", True)
    list_cap = max(0, min(env_int("SOCIALDATA_LIST_MAX_RESULTS", SOCIALDATA_LIST_DEFAULT_MAX_RESULTS), 200)) if list_enabled else 0
    combined_cap = effective_cap + list_cap
    return {
        "enabled": enable_toggle and api_key_present,
        "enable_toggle": enable_toggle,
        "api_key_present": api_key_present,
        "ok": None,
        "item_count": 0,
        "privacy": "public_posts_metadata_only",
        "published_by_default": False,
        "unit_cost_usd_per_tweet_read": SOCIALDATA_TWEET_READ_COST_USD,
        "daily_tweet_limit": daily_tweet_limit,
        "max_results_per_run": max_results,
        "effective_result_cap": effective_cap,
        "search_result_cap": effective_cap,
        "list_result_cap": list_cap,
        "combined_result_cap": combined_cap,
        "recency_days": SOCIALDATA_RECENCY_DAYS,
        "estimated_max_cost_usd_per_run": round(combined_cap * SOCIALDATA_TWEET_READ_COST_USD, 4),
        "run_interval_hours": paid_source_interval_hours("SOCIALDATA"),
        "run_utc_hour": max(0, min(env_int("SOCIALDATA_RUN_UTC_HOUR", 0), 23)),
        "run_utc_minute_max": max(0, min(env_int("SOCIALDATA_RUN_UTC_MINUTE_MAX", 10), 59)),
        "last_run_at": state_entry.get("last_run_at"),
        "last_success_at": state_entry.get("last_success_at"),
        "generated_date_utc": now.astimezone(UTC).date().isoformat(),
    }


def fetch_socialdata_search(
    session: requests.Session,
    api_key: str,
    query: str,
    now: datetime,
    max_results: int,
    search_type: str = "Latest",
    base_url: str = SOCIALDATA_API_BASE_DEFAULT,
) -> tuple[list[RawItem], dict[str, Any]]:
    """Fetch public X search results through SocialData; no writes and no private data."""
    query = re.sub(r"\s+", " ", (query or SOCIALDATA_DEFAULT_QUERY).strip())
    if len(query) > SOCIALDATA_MAX_QUERY_CHARS:
        raise ValueError("socialdata_query_too_long")
    capped_max_results = max(1, min(int(max_results or SOCIALDATA_DEFAULT_MAX_RESULTS), 100))
    effective_search_type = search_type if search_type in {"Latest", "Top"} else "Latest"
    out: list[RawItem] = []
    raw_tweet_count = 0
    response_top_level_keys: list[str] = []
    page_count = 0
    cursor = ""
    seen_cursors: set[str] = set()
    seen_tweet_ids: set[str] = set()
    pagination_error: str | None = None
    while len(out) < capped_max_results:
        params = {
            "query": query,
            "type": effective_search_type,
        }
        if cursor:
            params["cursor"] = cursor
        try:
            response = session.get(
                f"{(base_url or SOCIALDATA_API_BASE_DEFAULT).rstrip('/')}/twitter/search",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
                params=params,
                timeout=30,
            )
            response.raise_for_status()
        except Exception as exc:
            if page_count == 0:
                raise
            pagination_error = type(exc).__name__
            break

        payload = response.json()
        page_count += 1
        if isinstance(payload, dict) and not response_top_level_keys:
            response_top_level_keys = sorted(payload.keys())[:12]
        tweets = payload.get("tweets") if isinstance(payload, dict) else []
        raw_tweet_count += len(tweets) if isinstance(tweets, list) else 0
        for tweet in tweets or []:
            if len(out) >= capped_max_results:
                break
            if not isinstance(tweet, dict):
                continue
            tweet_id = str(tweet.get("id_str") or tweet.get("id") or "").strip()
            text = compact_public_snippet(str(tweet.get("full_text") or tweet.get("text") or ""), max_chars=220)
            if not (tweet_id and text) or tweet_id in seen_tweet_ids:
                continue
            seen_tweet_ids.add(tweet_id)
            user = tweet.get("user") if isinstance(tweet.get("user"), dict) else {}
            username = str(user.get("screen_name") or "i/web").strip().lstrip("@") or "i/web"
            published = parse_iso(str(tweet.get("tweet_created_at") or tweet.get("created_at") or "")) or now
            out.append(
                RawItem(
                    site_id="socialdata_x",
                    site_name="SocialData X",
                    source=f"@{username}",
                    title=text,
                    url=f"https://x.com/{username}/status/{tweet_id}",
                    published_at=published,
                    meta={
                        "post_id": tweet_id,
                        "lang": tweet.get("lang"),
                        "public_metrics": {
                            "reply_count": tweet.get("reply_count"),
                            "retweet_count": tweet.get("retweet_count"),
                            "quote_count": tweet.get("quote_count"),
                            "favorite_count": tweet.get("favorite_count"),
                            "bookmark_count": tweet.get("bookmark_count"),
                            "views_count": tweet.get("views_count"),
                        },
                    },
                )
            )

        next_cursor = str(payload.get("next_cursor") or "").strip() if isinstance(payload, dict) else ""
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    diagnostics = {
        "endpoint": "/twitter/search",
        "search_type": effective_search_type,
        "query_chars": len(query),
        "response_top_level_keys": response_top_level_keys,
        "raw_tweet_count": raw_tweet_count,
        "mapped_tweet_count": len(out),
        "page_count": page_count,
        "cursor_request_count": max(0, page_count - 1),
        "reached_result_cap": len(out) >= capped_max_results,
    }
    if pagination_error:
        diagnostics["pagination_error"] = pagination_error
    if raw_tweet_count == 0:
        diagnostics["empty_reason"] = "no_tweets_returned_by_socialdata"
    elif len(out) == 0:
        diagnostics["empty_reason"] = "tweets_returned_but_none_mapped"
    return out, diagnostics


def fetch_socialdata_list_tweets(
    session: requests.Session,
    api_key: str,
    list_id: str,
    now: datetime,
    max_results: int,
    exclude_handles: set[str] | None = None,
    base_url: str = SOCIALDATA_API_BASE_DEFAULT,
    max_pages: int = SOCIALDATA_LIST_MAX_PAGES,
) -> tuple[list[RawItem], dict[str, Any]]:
    """Pull a curated X list timeline through SocialData, keeping only members'
    own AI posts. Retweets, replies, the excluded owner, and egg-avatar accounts
    are dropped so the list stays a high-signal, bot-free source. Pagination is
    hard-capped at ``max_pages`` so a heavily-filtered list can't bill without
    bound."""
    list_id = str(list_id or "").strip()
    if not list_id:
        raise ValueError("socialdata_list_id_empty")
    capped_max_results = max(1, min(int(max_results or SOCIALDATA_LIST_DEFAULT_MAX_RESULTS), 200))
    exclude = {h.strip().lstrip("@").lower() for h in (exclude_handles or set()) if h.strip()}
    out: list[RawItem] = []
    raw_tweet_count = 0
    skipped = {"retweet_or_reply": 0, "excluded_author": 0, "bot_like": 0, "empty": 0, "duplicate": 0}
    page_count = 0
    cursor = ""
    seen_cursors: set[str] = set()
    seen_tweet_ids: set[str] = set()
    pagination_error: str | None = None
    page_cap = max(1, int(max_pages or 1))
    hit_page_cap = False
    while len(out) < capped_max_results and page_count < page_cap:
        params: dict[str, str] = {}
        if cursor:
            params["cursor"] = cursor
        try:
            response = session.get(
                f"{(base_url or SOCIALDATA_API_BASE_DEFAULT).rstrip('/')}/twitter/list/{list_id}/tweets",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
                params=params,
                timeout=30,
            )
            response.raise_for_status()
        except Exception as exc:
            if page_count == 0:
                raise
            pagination_error = type(exc).__name__
            break

        payload = response.json()
        page_count += 1
        tweets = payload.get("tweets") if isinstance(payload, dict) else []
        raw_tweet_count += len(tweets) if isinstance(tweets, list) else 0
        for tweet in tweets or []:
            if len(out) >= capped_max_results:
                break
            if not isinstance(tweet, dict):
                continue
            tweet_type = str(tweet.get("type") or "tweet").lower()
            if tweet_type not in SOCIALDATA_LIST_ALLOWED_TYPES:
                skipped["retweet_or_reply"] += 1
                continue
            user = tweet.get("user") if isinstance(tweet.get("user"), dict) else {}
            username = str(user.get("screen_name") or "").strip().lstrip("@")
            if username.lower() in exclude:
                skipped["excluded_author"] += 1
                continue
            if user.get("default_profile_image"):
                skipped["bot_like"] += 1
                continue
            tweet_id = str(tweet.get("id_str") or tweet.get("id") or "").strip()
            text = compact_public_snippet(str(tweet.get("full_text") or tweet.get("text") or ""), max_chars=220)
            if not (tweet_id and text and username):
                skipped["empty"] += 1
                continue
            if tweet_id in seen_tweet_ids:
                skipped["duplicate"] += 1
                continue
            seen_tweet_ids.add(tweet_id)
            published = parse_iso(str(tweet.get("tweet_created_at") or tweet.get("created_at") or "")) or now
            out.append(
                RawItem(
                    site_id="socialdata_x",
                    site_name="SocialData X",
                    source=f"@{username}",
                    title=text,
                    url=f"https://x.com/{username}/status/{tweet_id}",
                    published_at=published,
                    meta={
                        "post_id": tweet_id,
                        "via": "list",
                        "list_id": list_id,
                        "tweet_type": tweet_type,
                        "lang": tweet.get("lang"),
                        "public_metrics": {
                            "reply_count": tweet.get("reply_count"),
                            "retweet_count": tweet.get("retweet_count"),
                            "quote_count": tweet.get("quote_count"),
                            "favorite_count": tweet.get("favorite_count"),
                            "bookmark_count": tweet.get("bookmark_count"),
                            "views_count": tweet.get("views_count"),
                        },
                    },
                )
            )

        next_cursor = str(payload.get("next_cursor") or "").strip() if isinstance(payload, dict) else ""
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    hit_page_cap = page_count >= page_cap and len(out) < capped_max_results
    diagnostics = {
        "endpoint": f"/twitter/list/{list_id}/tweets",
        "list_id": list_id,
        "raw_tweet_count": raw_tweet_count,
        "mapped_tweet_count": len(out),
        "page_count": page_count,
        "max_pages": page_cap,
        "hit_page_cap": hit_page_cap,
        "skipped": skipped,
        "excluded_handles": sorted(exclude),
        "reached_result_cap": len(out) >= capped_max_results,
    }
    if pagination_error:
        diagnostics["pagination_error"] = pagination_error
    return out, diagnostics


def maybe_fetch_socialdata_updates(
    session: requests.Session,
    now: datetime,
    paid_source_state: dict[str, Any] | None = None,
) -> tuple[list[RawItem], dict[str, Any]]:
    """Fetch SocialData when an API key is present and ENABLED is not turned off,
    then only if scheduled and capped. The key is the primary switch; ENABLED is
    an optional kill switch (set it to 0 to force off)."""
    status = socialdata_status_base(now, paid_source_state)
    if not status["enable_toggle"]:
        status["disabled_reason"] = "disabled_by_toggle"
        return [], status
    if not status["api_key_present"]:
        status["disabled_reason"] = "no_api_key"
        return [], status

    if status["effective_result_cap"] < 1:
        status["ok"] = False
        status["error"] = "socialdata_daily_tweet_limit_below_minimum"
        return [], status

    should_run, skip_reason = socialdata_should_run_now(now, paid_source_state)
    if not should_run:
        status["skipped"] = True
        status["skip_reason"] = skip_reason or "outside_socialdata_run_window"
        return [], status

    api_key = str(os.environ.get("SOCIALDATA_API_KEY") or "").strip()

    query = str(os.environ.get("SOCIALDATA_QUERY") or SOCIALDATA_DEFAULT_QUERY).strip()
    base_url = str(os.environ.get("SOCIALDATA_API_BASE_URL") or SOCIALDATA_API_BASE_DEFAULT).strip()
    search_type = str(os.environ.get("SOCIALDATA_SEARCH_TYPE") or "Latest").strip() or "Latest"
    list_id = str(os.environ.get("SOCIALDATA_LIST_ID") or SOCIALDATA_LIST_ID_DEFAULT).strip()
    list_enabled = bool(list_id) and str(os.environ.get("SOCIALDATA_LIST_ENABLED", "1")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    list_max_results = max(0, min(env_int("SOCIALDATA_LIST_MAX_RESULTS", SOCIALDATA_LIST_DEFAULT_MAX_RESULTS), 200))
    list_exclude = {
        handle.strip().lstrip("@").lower()
        for handle in str(os.environ.get("SOCIALDATA_LIST_EXCLUDE") or SOCIALDATA_LIST_DEFAULT_EXCLUDE).split(",")
        if handle.strip()
    }
    status["attempted"] = True

    items: list[RawItem] = []
    seen_urls: set[str] = set()
    errors: list[str] = []
    recency_cutoff = now - timedelta(days=SOCIALDATA_RECENCY_DAYS) if SOCIALDATA_RECENCY_DAYS else None
    skipped_stale = 0

    # 1) Broad keyword search: discovers new voices across en/zh.
    try:
        search_items, diagnostics = fetch_socialdata_search(
            session,
            api_key=api_key,
            query=query,
            now=now,
            max_results=int(status["effective_result_cap"]),
            search_type=search_type,
            base_url=base_url,
        )
        status["diagnostics"] = diagnostics
        for item in search_items:
            if recency_cutoff and item.published_at and item.published_at < recency_cutoff:
                skipped_stale += 1
                continue
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            items.append(item)
    except Exception as exc:
        errors.append(f"search:{type(exc).__name__}")

    # 2) Curated list timeline: stably tracks known KOLs by identity, bot-filtered.
    list_item_count = 0
    if list_enabled and list_max_results >= 1:
        try:
            list_items, list_diagnostics = fetch_socialdata_list_tweets(
                session,
                api_key=api_key,
                list_id=list_id,
                now=now,
                max_results=list_max_results,
                exclude_handles=list_exclude,
                base_url=base_url,
            )
            status["list_diagnostics"] = list_diagnostics
            for item in list_items:
                if recency_cutoff and item.published_at and item.published_at < recency_cutoff:
                    skipped_stale += 1
                    continue
                if item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                items.append(item)
                list_item_count += 1
        except Exception as exc:
            errors.append(f"list:{type(exc).__name__}")

    # SocialData bills per tweet READ (raw), not per kept item; the list discards
    # retweets/replies/stale posts, so raw reads exceed mapped items. Cost and the
    # ceiling in socialdata_status_base both track raw reads across BOTH paths.
    search_raw = int((status.get("diagnostics") or {}).get("raw_tweet_count") or 0)
    list_raw = int((status.get("list_diagnostics") or {}).get("raw_tweet_count") or 0)
    status["list_enabled"] = list_enabled
    status["list_item_count"] = list_item_count
    status["search_item_count"] = len(items) - list_item_count
    status["item_count"] = len(items)
    status["recency_days"] = SOCIALDATA_RECENCY_DAYS
    status["skipped_stale_count"] = skipped_stale
    status["raw_reads"] = search_raw + list_raw
    status["estimated_cost_usd"] = round((search_raw + list_raw) * SOCIALDATA_TWEET_READ_COST_USD, 4)
    if errors and not items:
        status["ok"] = False
        status["error"] = ";".join(errors)
    else:
        status["ok"] = True
        if errors:
            status["partial_error"] = ";".join(errors)
    return items, status


def tikhub_should_run_now(now: datetime, paid_source_state: dict[str, Any] | None = None) -> tuple[bool, str | None]:
    """Gate paid TikHub reads so scheduled workflows do not spend every run."""
    return paid_source_run_gate("TIKHUB", "tikhub", now, paid_source_state)


def tikhub_status_base(now: datetime, paid_source_state: dict[str, Any] | None = None) -> dict[str, Any]:
    daily_limit = max(0, env_int("TIKHUB_DAILY_ITEM_LIMIT", TIKHUB_DEFAULT_MAX_RESULTS))
    max_results = max(1, min(env_int("TIKHUB_MAX_RESULTS", TIKHUB_DEFAULT_MAX_RESULTS), 100))
    effective_cap = min(max_results, daily_limit) if daily_limit else 0
    enable_toggle = env_flag_default("TIKHUB_ENABLED", True)
    api_key_present = bool(str(os.environ.get("TIKHUB_API_KEY") or "").strip())
    platforms = [
        part.strip().lower()
        for part in str(os.environ.get("TIKHUB_PLATFORMS") or TIKHUB_DEFAULT_PLATFORMS).split(",")
        if part.strip()
    ]
    state_entry = paid_source_state_entry(paid_source_state, "tikhub")
    return {
        "enabled": enable_toggle and api_key_present,
        "enable_toggle": enable_toggle,
        "api_key_present": api_key_present,
        "enabled_by": "disabled_by_toggle" if not enable_toggle else ("ready" if api_key_present else "no_api_key"),
        "ok": None,
        "item_count": 0,
        "privacy": "public_social_posts_metadata_only",
        "published_by_default": False,
        "billing": "tikhub_charged_request",
        "daily_item_limit": daily_limit,
        "max_results_per_run": max_results,
        "effective_result_cap": effective_cap,
        "platforms": platforms,
        "run_interval_hours": paid_source_interval_hours("TIKHUB"),
        "run_utc_hour": max(0, min(env_int("TIKHUB_RUN_UTC_HOUR", 0), 23)),
        "run_utc_minute_max": max(0, min(env_int("TIKHUB_RUN_UTC_MINUTE_MAX", 10), 59)),
        "last_run_at": state_entry.get("last_run_at"),
        "last_success_at": state_entry.get("last_success_at"),
        "generated_date_utc": now.astimezone(UTC).date().isoformat(),
    }


def iter_nested_dicts(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(value, dict):
        out.append(value)
        for child in value.values():
            out.extend(iter_nested_dicts(child))
    elif isinstance(value, list):
        for child in value:
            out.extend(iter_nested_dicts(child))
    return out


def tikhub_payload_shape(payload: Any) -> dict[str, Any]:
    """Return a sanitized structural summary for debugging API schema drift."""
    dicts = iter_nested_dicts(payload)
    data = payload.get("data") if isinstance(payload, dict) else None
    data_items = data.get("items") if isinstance(data, dict) else None
    data_business = data.get("business_data") if isinstance(data, dict) else None
    sample_nodes: list[dict[str, Any]] = []
    for node in dicts:
        if len(sample_nodes) >= 3:
            break
        keys = sorted(str(key) for key in node.keys())[:16]
        if {"aweme_info", "note_card", "display_title", "desc", "title", "id", "note_id"} & set(keys):
            sample_nodes.append({"keys": keys})
    return {
        "dict_count": len(dicts),
        "data_type": type(data).__name__ if data is not None else None,
        "data_keys": sorted(data.keys())[:16] if isinstance(data, dict) else [],
        "data_items_count": len(data_items) if isinstance(data_items, list) else None,
        "data_business_count": len(data_business) if isinstance(data_business, list) else None,
        "aweme_info_count": sum(1 for node in dicts if isinstance(node.get("aweme_info"), dict)),
        "note_card_count": sum(1 for node in dicts if isinstance(node.get("note_card"), dict)),
        "sample_nodes": sample_nodes,
    }


def parse_epoch_any(value: Any, now: datetime) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        if re.fullmatch(r"\d+(\.\d+)?", text):
            number = float(text)
        else:
            return parse_date_any(text, now)
    if number > 10_000_000_000:
        number = number / 1000
    try:
        return datetime.fromtimestamp(number, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def is_tikhub_generic_audio_title(title: str) -> bool:
    return bool(
        re.fullmatch(
            r"@?.{1,80}(?:创作的原声|的原声|original\s+sound)",
            (title or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def first_tikhub_douyin_title(aweme: dict[str, Any]) -> str:
    share_info = aweme.get("share_info") if isinstance(aweme.get("share_info"), dict) else {}
    candidates = (
        aweme.get("desc"),
        aweme.get("title"),
        aweme.get("caption"),
        share_info.get("share_desc"),
        share_info.get("share_title"),
    )
    for candidate in candidates:
        title = compact_public_snippet(str(candidate or ""), max_chars=220)
        if title and not is_tikhub_generic_audio_title(title):
            return title
    return ""


def parse_tikhub_published_at(record: dict[str, Any], now: datetime, fields: tuple[str, ...]) -> datetime | None:
    for field in fields:
        value = record.get(field)
        published = parse_epoch_any(value, now) or parse_date_any(value, now)
        if published:
            return published
    return None


def parse_xiaohongshu_note_id_published_at(note_id: str, now: datetime) -> datetime | None:
    """Infer Xiaohongshu note creation time from the timestamp prefix in note id."""
    raw = str(note_id or "").strip()
    match = re.match(r"^([0-9a-fA-F]{8})", raw)
    if not match:
        return None
    published = parse_unix_timestamp(int(match.group(1), 16))
    if not published:
        return None
    earliest_supported = datetime(2013, 1, 1, tzinfo=UTC)
    latest_supported = now.astimezone(UTC)
    if published < earliest_supported or published > latest_supported:
        return None
    return published


def is_credible_xiaohongshu_published_at(published: datetime | None, now: datetime) -> bool:
    if not published:
        return False
    return datetime(2013, 1, 1, tzinfo=UTC) <= published <= now.astimezone(UTC)


def creator_metric_count(*values: Any) -> int:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return max(0, int(float(str(value).replace(",", "").strip())))
        except (TypeError, ValueError):
            continue
    return 0


def normalize_creator_metrics(platform: str, *records: dict[str, Any]) -> dict[str, int]:
    merged: dict[str, Any] = {}
    for record in records:
        if isinstance(record, dict):
            merged.update(record)
    if platform == "douyin":
        return {
            "likes": creator_metric_count(merged.get("digg_count"), merged.get("like_count")),
            "comments": creator_metric_count(merged.get("comment_count"), merged.get("comments_count")),
            "collects": creator_metric_count(merged.get("collect_count"), merged.get("collected_count")),
            "shares": creator_metric_count(merged.get("share_count"), merged.get("shared_count")),
        }
    return {
        "likes": creator_metric_count(
            merged.get("liked_count"),
            merged.get("likes_count"),
            merged.get("like_count"),
            merged.get("digg_count"),
        ),
        "comments": creator_metric_count(merged.get("comments_count"), merged.get("comment_count")),
        "collects": creator_metric_count(merged.get("collected_count"), merged.get("collect_count")),
        "shares": creator_metric_count(merged.get("shared_count"), merged.get("share_count")),
    }


def parse_tikhub_douyin_items(payload: dict[str, Any], now: datetime, keyword: str, limit: int) -> list[RawItem]:
    out: list[RawItem] = []
    seen_ids: set[str] = set()
    for node in iter_nested_dicts(payload):
        # TikHub wraps real videos in ``aweme_info``. Walking arbitrary nested
        # dictionaries without this guard also reaches ``music`` objects, whose
        # generic titles look like "@…创作的原声" and are not video titles.
        wrapped_aweme = node.get("aweme_info") if isinstance(node.get("aweme_info"), dict) else None
        aweme = wrapped_aweme or node
        if not isinstance(aweme, dict):
            continue
        post_id = str(aweme.get("aweme_id") or aweme.get("awemeId") or "").strip()
        title = first_tikhub_douyin_title(aweme)
        if not (post_id and title) or post_id in seen_ids:
            continue
        seen_ids.add(post_id)
        author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
        source = str(author.get("nickname") or author.get("unique_id") or "Douyin Search").strip() or "Douyin Search"
        share = first_non_empty(
            aweme.get("share_url"),
            aweme.get("share_info", {}).get("share_url") if isinstance(aweme.get("share_info"), dict) else "",
            f"https://www.douyin.com/video/{post_id}",
        )
        published = parse_tikhub_published_at(
            aweme,
            now,
            (
                "create_time",
                "create_time_stamp",
                "createTime",
                "createTimeStamp",
                "created_at",
                "publish_time",
                "publishTime",
                "publish_timestamp",
                "time",
            ),
        ) or now
        statistics = aweme.get("statistics") if isinstance(aweme.get("statistics"), dict) else {}
        out.append(
            RawItem(
                site_id="tikhub_douyin",
                site_name="TikHub Douyin",
                source=source,
                title=title,
                url=str(share),
                published_at=published,
                meta={
                    "platform": "douyin",
                    "keyword": keyword,
                    "post_id": post_id,
                    "public_metrics": statistics,
                    "creator_metrics": normalize_creator_metrics("douyin", statistics),
                },
            )
        )
        if len(out) >= limit:
            break
    return out


def parse_tikhub_xiaohongshu_items(payload: dict[str, Any], now: datetime, keyword: str, limit: int) -> list[RawItem]:
    out: list[RawItem] = []
    seen_ids: set[str] = set()
    for node in iter_nested_dicts(payload):
        note = next(
            (
                node.get(key)
                for key in ("note_card", "note_info", "note", "note_data", "noteCard")
                if isinstance(node.get(key), dict)
            ),
            node,
        )
        if not isinstance(note, dict):
            continue
        note_id = str(
            note.get("note_id")
            or note.get("noteId")
            or note.get("id")
            or node.get("noteId")
            or node.get("note_id")
            or node.get("id")
            or ""
        ).strip()
        title = compact_public_snippet(
            str(
                note.get("display_title")
                or note.get("displayTitle")
                or note.get("title")
                or note.get("desc")
                or note.get("description")
                or note.get("content")
                or node.get("display_title")
                or node.get("title")
                or node.get("desc")
                or ""
            ),
            max_chars=220,
        )
        if not (note_id and title) or note_id in seen_ids:
            continue
        seen_ids.add(note_id)
        user = next(
            (
                owner
                for owner in (note.get("user"), note.get("user_info"), node.get("user"), node.get("user_info"))
                if isinstance(owner, dict)
            ),
            {},
        )
        source = str(
            user.get("nickname")
            or user.get("nick_name")
            or user.get("nickName")
            or user.get("name")
            or "Xiaohongshu Search"
        ).strip() or "Xiaohongshu Search"
        xsec_token = str(note.get("xsec_token") or node.get("xsec_token") or "").strip()
        url = first_non_empty(
            note.get("url"),
            note.get("share_url"),
            note.get("shareUrl"),
            node.get("url"),
            node.get("share_url"),
            node.get("shareUrl"),
            f"https://www.xiaohongshu.com/explore/{note_id}{'?xsec_token=' + xsec_token if xsec_token else ''}",
        )
        published = parse_tikhub_published_at(
            note,
            now,
            (
                "time",
                "create_time",
                "created_at",
                "last_update_time",
                "createTime",
                "createdAt",
                "lastUpdateTime",
                "publish_time",
                "publishTime",
            ),
        )
        if not is_credible_xiaohongshu_published_at(published, now):
            published = parse_tikhub_published_at(
                node,
                now,
                (
                    "time",
                    "create_time",
                    "created_at",
                    "last_update_time",
                    "createTime",
                    "createdAt",
                    "lastUpdateTime",
                    "publish_time",
                    "publishTime",
                ),
            )
        if not is_credible_xiaohongshu_published_at(published, now):
            published = parse_xiaohongshu_note_id_published_at(note_id, now)
        interact_info = note.get("interact_info") if isinstance(note.get("interact_info"), dict) else {}
        creator_metrics = normalize_creator_metrics("xiaohongshu", node, note, interact_info)
        out.append(
            RawItem(
                site_id="tikhub_xiaohongshu",
                site_name="TikHub Xiaohongshu",
                source=source,
                title=title,
                url=str(url),
                published_at=published,
                meta={
                    "platform": "xiaohongshu",
                    "keyword": keyword,
                    "post_id": note_id,
                    "public_metrics": interact_info or creator_metrics,
                    "creator_metrics": creator_metrics,
                },
            )
        )
        if len(out) >= limit:
            break
    return out


def tikhub_raw_item_key(item: RawItem) -> str:
    post_id = str((item.meta or {}).get("post_id") or "").strip()
    if post_id:
        return f"{item.site_id}:{post_id}"
    return f"{item.site_id}:{normalize_url(item.url)}:{item.title.strip()}"


def fetch_tikhub_search(
    session: requests.Session,
    api_key: str,
    query: str,
    now: datetime,
    max_results: int,
    platforms: list[str],
    base_url: str = TIKHUB_API_BASE_DEFAULT,
) -> tuple[list[RawItem], dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    root = (base_url or TIKHUB_API_BASE_DEFAULT).rstrip("/")
    keywords = [part.strip() for part in query.split(",") if part.strip()]
    if not keywords:
        raise ValueError("tikhub_query_empty")
    if any(len(keyword) > TIKHUB_MAX_QUERY_CHARS for keyword in keywords):
        raise ValueError("tikhub_query_too_long")

    capped_max_results = max(1, min(int(max_results or TIKHUB_DEFAULT_MAX_RESULTS), 100))
    platform_list = []
    for platform in platforms:
        if platform in {"douyin", "xiaohongshu"} and platform not in platform_list:
            platform_list.append(platform)
    out: list[RawItem] = []
    per_platform_cap = max(1, (capped_max_results + max(len(platform_list), 1) - 1) // max(len(platform_list), 1))
    per_keyword_cap = max(1, (per_platform_cap + max(len(keywords), 1) - 1) // max(len(keywords), 1))
    diagnostics: dict[str, Any] = {
        "keywords": keywords,
        "platforms": platform_list,
        "per_keyword_cap": per_keyword_cap,
        "requests": [],
        "successful_request_count": 0,
        "request_error_count": 0,
        "recency_days": TIKHUB_RECENCY_DAYS,
        "skipped_missing_published_at_count": 0,
        "skipped_stale_count": 0,
    }
    seen_item_keys: set[str] = set()
    recency_cutoff = now - timedelta(days=TIKHUB_RECENCY_DAYS) if TIKHUB_RECENCY_DAYS else None

    def append_mapped_items(mapped: list[RawItem], surface: str, remaining: int) -> int:
        appended = 0
        for item in mapped:
            if appended >= remaining:
                break
            # Enforce the exact recency window (the API only has coarse buckets).
            if not item.published_at:
                diagnostics["skipped_missing_published_at_count"] += 1
                continue
            if recency_cutoff and item.published_at and item.published_at < recency_cutoff:
                diagnostics["skipped_stale_count"] += 1
                continue
            key = tikhub_raw_item_key(item)
            if key in seen_item_keys:
                continue
            seen_item_keys.add(key)
            item.meta["search_surface"] = surface
            out.append(item)
            appended += 1
        return appended

    def request_error_info(exc: Exception) -> dict[str, Any]:
        response = getattr(exc, "response", None)
        return {
            "error": type(exc).__name__,
            "status_code": getattr(response, "status_code", None),
        }

    for platform in platform_list:
        platform_count = 0
        for keyword in keywords:
            remaining = min(capped_max_results - len(out), per_platform_cap - platform_count, per_keyword_cap)
            if remaining <= 0:
                break
            if platform == "douyin":
                endpoint = "/api/v1/douyin/search/fetch_general_search_v2"
                request_info = {
                    "platform": platform,
                    "surface": "douyin_general_v2",
                    "endpoint": endpoint,
                    "keyword": keyword,
                }
                try:
                    response = session.post(
                        f"{root}{endpoint}",
                        headers={**headers, "Content-Type": "application/json"},
                        json={
                            "keyword": keyword,
                            "cursor": 0,
                            "sort_type": TIKHUB_DOUYIN_SORT_TYPE,
                            "publish_time": TIKHUB_DOUYIN_PUBLISH_TIME,
                            "filter_duration": "0",
                            "content_type": "0",
                            "search_id": "",
                            "backtrace": "",
                        },
                        timeout=30,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    mapped = parse_tikhub_douyin_items(
                        payload,
                        now=now,
                        keyword=keyword,
                        limit=max(remaining, TIKHUB_RESPONSE_SCAN_LIMIT),
                    )
                    appended = append_mapped_items(mapped, "douyin_general_v2", remaining)
                    platform_count += appended
                    request_info.update(
                        {
                            "mapped_item_count": len(mapped),
                            "appended_item_count": appended,
                            "response_top_level_keys": sorted(payload.keys())[:12] if isinstance(payload, dict) else [],
                            "payload_shape": tikhub_payload_shape(payload),
                        }
                    )
                    diagnostics["successful_request_count"] += 1
                except Exception as exc:
                    diagnostics["request_error_count"] += 1
                    request_info.update(request_error_info(exc))
                diagnostics["requests"].append(request_info)
            else:
                # TikHub documents App V2 as the preferred Xiaohongshu API and
                # Web V3 as the next public web path; scan both because results
                # can differ between mobile and web surfaces.
                xhs_surfaces = (
                    (
                        "xiaohongshu_app_v2",
                        "/api/v1/xiaohongshu/app_v2/search_notes",
                        {
                            "keyword": keyword,
                            "page": 1,
                            "sort_type": TIKHUB_XHS_SORT,
                            "note_type": TIKHUB_XHS_NOTE_TYPE,
                            "time_filter": TIKHUB_XHS_TIME_FILTER,
                            "search_id": "",
                            "search_session_id": "",
                            "source": "explore_feed",
                            "ai_mode": 0,
                        },
                    ),
                    (
                        "xiaohongshu_web_v3",
                        "/api/v1/xiaohongshu/web_v3/fetch_search_notes",
                        {"keyword": keyword, "page": 1, "sort": TIKHUB_XHS_SORT, "note_type": 0},
                    ),
                )
                keyword_count = 0
                for surface, endpoint, params in xhs_surfaces:
                    surface_remaining = min(
                        remaining - keyword_count,
                        capped_max_results - len(out),
                        per_platform_cap - platform_count,
                    )
                    if surface_remaining <= 0:
                        break
                    request_info = {
                        "platform": platform,
                        "surface": surface,
                        "endpoint": endpoint,
                        "keyword": keyword,
                    }
                    try:
                        response = session.get(f"{root}{endpoint}", headers=headers, params=params, timeout=30)
                        response.raise_for_status()
                        payload = response.json()
                        mapped = parse_tikhub_xiaohongshu_items(
                            payload,
                            now=now,
                            keyword=keyword,
                            limit=max(surface_remaining, TIKHUB_RESPONSE_SCAN_LIMIT),
                        )
                        appended = append_mapped_items(mapped, surface, surface_remaining)
                        platform_count += appended
                        keyword_count += appended
                        request_info.update(
                            {
                                "mapped_item_count": len(mapped),
                                "appended_item_count": appended,
                                "response_top_level_keys": sorted(payload.keys())[:12] if isinstance(payload, dict) else [],
                                "payload_shape": tikhub_payload_shape(payload),
                            }
                        )
                        if surface == "xiaohongshu_app_v2" and keyword_count < remaining:
                            request_info["fallback_reason"] = (
                                "no_items_mapped_try_web_v3"
                                if not mapped
                                else "insufficient_recent_items_try_web_v3"
                            )
                        diagnostics["successful_request_count"] += 1
                    except Exception as exc:
                        diagnostics["request_error_count"] += 1
                        request_info.update(request_error_info(exc))
                    diagnostics["requests"].append(request_info)
        if len(out) >= capped_max_results:
            break
    diagnostics["mapped_item_count"] = len(out)
    if diagnostics["request_error_count"] and not diagnostics["successful_request_count"]:
        raise ValueError("tikhub_all_requests_failed")
    return out, diagnostics


def maybe_fetch_tikhub_updates(
    session: requests.Session,
    now: datetime,
    paid_source_state: dict[str, Any] | None = None,
) -> tuple[list[RawItem], dict[str, Any]]:
    """Fetch TikHub when an API key is present and ENABLED is not turned off,
    then only if scheduled and capped. The key is the primary switch; ENABLED is
    an optional kill switch (set it to 0 to force off)."""
    status = tikhub_status_base(now, paid_source_state)
    if not status["enable_toggle"]:
        status["disabled_reason"] = "disabled_by_toggle"
        return [], status
    if not status["api_key_present"]:
        status["disabled_reason"] = "no_api_key"
        return [], status

    if status["effective_result_cap"] < 1:
        status["ok"] = False
        status["error"] = "tikhub_daily_item_limit_below_minimum"
        return [], status

    should_run, skip_reason = tikhub_should_run_now(now, paid_source_state)
    if not should_run:
        status["skipped"] = True
        status["skip_reason"] = skip_reason or "outside_tikhub_run_window"
        return [], status

    api_key = str(os.environ.get("TIKHUB_API_KEY") or "").strip()

    query = str(os.environ.get("TIKHUB_QUERY") or TIKHUB_DEFAULT_QUERY).strip()
    base_url = str(os.environ.get("TIKHUB_API_BASE_URL") or TIKHUB_API_BASE_DEFAULT).strip()
    status["attempted"] = True
    try:
        items, diagnostics = fetch_tikhub_search(
            session,
            api_key=api_key,
            query=query,
            now=now,
            max_results=int(status["effective_result_cap"]),
            platforms=status["platforms"],
            base_url=base_url,
        )
        status["ok"] = True
        status["item_count"] = len(items)
        status["diagnostics"] = diagnostics
        return items, status
    except Exception as exc:
        status["ok"] = False
        status["error"] = type(exc).__name__
        return [], status


def has_mojibake_noise(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"(Ã|Â|â€|æ·|�)", text))


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
            chosen = min(values, key=source_tier_sort_key)
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
) -> list[dict[str, Any]]:
    window_start = now - timedelta(days=window_days) if window_days and window_days > 0 else None
    items: list[dict[str, Any]] = []
    for record in archive.values():
        if not is_subscription_record(record):
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
        "topic_filter": latest_payload.get("topic_filter"),
        "ai_relevance_threshold": latest_payload.get("ai_relevance_threshold"),
        "total_items_raw": latest_payload.get("total_items_raw"),
        "total_items_all_mode": latest_payload.get("total_items_all_mode"),
        "creator_window_days": latest_payload.get("creator_window_days"),
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate AI news updates from multiple sources")
    parser.add_argument("--output-dir", default="data", help="Directory for output JSON files")
    parser.add_argument("--window-hours", type=int, default=24, help="24h window size")
    parser.add_argument("--archive-days", type=int, default=21, help="Keep archive for N days")
    parser.add_argument("--translate-max-new", type=int, default=80, help="Max new EN->ZH title translations per run")
    parser.add_argument("--rss-opml", default="", help="Optional OPML file path to include RSS sources")
    parser.add_argument("--rss-max-feeds", type=int, default=0, help="Optional max OPML RSS feeds to fetch (0 means all)")
    parser.add_argument(
        "--source-config",
        default="",
        help="Optional sources.config.json exported from the dashboard; defaults to ./sources.config.json when present",
    )
    parser.add_argument("--bilibili-only", action="store_true", help="Publish only the configured Bilibili dynamic accounts")
    parser.add_argument(
        "--source-scope",
        default=os.environ.get("RADAR_SOURCE_SCOPE") or DEPLOYED_SOURCE_SCOPE_DEFAULT,
        help="Source set to publish: tested_creator_sources (default) or all_sources",
    )
    parser.add_argument("--all-time", action="store_true", help="Publish all retained records instead of the rolling window")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    source_config, source_config_status = load_source_config(args.source_config, output_dir=output_dir)
    if source_config_status.get("enabled") and source_config_status.get("ok") is False:
        print(f"Source config error: {source_config_status.get('error')}", file=sys.stderr)
        return 2
    source_config_runtime = apply_source_config_runtime(source_config)
    configured_source_ids = frozenset(source_config_runtime.get("enabled_site_ids") or [])
    source_config_active = bool(source_config_status.get("ok") and source_config)
    source_scope = (
        SOURCE_SCOPE_BILIBILI_ONLY
        if args.bilibili_only or env_flag("BILIBILI_ONLY_MODE")
        else SOURCE_SCOPE_CONFIGURED if source_config_active
        else normalize_source_scope(args.source_scope)
    )
    active_source_ids = configured_source_ids if source_config_active else source_ids_for_scope(source_scope)
    scoped_to_tested_creators = source_scope == SOURCE_SCOPE_TESTED_CREATORS
    scoped_by_config = source_scope == SOURCE_SCOPE_CONFIGURED
    all_time = bool(args.all_time or env_flag("RADAR_ALL_TIME"))
    wewe_rss_enabled = env_flag("WEWE_RSS_ENABLED") and (
        active_source_ids is None or WEWE_RSS_SITE_ID in active_source_ids
    )
    if wewe_rss_enabled and active_source_ids is not None:
        active_source_ids = frozenset(site_id for site_id in active_source_ids if site_id != MAOBIDAO_WECHAT_SITE_ID)

    now = utc_now()
    output_dir.mkdir(parents=True, exist_ok=True)

    archive_path = output_dir / "archive.json"
    latest_path = output_dir / "latest-24h.json"
    latest_all_path = output_dir / "latest-24h-all.json"
    status_path = output_dir / "source-status.json"
    daily_brief_path = output_dir / "daily-brief.json"
    stories_merged_path = output_dir / "stories-merged.json"
    merge_log_path = output_dir / "merge-log.json"
    waytoagi_path = output_dir / "waytoagi-7d.json"
    title_cache_path = output_dir / "title-zh-cache.json"
    email_digest_path = output_dir / AGENTMAIL_DIGEST_FILE
    paid_source_state_path = output_dir / PAID_SOURCE_STATE_FILE

    archive = filter_archive_by_source_ids(load_archive(archive_path), active_source_ids)
    paid_source_state = load_paid_source_state(paid_source_state_path)

    session = create_session()
    if scoped_to_tested_creators:
        raw_items, statuses = [], []
    elif scoped_by_config:
        raw_items, statuses = collect_all(session, now, allowed_site_ids=active_source_ids)
    else:
        raw_items, statuses = collect_all(session, now)
    rss_feed_statuses: list[dict[str, Any]] = []
    github_repo_error = None
    github_repo_start = time.perf_counter()
    github_repo_items: list[RawItem] = []
    github_repo_enabled = active_source_ids is None or GITHUB_REPO_SUBSCRIPTION_SITE_ID in active_source_ids
    if github_repo_enabled:
        try:
            github_repo_items = fetch_github_repo_subscription(session, now)
            raw_items.extend(github_repo_items)
        except Exception as exc:
            github_repo_error = str(exc)
        statuses.append(
            {
                "site_id": GITHUB_REPO_SUBSCRIPTION_SITE_ID,
                "site_name": GITHUB_REPO_SUBSCRIPTION_SITE_NAME,
                "ok": github_repo_error is None,
                "item_count": len(github_repo_items),
                "duration_ms": int((time.perf_counter() - github_repo_start) * 1000),
                "error": github_repo_error,
                "source_kind": "github_release_subscription",
                "repo": "AlkaidLab/foundation-sunshine",
                "max_items": GITHUB_REPO_SUBSCRIPTION_MAX_ITEMS,
            }
        )
    if wewe_rss_enabled:
        wewe_rss_items, wewe_rss_status = fetch_wewe_rss_subscription(session, now)
        raw_items.extend(wewe_rss_items)
        statuses.append(
            {
                "site_id": WEWE_RSS_SITE_ID,
                "site_name": WEWE_RSS_SITE_NAME,
                "ok": bool(wewe_rss_status.get("ok")),
                "item_count": int(wewe_rss_status.get("item_count") or 0),
                "duration_ms": int(wewe_rss_status.get("duration_ms") or 0),
                "error": wewe_rss_status.get("error"),
                "source_kind": wewe_rss_status.get("source_kind"),
                "base_url": wewe_rss_status.get("base_url"),
                "max_items_per_feed": wewe_rss_status.get("max_items_per_feed"),
                "feeds": wewe_rss_status.get("feeds"),
                "coverage_note": wewe_rss_status.get("coverage_note"),
                "privacy": wewe_rss_status.get("privacy"),
            }
        )
    elif active_source_ids is None or MAOBIDAO_WECHAT_SITE_ID in active_source_ids:
        maobidao_error = None
        maobidao_start = time.perf_counter()
        maobidao_items: list[RawItem] = []
        try:
            maobidao_items = fetch_maobidao_wechat_subscription(session, now)
            raw_items.extend(maobidao_items)
        except Exception as exc:
            maobidao_error = str(exc)
        statuses.append(
            {
                "site_id": MAOBIDAO_WECHAT_SITE_ID,
                "site_name": MAOBIDAO_WECHAT_SITE_NAME,
                "ok": maobidao_error is None,
                "item_count": len(maobidao_items),
                "duration_ms": int((time.perf_counter() - maobidao_start) * 1000),
                "error": maobidao_error,
                "source_kind": "wechat_public_account_backup",
                "source_name": "猫笔刀公众号",
                "source_origin": MAOBIDAO_WECHAT_HOME_URL,
                "max_items": MAOBIDAO_WECHAT_MAX_ITEMS,
                "coverage_note": "reads_public_discourse_backup_json_not_wechat_login",
            }
        )
    bilibili_dynamic_status = bilibili_dynamic_status_base()
    if active_source_ids is None or "bilibili_dynamic" in active_source_ids:
        bilibili_dynamic_items, bilibili_dynamic_status = maybe_fetch_bilibili_dynamic(session, now)
        if bilibili_dynamic_status.get("enabled"):
            raw_items.extend(bilibili_dynamic_items)
            statuses.append(
                {
                    "site_id": "bilibili_dynamic",
                    "site_name": "Bilibili Dynamic",
                    "ok": bool(bilibili_dynamic_status.get("ok")) if bilibili_dynamic_status.get("ok") is not None else True,
                    "item_count": int(bilibili_dynamic_status.get("item_count") or 0),
                    "duration_ms": int(bilibili_dynamic_status.get("duration_ms") or 0),
                    "error": bilibili_dynamic_status.get("error"),
                    "uid": bilibili_dynamic_status.get("uid"),
                    "uids": bilibili_dynamic_status.get("uids"),
                    "uid_count": bilibili_dynamic_status.get("uid_count"),
                    "source_name": bilibili_dynamic_status.get("source_name"),
                    "privacy": bilibili_dynamic_status.get("privacy"),
                    "coverage_note": bilibili_dynamic_status.get("coverage_note"),
                    "cookie_present": bool(bilibili_dynamic_status.get("cookie_present")),
                    "fetch_mode": bilibili_dynamic_status.get("fetch_mode"),
                    "fallback_reason": bilibili_dynamic_status.get("fallback_reason"),
                    "partial_failure_count": bilibili_dynamic_status.get("partial_failure_count"),
                    "max_items": bilibili_dynamic_status.get("max_items"),
                    "max_items_per_account": bilibili_dynamic_status.get("max_items_per_account"),
                    "max_pages": bilibili_dynamic_status.get("max_pages"),
                    "accounts": bilibili_dynamic_status.get("accounts"),
                }
            )
    mediacrawler_douyin_status = {
        "enabled": False,
        "ok": None,
        "item_count": 0,
        "disabled_reason": "disabled_by_source_config" if scoped_by_config else "disabled_by_source_scope",
    }
    if active_source_ids is None or MEDIACRAWLER_DOUYIN_SITE_ID in active_source_ids:
        mediacrawler_douyin_items, mediacrawler_douyin_status = maybe_fetch_mediacrawler_douyin(now)
        if mediacrawler_douyin_status.get("enabled"):
            raw_items.extend(mediacrawler_douyin_items)
            statuses.append(
                {
                    "site_id": MEDIACRAWLER_DOUYIN_SITE_ID,
                    "site_name": MEDIACRAWLER_DOUYIN_SITE_NAME,
                    "ok": bool(mediacrawler_douyin_status.get("ok")) if mediacrawler_douyin_status.get("ok") is not None else True,
                    "item_count": int(mediacrawler_douyin_status.get("item_count") or 0),
                    "duration_ms": int(mediacrawler_douyin_status.get("duration_ms") or 0),
                    "error": mediacrawler_douyin_status.get("error"),
                    "source_name": mediacrawler_douyin_status.get("source_name"),
                    "privacy": mediacrawler_douyin_status.get("privacy"),
                    "coverage_note": mediacrawler_douyin_status.get("coverage_note"),
                    "source_kind": mediacrawler_douyin_status.get("source_kind"),
                    "jsonl_path_configured": bool(mediacrawler_douyin_status.get("jsonl_path_configured")),
                    "jsonl_file": mediacrawler_douyin_status.get("jsonl_file"),
                    "max_items": mediacrawler_douyin_status.get("max_items"),
                }
            )
    mediacrawler_xhs_status = {
        "enabled": False,
        "ok": None,
        "item_count": 0,
        "disabled_reason": "disabled_by_source_config" if scoped_by_config else "disabled_by_source_scope",
    }
    if active_source_ids is None or MEDIACRAWLER_XHS_SITE_ID in active_source_ids:
        mediacrawler_xhs_items, mediacrawler_xhs_status = maybe_fetch_mediacrawler_xhs(now)
        if mediacrawler_xhs_status.get("enabled"):
            raw_items.extend(mediacrawler_xhs_items)
            statuses.append(
                {
                    "site_id": MEDIACRAWLER_XHS_SITE_ID,
                    "site_name": MEDIACRAWLER_XHS_SITE_NAME,
                    "ok": bool(mediacrawler_xhs_status.get("ok")) if mediacrawler_xhs_status.get("ok") is not None else True,
                    "item_count": int(mediacrawler_xhs_status.get("item_count") or 0),
                    "duration_ms": int(mediacrawler_xhs_status.get("duration_ms") or 0),
                    "error": mediacrawler_xhs_status.get("error"),
                    "source_name": mediacrawler_xhs_status.get("source_name"),
                    "privacy": mediacrawler_xhs_status.get("privacy"),
                    "coverage_note": mediacrawler_xhs_status.get("coverage_note"),
                    "source_kind": mediacrawler_xhs_status.get("source_kind"),
                    "jsonl_path_configured": bool(mediacrawler_xhs_status.get("jsonl_path_configured")),
                    "jsonl_file": mediacrawler_xhs_status.get("jsonl_file"),
                    "max_items": mediacrawler_xhs_status.get("max_items"),
                }
            )
    advanced_source_ids = frozenset({
        "agentmail",
        "xapi",
        "socialdata_x",
        "tikhub_douyin",
        "tikhub_xiaohongshu",
        "waytoagi",
    })
    advanced_sources_enabled = active_source_ids is None or bool(active_source_ids.intersection(advanced_source_ids))
    if scoped_to_tested_creators or not advanced_sources_enabled:
        email_digest_payload = None
        disabled_reason = "disabled_by_source_config" if scoped_by_config else "disabled_by_source_scope"
        agentmail_status = {
            "enabled": False,
            "ok": None,
            "item_count": 0,
            "privacy": "metadata_only_no_body",
            "published_by_default": False,
            "disabled_reason": disabled_reason,
        }
        x_api_status = {
            "enabled": False,
            "ok": None,
            "item_count": 0,
            "disabled_reason": disabled_reason,
        }
        socialdata_status = {
            "enabled": False,
            "ok": None,
            "item_count": 0,
            "disabled_reason": disabled_reason,
        }
        tikhub_status = {
            "enabled": False,
            "ok": None,
            "item_count": 0,
            "disabled_reason": disabled_reason,
        }
        waytoagi_payload = {
            "generated_at": iso(now),
            "timezone": "Asia/Shanghai",
            "root_url": WAYTOAGI_DEFAULT,
            "history_url": None,
            "window_days": 7,
            "count_7d": 0,
            "updates_7d": [],
            "skipped": True,
            "skip_reason": disabled_reason,
        }
    else:
        if active_source_ids is None or "agentmail" in active_source_ids:
            email_digest_payload, agentmail_status = maybe_fetch_agentmail_digest(
                session,
                generated_at=iso(now),
                after=iso(now - timedelta(hours=args.window_hours)),
                window_hours=args.window_hours,
            )
        else:
            email_digest_payload = None
            agentmail_status = {
                "enabled": False,
                "ok": None,
                "item_count": 0,
                "privacy": "metadata_only_no_body",
                "published_by_default": False,
                "disabled_reason": "disabled_by_source_config",
            }
        if active_source_ids is None or "xapi" in active_source_ids:
            x_api_items, x_api_status = maybe_fetch_x_api_updates(session, now)
        else:
            x_api_items, x_api_status = [], {"enabled": False, "ok": None, "item_count": 0, "disabled_reason": "disabled_by_source_config"}
        if x_api_status.get("enabled"):
            raw_items.extend(x_api_items)
            statuses.append(
                {
                    "site_id": "xapi",
                    "site_name": "X API",
                    "ok": bool(x_api_status.get("ok")) if x_api_status.get("ok") is not None else True,
                    "item_count": int(x_api_status.get("item_count") or 0),
                    "duration_ms": 0,
                    "error": x_api_status.get("error"),
                    "skipped": bool(x_api_status.get("skipped")),
                    "skip_reason": x_api_status.get("skip_reason"),
                }
            )
        if active_source_ids is None or "socialdata_x" in active_source_ids:
            socialdata_items, socialdata_status = maybe_fetch_socialdata_updates(session, now, paid_source_state)
            update_paid_source_state(paid_source_state, "socialdata", socialdata_status, now)
            sync_paid_source_status_timestamps(socialdata_status, paid_source_state, "socialdata")
        else:
            socialdata_items, socialdata_status = [], {"enabled": False, "ok": None, "item_count": 0, "disabled_reason": "disabled_by_source_config"}
        if socialdata_status.get("enabled"):
            raw_items.extend(socialdata_items)
            statuses.append(
                {
                    "site_id": "socialdata_x",
                    "site_name": "SocialData X",
                    "ok": bool(socialdata_status.get("ok")) if socialdata_status.get("ok") is not None else True,
                    "item_count": int(socialdata_status.get("item_count") or 0),
                    "duration_ms": 0,
                    "error": socialdata_status.get("error"),
                    "skipped": bool(socialdata_status.get("skipped")),
                    "skip_reason": socialdata_status.get("skip_reason"),
                }
            )
        if active_source_ids is None or active_source_ids.intersection({"tikhub_douyin", "tikhub_xiaohongshu"}):
            tikhub_items, tikhub_status = maybe_fetch_tikhub_updates(session, now, paid_source_state)
            update_paid_source_state(paid_source_state, "tikhub", tikhub_status, now)
            sync_paid_source_status_timestamps(tikhub_status, paid_source_state, "tikhub")
        else:
            tikhub_items, tikhub_status = [], {"enabled": False, "ok": None, "item_count": 0, "disabled_reason": "disabled_by_source_config"}
        if tikhub_status.get("enabled"):
            raw_items.extend(tikhub_items)
            tikhub_counts: dict[str, int] = {}
            for item in tikhub_items:
                tikhub_counts[item.site_id] = tikhub_counts.get(item.site_id, 0) + 1
            for site_id, site_name in (
                ("tikhub_douyin", "TikHub Douyin"),
                ("tikhub_xiaohongshu", "TikHub Xiaohongshu"),
            ):
                if site_id.split("_", 1)[1] not in set(tikhub_status.get("platforms") or []):
                    continue
                statuses.append(
                    {
                        "site_id": site_id,
                        "site_name": site_name,
                        "ok": bool(tikhub_status.get("ok")) if tikhub_status.get("ok") is not None else True,
                        "item_count": tikhub_counts.get(site_id, 0),
                        "duration_ms": 0,
                        "error": tikhub_status.get("error"),
                        "skipped": bool(tikhub_status.get("skipped")),
                        "skip_reason": tikhub_status.get("skip_reason"),
                    }
                )

        waytoagi_started = time.perf_counter()
        if active_source_ids is not None and "waytoagi" not in active_source_ids:
            waytoagi_payload = {
                "generated_at": iso(now),
                "timezone": "Asia/Shanghai",
                "root_url": WAYTOAGI_DEFAULT,
                "history_url": None,
                "window_days": 7,
                "count_7d": 0,
                "updates_7d": [],
                "skipped": True,
                "skip_reason": "disabled_by_source_config",
            }
        else:
            try:
                waytoagi_payload = fetch_waytoagi_recent_7d(session, now, WAYTOAGI_DEFAULT)
                waytoagi_items = waytoagi_updates_to_raw_items(waytoagi_payload, now)
                raw_items.extend(waytoagi_items)
                statuses.append(
                    {
                        "site_id": "waytoagi",
                        "site_name": "WaytoAGI",
                        "ok": True,
                        "item_count": len(waytoagi_items),
                        "duration_ms": int((time.perf_counter() - waytoagi_started) * 1000),
                        "error": None,
                    }
                )
            except Exception as exc:
                waytoagi_payload = {
                    "generated_at": iso(now),
                    "timezone": "Asia/Shanghai",
                    "root_url": WAYTOAGI_DEFAULT,
                    "history_url": None,
                    "window_days": 7,
                    "count_7d": 0,
                    "updates_7d": [],
                    "warning": "WaytoAGI 近7日更新抓取失败",
                    "has_error": True,
                    "error": str(exc),
                }
                statuses.append(
                    {
                        "site_id": "waytoagi",
                        "site_name": "WaytoAGI",
                        "ok": False,
                        "item_count": 0,
                        "duration_ms": int((time.perf_counter() - waytoagi_started) * 1000),
                        "error": str(exc),
                    }
                )

    rss_opml_path = str(source_config_runtime.get("rss_opml") or args.rss_opml or "").strip()
    rss_opml_enabled = bool(
        rss_opml_path
        and not scoped_to_tested_creators
        and (active_source_ids is None or "opmlrss" in active_source_ids)
    )
    if rss_opml_enabled:
        opml_path = Path(rss_opml_path).expanduser()
        if opml_path.exists():
            rss_items, rss_summary_status, rss_feed_statuses = fetch_opml_rss(
                now,
                opml_path,
                max_feeds=max(0, int(args.rss_max_feeds)),
            )
            raw_items.extend(rss_items)
            statuses.append(rss_summary_status)
        else:
            statuses.append(
                {
                    "site_id": "opmlrss",
                    "site_name": "OPML RSS",
                    "ok": False,
                    "item_count": 0,
                    "duration_ms": 0,
                    "error": f"OPML not found: {opml_path}",
                    "feed_count": 0,
                    "ok_feed_count": 0,
                    "failed_feed_count": 0,
                }
            )

    if active_source_ids is not None:
        raw_items = [item for item in raw_items if item.site_id in active_source_ids]
        statuses = [status for status in statuses if str(status.get("site_id") or "") in active_source_ids]

    seen_this_run: set[str] = set()

    for raw in raw_items:
        title = raw.title.strip()
        url = normalize_url(raw.url)
        if not title or not url:
            continue
        if not url.startswith("http"):
            continue

        item_id = make_item_id(raw.site_id, raw.source, title, url)
        seen_this_run.add(item_id)

        existing = archive.get(item_id)
        if existing is None:
            archive[item_id] = {
                "id": item_id,
                "site_id": raw.site_id,
                "site_name": raw.site_name,
                "source": raw.source,
                "title": title,
                "url": url,
                "published_at": iso(raw.published_at),
                "first_seen_at": iso(now),
                "last_seen_at": iso(now),
            }
            apply_public_raw_meta(archive[item_id], raw)
        else:
            existing["site_id"] = raw.site_id
            existing["site_name"] = raw.site_name
            existing["source"] = raw.source
            existing["title"] = title
            existing["url"] = url
            if raw.published_at:
                # OPML RSS may fix previously wrong publish times; allow overwrite.
                if raw.site_id == "opmlrss" or not existing.get("published_at"):
                    existing["published_at"] = iso(raw.published_at)
            existing["last_seen_at"] = iso(now)
            apply_public_raw_meta(existing, raw)

    # Prune old archive unless the generated view intentionally needs all retained history.
    if not all_time:
        keep_after = now - timedelta(days=args.archive_days)
        pruned: dict[str, dict[str, Any]] = {}
        for item_id, record in archive.items():
            ts = (
                parse_iso(record.get("last_seen_at"))
                or parse_iso(record.get("published_at"))
                or parse_iso(record.get("first_seen_at"))
                or now
            )
            if ts >= keep_after:
                pruned[item_id] = record
        archive = pruned

    window_start = datetime.min.replace(tzinfo=UTC) if all_time else now - timedelta(hours=args.window_hours)
    latest_items_all: list[dict[str, Any]] = []
    for record in archive.values():
        if active_source_ids is not None and str(record.get("site_id") or "") not in active_source_ids:
            continue
        ts = event_time(record)
        if not ts:
            continue
        if ts >= window_start:
            normalized = dict(record)
            normalized["title"] = maybe_fix_mojibake(str(normalized.get("title") or ""))
            normalized["source"] = maybe_fix_mojibake(normalize_source_for_display(
                str(normalized.get("site_id") or ""),
                str(normalized.get("source") or ""),
                str(normalized.get("url") or ""),
            ))
            if str(normalized.get("site_id") or "") == "aihubtoday" and is_hubtoday_placeholder_title(
                str(normalized.get("title") or "")
            ):
                continue
            normalized = add_ai_relevance_fields(normalized)
            normalized = add_source_tier_fields(normalized)
            latest_items_all.append(normalized)

    latest_items_all = normalize_aihubtoday_records(latest_items_all)

    latest_items_all.sort(key=lambda x: event_time(x) or datetime.min.replace(tzinfo=UTC), reverse=True)
    latest_items = [record for record in latest_items_all if record.get("ai_is_related", is_ai_related_record(record))]
    title_cache = load_title_zh_cache(title_cache_path)
    latest_items, latest_items_all, title_cache = add_bilingual_fields(
        latest_items,
        latest_items_all,
        session,
        title_cache,
        max_new_translations=max(0, args.translate_max_new),
    )
    creator_window_days = None if all_time else CREATOR_HOT_WINDOW_DAYS
    creator_items_ai = build_creator_hot_items(archive, now, ai_only=True, window_days=creator_window_days)
    creator_items_all = build_creator_hot_items(archive, now, ai_only=False, window_days=creator_window_days)
    creator_items_ai, creator_items_all, title_cache = add_bilingual_fields(
        creator_items_ai,
        creator_items_all,
        session,
        title_cache,
        max_new_translations=0,
    )
    latest_items_ai_dedup = suppress_near_duplicate_items(dedupe_items_by_title_url(latest_items, random_pick=False))
    latest_items_all_dedup = dedupe_items_by_title_url(latest_items_all, random_pick=True)
    stories, merge_events = merge_story_items(latest_items_ai_dedup, now=now, window_hours=args.window_hours)
    generated_at = iso(now)
    daily_brief_payload = build_daily_brief_payload(stories, generated_at=generated_at, window_hours=args.window_hours)
    stories_merged_payload = build_stories_payload(stories, generated_at=generated_at, window_hours=args.window_hours)
    merge_log_payload = build_merge_log_payload(merge_events, generated_at=generated_at)

    # site stats
    site_stat: dict[str, dict[str, Any]] = {}
    raw_count_by_site: dict[str, int] = {}
    for record in latest_items_all:
        sid = record["site_id"]
        raw_count_by_site[sid] = raw_count_by_site.get(sid, 0) + 1

    site_name_by_id: dict[str, str] = {}
    for record in latest_items_all:
        site_name_by_id[record["site_id"]] = record["site_name"]
    for s in statuses:
        sid = s["site_id"]
        if sid not in site_name_by_id:
            site_name_by_id[sid] = s.get("site_name") or sid

    for record in latest_items_ai_dedup:
        sid = record["site_id"]
        if sid not in site_stat:
            site_stat[sid] = {
                "site_id": sid,
                "site_name": record["site_name"],
                "count": 0,
                "raw_count": raw_count_by_site.get(sid, 0),
            }
        site_stat[sid]["count"] += 1

    for sid, site_name in site_name_by_id.items():
        if sid in site_stat:
            continue
        site_stat[sid] = {
            "site_id": sid,
            "site_name": site_name,
            "count": 0,
            "raw_count": raw_count_by_site.get(sid, 0),
        }

    latest_payload = {
        "generated_at": generated_at,
        "window_hours": args.window_hours,
        "time_scope": "all_time" if all_time else "rolling_window",
        "source_scope": source_scope,
        "total_items": len(latest_items_ai_dedup),
        "total_items_ai_raw": len(latest_items),
        "total_items_raw": len(latest_items_all),
        "total_items_all_mode": len(latest_items_all_dedup),
        "topic_filter": "ai_relevance_scoring_v0_4",
        "ai_relevance_threshold": 0.65,
        "archive_total": len(archive),
        "site_count": len(site_stat),
        "source_count": len({f"{i['site_id']}::{i['source']}" for i in latest_items_ai_dedup}),
        "site_stats": sorted(site_stat.values(), key=lambda x: x["count"], reverse=True),
        "creator_window_days": 0 if creator_window_days is None else creator_window_days,
        "creator_time_scope": "all_time" if creator_window_days is None else "rolling_window",
        "creator_ranking": "engagement_85_fresh_24h_bonus_15_v1",
        "creator_items_ai": creator_items_ai,
        "creator_items_all": creator_items_all,
        "items": latest_items_ai_dedup,
        "items_ai": latest_items_ai_dedup,
        "items_all_raw": latest_items_all,
        "items_all": latest_items_all_dedup,
    }

    archive_payload = {
        "generated_at": generated_at,
        "total_items": len(archive),
        "items": sorted(
            archive.values(),
            key=lambda x: parse_iso(x.get("last_seen_at")) or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        ),
    }

    empty_advanced_sources = [
        {
            "site_id": s["site_id"],
            "site_name": s.get("site_name") or s["site_id"],
            "reason": "connected_no_matching_results",
        }
        for s in statuses
        if s.get("ok")
        and int(s.get("item_count") or 0) == 0
        and str(s.get("site_id") or "") in {
            "xapi",
            "socialdata_x",
            "tikhub_douyin",
            "tikhub_xiaohongshu",
            MEDIACRAWLER_DOUYIN_SITE_ID,
            MEDIACRAWLER_XHS_SITE_ID,
        }
        and not s.get("skipped")
    ]
    empty_advanced_site_ids = {item["site_id"] for item in empty_advanced_sources}

    status_payload = {
        "generated_at": generated_at,
        "sites": statuses,
        "time_scope": "all_time" if all_time else "rolling_window",
        "source_scope": source_scope,
        "successful_sites": sum(1 for s in statuses if s["ok"]),
        "failed_sites": [s["site_id"] for s in statuses if not s["ok"]],
        "zero_item_sites": [
            s["site_id"]
            for s in statuses
            if s.get("ok")
            and int(s.get("item_count") or 0) == 0
            and not s.get("skipped")
            and str(s.get("site_id") or "") not in empty_advanced_site_ids
        ],
        "empty_advanced_sources": empty_advanced_sources,
        "fetched_raw_items": len(raw_items),
        "items_before_topic_filter": len(latest_items_all),
        "items_in_24h": len(latest_items_ai_dedup),
        "rss_opml": {
            "enabled": rss_opml_enabled,
            "path": "configured" if rss_opml_enabled else None,
            "disabled_reason": "disabled_by_source_scope" if rss_opml_path and not rss_opml_enabled else None,
            "feed_total": len(rss_feed_statuses),
            "effective_feed_total": sum(1 for s in rss_feed_statuses if not s.get("skipped")),
            "ok_feeds": sum(1 for s in rss_feed_statuses if s["ok"] and not s.get("skipped")),
            "failed_feeds": [s.get("effective_feed_url") or s["feed_url"] for s in rss_feed_statuses if not s["ok"]],
            "zero_item_feeds": [
                s.get("effective_feed_url") or s["feed_url"]
                for s in rss_feed_statuses
                if s["ok"] and not s.get("skipped") and int(s.get("item_count") or 0) == 0
            ],
            "skipped_feeds": [
                {"feed_url": s["feed_url"], "reason": s.get("skip_reason")}
                for s in rss_feed_statuses
                if s.get("skipped")
            ],
            "replaced_feeds": [
                {"from": s["feed_url"], "to": s.get("effective_feed_url")}
                for s in rss_feed_statuses
                if s.get("replaced") and s.get("effective_feed_url")
            ],
            "feeds": rss_feed_statuses,
        },
        "agentmail": agentmail_status,
        "x_api": x_api_status,
        "socialdata": socialdata_status,
        "tikhub": tikhub_status,
        "mediacrawler_douyin": mediacrawler_douyin_status,
        "mediacrawler_xhs": mediacrawler_xhs_status,
        "source_config": {
            **source_config_status,
            **source_config_runtime,
            "active": source_config_active,
        },
    }

    latest_payload, latest_all_payload = build_latest_payloads(latest_payload)

    latest_path.write_text(json.dumps(sanitize_public_payload(latest_payload), ensure_ascii=False, indent=2), encoding="utf-8")
    latest_all_path.write_text(json.dumps(sanitize_public_payload(latest_all_payload), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    daily_brief_path.write_text(
        json.dumps(sanitize_public_payload(daily_brief_payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    stories_merged_path.write_text(
        json.dumps(sanitize_public_payload(stories_merged_payload), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    merge_log_path.write_text(
        json.dumps(sanitize_public_payload(merge_log_payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    archive_path.write_text(
        json.dumps(sanitize_public_payload(archive_payload), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    status_path.write_text(json.dumps(sanitize_public_payload(status_payload), ensure_ascii=False, indent=2), encoding="utf-8")
    paid_source_state_path.write_text(
        json.dumps(sanitize_public_payload(paid_source_state), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if email_digest_payload is not None:
        email_digest_path.write_text(
            json.dumps(sanitize_public_payload(email_digest_payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    waytoagi_path.write_text(json.dumps(sanitize_public_payload(waytoagi_payload), ensure_ascii=False, indent=2), encoding="utf-8")
    title_cache_path.write_text(json.dumps(sanitize_public_payload(title_cache), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote: {latest_path} ({len(latest_items)} items)")
    print(f"Wrote: {latest_all_path} ({len(latest_items_all_dedup)} all-mode items)")
    print(f"Wrote: {daily_brief_path} ({daily_brief_payload.get('total_items', 0)} brief items)")
    print(f"Wrote: {stories_merged_path} ({stories_merged_payload.get('total_stories', 0)} stories)")
    print(f"Wrote: {merge_log_path} ({len(merge_events)} merge events)")
    print(f"Wrote: {archive_path} ({len(archive)} items)")
    print(f"Wrote: {status_path}")
    print(f"Wrote: {paid_source_state_path}")
    if email_digest_payload is not None:
        print(f"Wrote: {email_digest_path} ({email_digest_payload.get('total_messages', 0)} email items)")
    print(f"Wrote: {waytoagi_path} ({waytoagi_payload.get('count_7d', 0)} items)")
    print(f"Wrote: {title_cache_path} ({len(title_cache)} entries)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
