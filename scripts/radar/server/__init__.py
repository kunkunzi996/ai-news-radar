"""Shared local-server state and constants for AI News Radar."""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
import shutil
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
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


def wire_modules(modules: list[ModuleType]) -> None:
    """Share moved local-server helper names across split modules."""

    shared: dict[str, object] = {}
    for module in modules:
        for name, value in vars(module).items():
            if not name.startswith("_"):
                shared[name] = value
    for module in modules:
        for name, value in shared.items():
            if not name.startswith("_"):
                setattr(module, name, value)
