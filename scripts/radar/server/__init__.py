"""Shared local-server state and constants for AI News Radar."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

MAX_CONFIG_BYTES = 1024 * 1024
MAX_ACTION_BYTES = 4096
MAX_SUBSCRIPTION_BYTES = 256 * 1024
CONFIG_FILENAME = "sources.config.json"
OPML_FILENAME = Path("feeds") / "follow.opml"
REFRESH_TIMEOUT_SECONDS = 600
REFRESH_LOCK = threading.Lock()
REFRESH_PROGRESS_LOCK = threading.Lock()
REFRESH_PROGRESS: dict[str, Any] = {
    "running": False,
    "status": "idle",
    "percent": 0,
    "current_step": "等待刷新",
    "log": [],
}
RESTART_DELAY_SECONDS = 0.4
COLLECTION_SCOPE_24H = "24h"
COLLECTION_SCOPE_ALL = "all"
COLLECTION_SCOPES = {COLLECTION_SCOPE_24H, COLLECTION_SCOPE_ALL}
MEDIACRAWLER_JSONL_STALE_HOURS = 36
WEWE_RSS_BASE_URL_DEFAULT = "http://127.0.0.1:4000"
LOCAL_HTTP_TIMEOUT_SECONDS = 2.0
BILIBILI_LOGIN_URL = "https://passport.bilibili.com/login"
BILIBILI_DEFAULT_COOKIE_FILE = Path("local-secrets") / "bilibili-cookies.txt"
BILIBILI_PROFILE_DIR = Path("local-secrets") / "bilibili-profile"
BILIBILI_CDP_PORT = 9334
BILIBILI_COOKIE_URL = "https://www.bilibili.com/"
DOUYIN_HOME_URL = "https://www.douyin.com/"
XIAOHONGSHU_HOME_URL = "https://www.xiaohongshu.com/explore"
WEWE_RSS_SIDECAR_DIR_NAME = "wewe-rss-sidecar"
WEWE_RSS_SIDECAR_LOG_OUT = "wewe-rss.out.log"
WEWE_RSS_SIDECAR_LOG_ERR = "wewe-rss.err.log"
MEDIACRAWLER_LOCAL_DIR_NAME = "MediaCrawler-local-test"
MEDIACRAWLER_DOUYIN_LOG_OUT = "mediacrawler-douyin.out.log"
MEDIACRAWLER_DOUYIN_LOG_ERR = "mediacrawler-douyin.err.log"
MEDIACRAWLER_DOUYIN_PID = "mediacrawler-douyin.pid"
MEDIACRAWLER_XHS_LOG_OUT = "mediacrawler-xhs.out.log"
MEDIACRAWLER_XHS_LOG_ERR = "mediacrawler-xhs.err.log"
MEDIACRAWLER_XHS_PID = "mediacrawler-xhs.pid"
MEDIACRAWLER_24H_WINDOW_HOURS = 24
MEDIACRAWLER_DOUYIN_24H_MAX_NOTES = 5
MEDIACRAWLER_XHS_24H_MAX_NOTES = 5


def normalize_collection_scope(raw_scope: Any) -> str:
    scope = str(raw_scope or COLLECTION_SCOPE_24H).strip().lower()
    if scope in {"24h", "24", "last_24h", "last-24h", "rolling_window"}:
        return COLLECTION_SCOPE_24H
    if scope in {"all", "all_time", "all-time", "full"}:
        return COLLECTION_SCOPE_ALL
    raise ValueError("unsupported_collection_scope")


def bilibili_cookie_status(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .common import bilibili_cookie_status as implementation

    return implementation(*args, **kwargs)


def maintenance_issues_from_status(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    from .common import maintenance_issues_from_status as implementation

    return implementation(*args, **kwargs)

def local_config_maintenance_issues(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    from .collectors import local_config_maintenance_issues as implementation

    return implementation(*args, **kwargs)


def mediacrawler_douyin_collector_status(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .collectors import mediacrawler_douyin_collector_status as implementation

    return implementation(*args, **kwargs)


def mediacrawler_xhs_collector_status(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .collectors import mediacrawler_xhs_collector_status as implementation

    return implementation(*args, **kwargs)


def start_mediacrawler_douyin(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .collectors import start_mediacrawler_douyin as implementation

    return implementation(*args, **kwargs)


def start_mediacrawler_xhs(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .collectors import start_mediacrawler_xhs as implementation

    return implementation(*args, **kwargs)


def start_wewe_rss_sidecar(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .collectors import start_wewe_rss_sidecar as implementation

    return implementation(*args, **kwargs)
