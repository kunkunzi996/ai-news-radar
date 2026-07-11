from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
from dateutil import parser as dtparser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import feedparser
except ModuleNotFoundError:
    feedparser = None

"""Common constants and helpers for the AI News Radar pipeline."""

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
BILIBILI_DYNAMIC_DETAIL_API_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"
BILIBILI_DYNAMIC_OPUS_DETAIL_API_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/detail"
BILIBILI_NAV_API_URL = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_DYNAMIC_DEFAULT_UID = "505301413"
BILIBILI_DYNAMIC_DEFAULT_SOURCE_NAME = "Koji杨远骋at十字路口"
BILIBILI_DYNAMIC_DEFAULT_ACCOUNTS = (
    (BILIBILI_DYNAMIC_DEFAULT_UID, BILIBILI_DYNAMIC_DEFAULT_SOURCE_NAME),
    ("316183842", "技术爬爬虾"),
)
BILIBILI_DYNAMIC_DEFAULT_MAX_ITEMS = 5
BILIBILI_DYNAMIC_DEFAULT_MAX_PAGES = 5
BILIBILI_DYNAMIC_BACKFILL_MAX_ITEMS = 80
BILIBILI_DYNAMIC_BACKFILL_MAX_PAGES = 8
MEDIACRAWLER_DOUYIN_SITE_ID = "mediacrawler_douyin"
MEDIACRAWLER_DOUYIN_SITE_NAME = "MediaCrawler Douyin"
MEDIACRAWLER_XHS_SITE_ID = "mediacrawler_xhs"
MEDIACRAWLER_XHS_SITE_NAME = "MediaCrawler Xiaohongshu"
GITHUB_REPO_SUBSCRIPTION_SITE_ID = "github_foundation_sunshine_releases"
GITHUB_REPO_SUBSCRIPTION_SITE_NAME = "GitHub Foundation Sunshine"
GITHUB_REPO_SUBSCRIPTION_API_URL = "https://api.github.com/repos/AlkaidLab/foundation-sunshine/releases"
GITHUB_REPO_SUBSCRIPTION_HTML_URL = "https://github.com/AlkaidLab/foundation-sunshine"
GITHUB_REPO_SUBSCRIPTION_MAX_ITEMS = 5
GITHUB_REPO_SUBSCRIPTION_BACKFILL_MAX_ITEMS = 30
MAOBIDAO_WECHAT_SITE_ID = "maobidao_wudaolu_backup"
MAOBIDAO_WECHAT_SITE_NAME = "Maobidao Wudaolu Backup"
MAOBIDAO_WECHAT_API_URL = "https://wudaolu.com/c/dav/7.json"
MAOBIDAO_WECHAT_HOME_URL = "https://wudaolu.com/c/dav/7"
MAOBIDAO_WECHAT_MAX_ITEMS = 2
WEWE_RSS_SITE_ID = "wewe_rss"
WEWE_RSS_SITE_NAME = "WeWe RSS"
WEWE_RSS_BASE_URL_DEFAULT = "http://127.0.0.1:4000"
WEWE_RSS_DEFAULT_MAX_ITEMS = 20
WE_MP_RSS_SITE_ID = "we_mp_rss"
WE_MP_RSS_SITE_NAME = "WeRSS 公众号"
WE_MP_RSS_BASE_URL_DEFAULT = "http://127.0.0.1:8001"
WE_MP_RSS_DEFAULT_MAX_ITEMS = 20
WE_MP_RSS_JSONL_SITE_ID = "we_mp_rss_jsonl"
WE_MP_RSS_JSONL_SITE_NAME = "WeRSS \u516c\u4f17\u53f7"
WE_MP_RSS_JSONL_DEFAULT_MAX_ITEMS = 20
OPML_RSS_DEFAULT_MAX_ITEMS_PER_FEED = 5
# 新订阅源第一次采集时的历史回填窗口（天）：归档里从未出现过的源，
# 首采会尽量补齐该窗口内的全部内容；之后恢复常规采集口径。
FIRST_COLLECT_BACKFILL_DAYS_DEFAULT = 60
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
    "opmlrss",
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
    "we_mp_rss_maobidao": (WE_MP_RSS_SITE_ID,),
    "online_we_mp_rss_maobidao": (WE_MP_RSS_JSONL_SITE_ID,),
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
    "we_mp_rss": (WE_MP_RSS_SITE_ID,),
    "we_mp_rss_jsonl": (WE_MP_RSS_JSONL_SITE_ID,),
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
    "bilibili_dynamic_id",
    "bilibili_opus_id",
    "creator_metrics",
    "search_surface",
    "summary",
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SECRET_LIKE_RE = re.compile(r"\b(sk-(?!hynix\b)[A-Za-z0-9_-]{12,}|(?:api[_-]?key|secret|token)=([^\s&]{6,}))\b", re.I)
URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>]+")
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
MEANINGFUL_EN_SIGNAL_RE = re.compile(
    r"(?i)(?<![a-z0-9])(ai|aigc|llm|gpt|openai|anthropic|deepseek|gemini|claude|robot|robotics|embodied|autonomous|machine learning|artificial intelligence|transformer|diffusion)(?![a-z0-9])"
)
BROAD_AI_TERMS = {"agent", "模型", "推理"}


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


def event_time(record: dict[str, Any]) -> datetime | None:
    # RSS sources must rely on the source's publish time only.
    # first_seen_at is fetch time and would falsely mark historical items as "24h".
    if str(record.get("site_id") or "") == "opmlrss":
        return parse_iso(record.get("published_at"))
    return parse_iso(record.get("published_at")) or parse_iso(record.get("first_seen_at"))


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


def parse_domain_filter(raw: str) -> list[str]:
    """Parse a comma-separated sender-domain allowlist for private newsletter demos."""
    domains: list[str] = []
    for part in re.split(r"[,\s]+", str(raw or "")):
        domain = part.strip().lower().lstrip("@")
        if domain and re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", domain):
            domains.append(domain)
    return sorted(set(domains))


def creator_metric_count(*values: Any) -> int:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return max(0, int(float(str(value).replace(",", "").strip())))
        except (TypeError, ValueError):
            continue
    return 0


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


def has_mojibake_noise(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"(Ã|Â|â€|æ·|�)", text))


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


def first_collect_backfill_days() -> int:
    return max(0, min(env_int("FIRST_COLLECT_BACKFILL_DAYS", FIRST_COLLECT_BACKFILL_DAYS_DEFAULT), 365))


def trim_first_collect_backfill_items(
    items: list[RawItem],
    now: datetime,
    keep_latest: int,
    backfill_days: int | None = None,
) -> list[RawItem]:
    """首采回填的统一截断：保留最新 keep_latest 条兜底 + 回填窗口内的其余条目。

    线上 Actions 不带采集窗口参数（管线窗口过滤不生效），所以回填的时间
    边界必须在 fetcher 层落实，否则首采会带入远超两个月的历史内容。
    """
    days = first_collect_backfill_days() if backfill_days is None else backfill_days
    if days <= 0:
        return items
    backfill_start = now - timedelta(days=days)
    ordered = sorted(
        items,
        key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return [
        item
        for index, item in enumerate(ordered)
        if index < keep_latest or (item.published_at and item.published_at >= backfill_start)
    ]



