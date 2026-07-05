#!/usr/bin/env python3
"""Local-only static server with a narrow source-config write endpoint."""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
import shutil
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MAX_CONFIG_BYTES = 1024 * 1024
MAX_ACTION_BYTES = 4096
MAX_SUBSCRIPTION_BYTES = 256 * 1024
CONFIG_FILENAME = "sources.config.json"
OPML_FILENAME = Path("feeds") / "follow.opml"
REFRESH_TIMEOUT_SECONDS = 600
REFRESH_LOCK = threading.Lock()
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


def site_display_name(site: dict[str, Any]) -> str:
    return str(site.get("site_name") or site.get("source_name") or site.get("site_id") or "未知来源")


def add_maintenance_issue(
    issues: list[dict[str, Any]],
    issue_id: str,
    severity: str,
    source_id: str,
    title: str,
    detail: str,
    action: str,
    fix_actions: list[dict[str, Any]] | None = None,
) -> None:
    issue = {
        "id": issue_id,
        "severity": severity,
        "source_id": source_id,
        "title": title,
        "detail": detail,
        "action": action,
    }
    if fix_actions:
        issue["fix_actions"] = fix_actions
    issues.append(issue)


def open_url_action(action_id: str, label: str, url: str) -> dict[str, Any]:
    return {"id": action_id, "kind": "open_url", "label": label, "url": url}


def open_path_action(action_id: str, label: str, path: Path) -> dict[str, Any]:
    return {"id": action_id, "kind": "open_path", "label": label, "path": str(path)}


def start_service_action(action_id: str, label: str) -> dict[str, Any]:
    return {"id": action_id, "kind": "start_service", "label": label}


def wewe_dashboard_url() -> str:
    base_url = (os.environ.get("WEWE_RSS_BASE_URL") or WEWE_RSS_BASE_URL_DEFAULT).strip().rstrip("/")
    return base_url + "/dash"


def wewe_fix_actions(include_start: bool = False) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if include_start:
        actions.append(start_service_action("start_wewe_rss_sidecar", "启动后台/扫码"))
    actions.append(open_url_action("open_wewe_rss_dashboard", "打开后台/扫码", wewe_dashboard_url()))
    return actions


def bilibili_fix_actions(root_dir: Path | None = None) -> list[dict[str, Any]]:
    cookie_folder = (root_dir / BILIBILI_DEFAULT_COOKIE_FILE.parent) if root_dir else BILIBILI_DEFAULT_COOKIE_FILE.parent
    return [
        start_service_action("open_bilibili_login", "打开B站小号登录"),
        start_service_action("sync_bilibili_cookie", "同步cookie"),
        open_path_action("open_bilibili_cookie_folder", "打开cookie文件夹", cookie_folder),
    ]


def bilibili_cookie_file_path(root_dir: Path) -> Path:
    configured = str(os.environ.get("BILIBILI_COOKIE_FILE") or os.environ.get("BILIBILI_DYNAMIC_COOKIE_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return root_dir / BILIBILI_DEFAULT_COOKIE_FILE


def bilibili_cookie_status(root_dir: Path) -> dict[str, Any]:
    has_env_cookie = bool(str(os.environ.get("BILIBILI_COOKIE") or os.environ.get("BILIBILI_DYNAMIC_COOKIE") or "").strip())
    cookie_file = bilibili_cookie_file_path(root_dir)
    file_exists = cookie_file.exists() and cookie_file.is_file() and cookie_file.stat().st_size > 0
    return {
        "configured": has_env_cookie or file_exists,
        "env_cookie_present": has_env_cookie,
        "cookie_file": str(cookie_file),
        "cookie_file_exists": file_exists,
        "recommended_cookie_file": str(root_dir / BILIBILI_DEFAULT_COOKIE_FILE),
    }


def port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def find_available_port(start_port: int) -> int:
    for port in range(start_port, start_port + 50):
        if not port_is_open(port):
            return port
    raise RuntimeError(f"no available local port from {start_port}")


def cdp_json(port: int, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=3.0) as response:
        return json.loads(response.read().decode("utf-8"))


def cdp_ready(port: int) -> bool:
    try:
        return bool(cdp_json(port, "/json/version").get("Browser"))
    except Exception:
        return False


def find_chrome_executable() -> str | None:
    configured = str(os.environ.get("BILIBILI_CHROME_PATH") or os.environ.get("MEDIACRAWLER_CHROME_PATH") or "").strip()
    if configured and Path(configured).is_file():
        return configured
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def launch_bilibili_dedicated_browser(root_dir: Path, *, execute: bool = True) -> dict[str, Any]:
    profile_dir = (root_dir / BILIBILI_PROFILE_DIR).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = BILIBILI_CDP_PORT if cdp_ready(BILIBILI_CDP_PORT) else find_available_port(BILIBILI_CDP_PORT)
    chrome = find_chrome_executable()
    if not chrome:
        return {"ok": False, "error": "chrome_not_found"}
    command = [
        chrome,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--start-maximized",
        BILIBILI_LOGIN_URL,
    ]
    if not execute:
        return {
            "ok": True,
            "kind": "start_service",
            "action_id": "open_bilibili_login",
            "command": command,
            "profile_dir": str(profile_dir),
            "cdp_port": port,
            "executed": False,
        }
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, close_fds=True, creationflags=creationflags)
    return {
        "ok": True,
        "kind": "start_service",
        "action_id": "open_bilibili_login",
        "pid": process.pid,
        "profile_dir": str(profile_dir),
        "cdp_port": port,
        "next_action": "在这个专用窗口登录B站小号，然后回本页点同步cookie。",
        "executed": True,
    }


def active_bilibili_cdp_port() -> int | None:
    for port in range(BILIBILI_CDP_PORT, BILIBILI_CDP_PORT + 8):
        if cdp_ready(port):
            return port
    return None


def cdp_new_page(port: int, url: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(url, safe=":/?=&")
    for method in ("PUT", "GET"):
        request = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{encoded}", method=method, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=3.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            if method == "PUT":
                continue
            raise
    return {}


def read_websocket_frame(sock: socket.socket) -> bytes:
    header = sock.recv(2)
    if len(header) < 2:
        return b""
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", sock.recv(8))[0]
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def sync_bilibili_cookie(root_dir: Path, *, execute: bool = True) -> dict[str, Any]:
    port = active_bilibili_cdp_port()
    if not port:
        return {"ok": False, "error": "bilibili_login_window_not_running"}
    payload = cdp_new_page(port, BILIBILI_COOKIE_URL)
    websocket_url = str(payload.get("webSocketDebuggerUrl") or "")
    if not websocket_url:
        return {"ok": False, "error": "cdp_target_not_available"}
    import base64

    parsed = urllib.parse.urlparse(websocket_url)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {parsed.path} HTTP/1.1\r\n"
        f"Host: {parsed.netloc}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode("ascii")
    with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or port), timeout=5) as sock:
        sock.sendall(request)
        response = sock.recv(4096)
        if b" 101 " not in response:
            return {"ok": False, "error": "websocket_upgrade_failed"}
        message = json.dumps({"id": 1, "method": "Network.getAllCookies"}).encode("utf-8")
        header = bytearray([0x81])
        length = len(message)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(message))
        sock.sendall(bytes(header) + masked)
        data = None
        for _attempt in range(20):
            raw = read_websocket_frame(sock)
            if not raw:
                continue
            candidate = json.loads(raw.decode("utf-8"))
            if candidate.get("id") == 1:
                data = candidate
                break
        if data is None:
            return {"ok": False, "error": "websocket_cookie_response_missing"}
    cookies = [
        cookie for cookie in data.get("result", {}).get("cookies", [])
        if "bilibili.com" in str(cookie.get("domain") or "")
    ]
    if not cookies:
        return {"ok": False, "error": "bilibili_cookie_not_found"}
    cookie_text = "; ".join(f"{cookie.get('name')}={cookie.get('value')}" for cookie in cookies if cookie.get("name") and cookie.get("value"))
    if "SESSDATA=" not in cookie_text:
        return {"ok": False, "error": "bilibili_login_cookie_missing_sessdata"}
    cookie_file = (root_dir / BILIBILI_DEFAULT_COOKIE_FILE).resolve()
    if execute:
        cookie_file.parent.mkdir(parents=True, exist_ok=True)
        cookie_file.write_text(cookie_text + "\n", encoding="utf-8")
    return {
        "ok": True,
        "kind": "start_service",
        "action_id": "sync_bilibili_cookie",
        "cookie_file": str(cookie_file),
        "cookie_count": len(cookies),
        "has_sessdata": True,
        "executed": execute,
    }


def platform_url_for_runtime_id(runtime_id: str) -> str:
    if runtime_id == "mediacrawler_xhs":
        return XIAOHONGSHU_HOME_URL
    if runtime_id == "mediacrawler_douyin":
        return DOUYIN_HOME_URL
    return ""


def platform_label_for_runtime_id(runtime_id: str) -> str:
    if runtime_id == "mediacrawler_xhs":
        return "打开小红书"
    if runtime_id == "mediacrawler_douyin":
        return "打开抖音"
    return "打开平台"


def existing_open_target(path: Path) -> Path | None:
    if path.exists():
        return path.parent if path.is_file() else path
    candidate = path.parent
    while candidate != candidate.parent:
        if candidate.exists():
            return candidate
        candidate = candidate.parent
    return candidate if candidate.exists() else None


def resolve_latest_mediacrawler_jsonl(raw_path: Path) -> Path:
    path = raw_path.expanduser()
    if path.is_dir():
        candidates = sorted(
            path.glob("creator_contents_*.jsonl"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        non_empty_candidates = [candidate for candidate in candidates if candidate.stat().st_size > 0]
        if non_empty_candidates:
            return non_empty_candidates[0]
        return candidates[0] if candidates else path
    if path.parent.exists() and (not path.exists() or path.name.startswith("creator_contents_")):
        candidates = sorted(
            path.parent.glob("creator_contents_*.jsonl"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        non_empty_candidates = [candidate for candidate in candidates if candidate.stat().st_size > 0]
        if non_empty_candidates and (not path.exists() or path.stat().st_size <= 0 or non_empty_candidates[0].stat().st_mtime >= path.stat().st_mtime):
            return non_empty_candidates[0]
        if candidates and (not path.exists() or candidates[0].stat().st_mtime >= path.stat().st_mtime):
            return candidates[0]
    return path


def mediacrawler_fix_actions(root_dir: Path, runtime_id: str, raw_path: str = "") -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if runtime_id == "mediacrawler_douyin":
        actions.append(start_service_action("start_mediacrawler_douyin", "启动抖音采集"))
    if runtime_id == "mediacrawler_xhs":
        actions.append(start_service_action("start_mediacrawler_xhs", "启动小红书采集"))
    target = existing_open_target(resolve_mediacrawler_locator(root_dir, runtime_id, raw_path))
    if target:
        actions.append(open_path_action(f"open_{runtime_id}_jsonl_folder", "打开JSONL文件夹", target))
    platform_url = platform_url_for_runtime_id(runtime_id)
    if platform_url:
        actions.append(open_url_action(f"open_{runtime_id}_platform", platform_label_for_runtime_id(runtime_id), platform_url))
    return actions


def maintenance_action_for_error(site_id: str, error: str) -> str:
    text = str(error or "")
    if site_id == "wewe_rss":
        if "no_feeds" in text:
            return "打开 WeWe RSS 后台，确认公众号已订阅，并检查 WEWE_RSS_FEEDS 或 /feeds 输出。"
        if "base_url" in text or "Connection" in text or "HTTPConnection" in text:
            return "先启动 wewe-rss-sidecar，再确认 http://127.0.0.1:4000 可以访问。"
        return "先看 WeWe RSS 后台是否需要重新扫码或重新添加公众号。"
    if site_id in {"mediacrawler_douyin", "mediacrawler_xhs"}:
        if "not_found" in text or "missing" in text:
            return "先运行对应平台的 MediaCrawler，生成新的 creator_contents_*.jsonl，或修正 sources.config.json 里的 JSONL 路径。"
        return "先检查 MediaCrawler 是否能单独抓取，再让本看板读取新导出的 JSONL。"
    if site_id == "bilibili_dynamic":
        return "重新导出 B站 cookie，或接受当前公开接口兜底结果。不要把 cookie 写进仓库。"
    return "检查该源的地址、网络、接口返回和 sources.config.json 配置。"


def maintenance_issues_from_status(payload: dict[str, Any], root_dir: Path | None = None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    sites = [site for site in payload.get("sites", []) if isinstance(site, dict)]
    for site in sites:
        site_id = str(site.get("site_id") or "")
        name = site_display_name(site)
        error = str(site.get("error") or "")
        has_failed_wewe_feed = site_id == "wewe_rss" and any(
            isinstance(feed, dict) and feed.get("ok") is False
            for feed in site.get("feeds") or []
        )
        if site.get("ok") is False and not has_failed_wewe_feed:
            add_maintenance_issue(
                issues,
                f"{site_id or 'source'}_failed",
                "bad",
                site_id,
                f"{name} 抓取失败",
                error or "本轮没有成功返回数据。",
                maintenance_action_for_error(site_id, error),
                wewe_fix_actions(include_start=True) if site_id == "wewe_rss" else bilibili_fix_actions(root_dir) if site_id == "bilibili_dynamic" else [],
            )
        elif site.get("ok") is True and int(site.get("item_count") or 0) == 0:
            add_maintenance_issue(
                issues,
                f"{site_id or 'source'}_zero_items",
                "warn",
                site_id,
                f"{name} 本轮 0 条",
                "接口能访问，但没有抓到可入池内容。",
                "先确认订阅对象最近是否更新；如果确认有更新，再检查源地址、时间窗口和过滤规则。",
            )

        if site_id == "bilibili_dynamic":
            if site.get("cookie_present") is False:
                add_maintenance_issue(
                    issues,
                    "bilibili_cookie_missing",
                    "warn",
                    site_id,
                    "B站 cookie 未配置",
                    "当前走公开接口兜底，可能拿不到完整动态。",
                    "如需完整动态，重新导出 B站 cookie 并通过环境变量或本地 cookie 文件配置；不要提交 cookie。",
                    bilibili_fix_actions(root_dir),
                )
            for account in site.get("accounts") or []:
                if isinstance(account, dict) and account.get("ok") is False:
                    add_maintenance_issue(
                        issues,
                        f"bilibili_account_{account.get('uid')}_failed",
                        "bad",
                        site_id,
                        f"B站账号 {account.get('source_name') or account.get('uid')} 抓取失败",
                        str(account.get("error") or "账号级抓取失败。"),
                        "检查 UID 是否正确；如果 cookie 模式失败，重新导出 B站 cookie。",
                        bilibili_fix_actions(root_dir),
                    )

        if site_id == "wewe_rss":
            for feed in site.get("feeds") or []:
                if isinstance(feed, dict) and feed.get("ok") is False:
                    add_maintenance_issue(
                        issues,
                        f"wewe_feed_{feed.get('id')}_failed",
                        "bad",
                        site_id,
                        f"公众号 {feed.get('name') or feed.get('id')} 读取失败",
                        str(feed.get("error") or "WeWe RSS feed 没有返回正常数据。"),
                        "打开 WeWe RSS 后台确认是否需要扫码、重新登录或重新订阅该公众号。",
                        wewe_fix_actions(include_start=True),
                    )

    source_config = payload.get("source_config")
    if isinstance(source_config, dict) and source_config.get("ok") is False:
        add_maintenance_issue(
            issues,
            "source_config_invalid",
            "bad",
            "source_config",
            "sources.config.json 读取失败",
            str(source_config.get("error") or "配置文件格式不正确。"),
            "在页面里重新写入配置，或检查 sources.config.json 是否是合法 JSON。",
        )
    return issues


def dedupe_maintenance_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in issues:
        issue_id = str(issue.get("id") or "")
        if issue_id and issue_id in seen:
            continue
        if issue_id:
            seen.add(issue_id)
        deduped.append(issue)
    return deduped


def read_source_status(root_dir: Path) -> dict[str, Any] | None:
    path = root_dir / "data" / "source-status.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def validate_source_config(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("config root must be a JSON object")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise ValueError("config must contain a sources array")
    if len(sources) > 500:
        raise ValueError("too many sources")
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"sources[{index}] must be an object")
        source_id = str(source.get("id") or "").strip()
        name = str(source.get("name") or "").strip()
        if not source_id:
            raise ValueError(f"sources[{index}].id is required")
        if not name:
            raise ValueError(f"sources[{index}].name is required")
    return payload


def youtube_channel_id_from_feed_url(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.netloc not in {"www.youtube.com", "youtube.com"}:
        return ""
    query = urllib.parse.parse_qs(parsed.query)
    return str((query.get("channel_id") or [""])[0]).strip()


def youtube_feed_url(channel_id: str) -> str:
    clean = str(channel_id or "").strip()
    if not clean:
        return ""
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={clean}"


def validate_youtube_subscription(payload: dict[str, Any], index: int) -> dict[str, str]:
    title = str(payload.get("title") or payload.get("text") or "").strip()
    channel_id = str(payload.get("channel_id") or "").strip()
    html_url = str(payload.get("html_url") or payload.get("htmlUrl") or "").strip()
    xml_url = str(payload.get("xml_url") or payload.get("xmlUrl") or "").strip()
    if not channel_id and xml_url:
        channel_id = youtube_channel_id_from_feed_url(xml_url)
    if not xml_url and channel_id:
        xml_url = youtube_feed_url(channel_id)
    if not title:
        raise ValueError(f"subscriptions[{index}].title is required")
    if not channel_id:
        raise ValueError(f"subscriptions[{index}].channel_id is required")
    if not xml_url.startswith("https://www.youtube.com/feeds/videos.xml?channel_id="):
        raise ValueError(f"subscriptions[{index}].xml_url must be a YouTube channel feed")
    if html_url and not (
        html_url.startswith("https://www.youtube.com/")
        or html_url.startswith("https://youtube.com/")
    ):
        raise ValueError(f"subscriptions[{index}].html_url must be a YouTube URL")
    return {
        "title": title[:120],
        "channel_id": channel_id[:120],
        "xml_url": xml_url,
        "html_url": html_url[:300],
    }


def opml_path(root_dir: Path) -> Path:
    return (root_dir / OPML_FILENAME).resolve()


def read_youtube_subscriptions(root_dir: Path) -> list[dict[str, str]]:
    path = opml_path(root_dir)
    if path.parent != (root_dir / "feeds").resolve() or path.name != "follow.opml":
        raise ValueError("invalid_opml_path")
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    subscriptions: list[dict[str, str]] = []
    seen: set[str] = set()
    for outline in root.findall(".//outline"):
        xml_url = str(outline.attrib.get("xmlUrl") or "").strip()
        channel_id = youtube_channel_id_from_feed_url(xml_url)
        if not channel_id or channel_id in seen:
            continue
        seen.add(channel_id)
        title = str(outline.attrib.get("title") or outline.attrib.get("text") or channel_id).strip()
        subscriptions.append(
            {
                "title": title,
                "channel_id": channel_id,
                "xml_url": youtube_feed_url(channel_id),
                "html_url": str(outline.attrib.get("htmlUrl") or "").strip(),
            }
        )
    return subscriptions


def write_youtube_subscriptions(root_dir: Path, raw_subscriptions: Any) -> list[dict[str, str]]:
    if not isinstance(raw_subscriptions, list):
        raise ValueError("subscriptions must be an array")
    if len(raw_subscriptions) > 200:
        raise ValueError("too many subscriptions")
    subscriptions: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_subscriptions):
        if not isinstance(item, dict):
            raise ValueError(f"subscriptions[{index}] must be an object")
        subscription = validate_youtube_subscription(item, index)
        if subscription["channel_id"] in seen:
            continue
        seen.add(subscription["channel_id"])
        subscriptions.append(subscription)

    path = opml_path(root_dir)
    if path.parent != (root_dir / "feeds").resolve() or path.name != "follow.opml":
        raise ValueError("invalid_opml_path")
    path.parent.mkdir(parents=True, exist_ok=True)
    opml = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(opml, "head")
    title = ET.SubElement(head, "title")
    title.text = "AI News Radar Personal Subscriptions"
    body = ET.SubElement(opml, "body")
    for subscription in subscriptions:
        ET.SubElement(
            body,
            "outline",
            {
                "text": subscription["title"],
                "title": subscription["title"],
                "type": "rss",
                "xmlUrl": subscription["xml_url"],
                "htmlUrl": subscription["html_url"],
            },
        )
    tree = ET.ElementTree(opml)
    ET.indent(tree, space="  ")
    tmp_path = path.with_suffix(".opml.tmp")
    tree.write(tmp_path, encoding="utf-8", xml_declaration=True)
    os.replace(tmp_path, path)
    return subscriptions


def read_source_config(root_dir: Path) -> dict[str, Any] | None:
    path = root_dir / CONFIG_FILENAME
    if not path.exists():
        return None
    return validate_source_config(json.loads(path.read_text(encoding="utf-8")))


def source_config_runtime_ids(source: dict[str, Any]) -> set[str]:
    raw_id = str(source.get("id") or "").strip().lower()
    raw_type = str(source.get("type") or "").strip().lower()
    channel = str(source.get("channel") or "").lower()
    target = str(source.get("target") or "").lower()
    locator = str(source.get("locator") or "").lower()
    haystack = f"{raw_id} {raw_type} {channel} {target} {locator}"
    runtime_ids: set[str] = set()
    if raw_type == "wewe_rss" or raw_id.startswith("wewe_rss") or "wewe_rss" in haystack or "wewe rss" in haystack:
        runtime_ids.add("wewe_rss")
    if raw_type == "bilibili_dynamic" or "bilibili" in haystack or "b站" in haystack:
        runtime_ids.add("bilibili_dynamic")
    if raw_type == "mediacrawler_jsonl":
        if "xhs" in haystack or "xiaohongshu" in haystack or "小红书" in haystack:
            runtime_ids.add("mediacrawler_xhs")
        if "douyin" in haystack or "抖音" in haystack:
            runtime_ids.add("mediacrawler_douyin")
    return runtime_ids


PURGE_TRACKED_SITE_IDS = frozenset(
    {
        "wewe_rss",
        "bilibili_dynamic",
        "mediacrawler_douyin",
        "mediacrawler_xhs",
        "github_foundation_sunshine_releases",
    }
)


def purge_tracked_site_ids(source: dict[str, Any]) -> set[str]:
    ids = set(source_config_runtime_ids(source))
    if str(source.get("type") or "").strip().lower() == "github_release":
        ids.add("github_foundation_sunshine_releases")
    return ids & PURGE_TRACKED_SITE_IDS


def source_identity_names(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    identities: dict[str, dict[str, str]] = {site_id: {} for site_id in PURGE_TRACKED_SITE_IDS}
    sources = config.get("sources") if isinstance(config, dict) else None
    if not isinstance(sources, list):
        return identities
    for source in sources:
        if not isinstance(source, dict):
            continue
        site_ids = purge_tracked_site_ids(source)
        if not site_ids:
            continue
        if "bilibili_dynamic" in site_ids:
            names = [part.strip() for part in str(source.get("target") or "").split(",")]
            locators = [part.strip() for part in str(source.get("locator") or "").split(",")]
            for index in range(max(len(names), len(locators))):
                locator = locators[index] if index < len(locators) else ""
                identity_key = locator or (names[index] if index < len(names) else "")
                if not identity_key:
                    continue
                name = names[index] if index < len(names) and names[index] else locator
                identities["bilibili_dynamic"][identity_key] = name
        for site_id in site_ids:
            if site_id == "bilibili_dynamic":
                continue
            record_id = str(source.get("id") or "").strip()
            display = str(source.get("target") or source.get("name") or "").strip()
            if record_id and display:
                identities[site_id][record_id] = display
    return identities


def alive_source_names_by_site(
    config: dict[str, Any],
    previous_config: dict[str, Any] | None = None,
) -> dict[str, set[str]]:
    current = source_identity_names(config)
    previous = source_identity_names(previous_config) if previous_config else {}
    alive: dict[str, set[str]] = {}
    for site_id in PURGE_TRACKED_SITE_IDS:
        names = set(current.get(site_id, {}).values())
        for identity_key, old_name in previous.get(site_id, {}).items():
            if identity_key in current.get(site_id, {}):
                names.add(old_name)
        alive[site_id] = names
    return alive


def is_item_orphaned(record: dict[str, Any], alive_names: dict[str, set[str]]) -> bool:
    site_id = str(record.get("site_id") or "").strip()
    if site_id not in alive_names:
        return False
    source_name = str(record.get("source") or "").strip()
    return source_name not in alive_names[site_id]


def purge_orphaned_from_flat_list(
    items: list[Any],
    alive_names: dict[str, set[str]],
) -> tuple[list[Any], int]:
    kept = [item for item in items if not (isinstance(item, dict) and is_item_orphaned(item, alive_names))]
    return kept, len(items) - len(kept)


def purge_orphaned_from_story_list(
    stories: list[Any],
    alive_names: dict[str, set[str]],
) -> tuple[list[Any], int]:
    kept = []
    removed = 0
    for story in stories:
        if not isinstance(story, dict):
            kept.append(story)
            continue
        members = story.get("items")
        if not isinstance(members, list):
            members = story.get("sources") if isinstance(story.get("sources"), list) else []
        if any(isinstance(member, dict) and is_item_orphaned(member, alive_names) for member in members):
            removed += 1
            continue
        kept.append(story)
    return kept, removed


def write_json_atomic(path: Path, payload: Any, *, compact: bool) -> None:
    text = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if compact
        else json.dumps(payload, ensure_ascii=False, indent=2)
    )
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def purge_deleted_source_data(
    root_dir: Path,
    config: dict[str, Any],
    *,
    previous_config: dict[str, Any] | None = None,
) -> dict[str, int]:
    alive_names = alive_source_names_by_site(config, previous_config)
    data_dir = root_dir / "data"
    summary: dict[str, int] = {}

    def rewrite_flat(filename: str, list_keys: tuple[str, ...], *, compact: bool) -> None:
        path = data_dir / filename
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        removed_total = 0
        for key in list_keys:
            items = payload.get(key)
            if not isinstance(items, list):
                continue
            kept, removed = purge_orphaned_from_flat_list(items, alive_names)
            payload[key] = kept
            removed_total += removed
        if "total_items" in payload and "items" in list_keys:
            payload["total_items"] = len(payload.get("items") or [])
        if removed_total:
            write_json_atomic(path, payload, compact=compact)
        summary[filename] = removed_total

    def rewrite_stories(filename: str, list_key: str, total_key: str, *, compact: bool) -> None:
        path = data_dir / filename
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict) or not isinstance(payload.get(list_key), list):
            return
        kept, removed = purge_orphaned_from_story_list(payload[list_key], alive_names)
        payload[list_key] = kept
        if total_key in payload:
            payload[total_key] = len(kept)
        if removed:
            write_json_atomic(path, payload, compact=compact)
        summary[filename] = removed

    rewrite_flat("archive.json", ("items",), compact=True)
    rewrite_flat(
        "latest-24h.json",
        ("items", "items_ai", "creator_items_ai", "creator_items_all"),
        compact=False,
    )
    rewrite_flat(
        "latest-24h-all.json",
        ("items_all", "items_all_raw", "creator_items_all"),
        compact=True,
    )
    rewrite_stories("stories-merged.json", "stories", "total_stories", compact=True)
    rewrite_stories("daily-brief.json", "items", "total_items", compact=False)
    return summary


def enabled_source_config_records(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not config:
        return []
    sources = config.get("sources")
    if not isinstance(sources, list):
        return []
    return [source for source in sources if isinstance(source, dict) and source.get("enabled") is not False]


def resolve_config_path(root_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = root_dir / path
    return path


def is_url_like(value: str) -> bool:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def default_mediacrawler_jsonl_dir(root_dir: Path, runtime_id: str) -> Path:
    folder = "xhs" if runtime_id == "mediacrawler_xhs" else "douyin"
    return mediacrawler_local_root(root_dir) / "output" / folder / "jsonl"


def resolve_mediacrawler_locator(root_dir: Path, runtime_id: str, locator: str) -> Path:
    raw = str(locator or "").strip()
    if not raw or is_url_like(raw):
        return default_mediacrawler_jsonl_dir(root_dir, runtime_id)
    return resolve_config_path(root_dir, raw)


def add_mediacrawler_jsonl_issue(
    issues: list[dict[str, Any]],
    root_dir: Path,
    source: dict[str, Any],
    runtime_id: str,
    now: datetime,
    stale_after_hours: int,
) -> None:
    locator = str(source.get("locator") or "").strip()
    source_name = str(source.get("name") or source.get("target") or source.get("id") or "MediaCrawler")
    platform = "小红书" if runtime_id == "mediacrawler_xhs" else "抖音"
    if not locator:
        add_maintenance_issue(
            issues,
            f"{runtime_id}_jsonl_missing_path",
            "bad",
            runtime_id,
            f"{platform}主页链接未配置",
            f"{source_name} 已启用，但还没有填写创作者主页链接。",
            "在订阅成员里填写创作者名称和主页链接，再启动对应平台采集。",
            mediacrawler_fix_actions(root_dir, runtime_id),
        )
        return

    configured_path = resolve_mediacrawler_locator(root_dir, runtime_id, locator)
    jsonl_path = resolve_latest_mediacrawler_jsonl(configured_path)
    if not jsonl_path.exists():
        locator_hint = "主页链接已保存，但本地还没找到该平台的 creator_contents_*.jsonl。" if is_url_like(locator) else f"配置路径没有找到文件：{configured_path}"
        add_maintenance_issue(
            issues,
            f"{runtime_id}_jsonl_not_found",
            "bad",
            runtime_id,
            f"{platform} JSONL 文件不存在",
            locator_hint,
            "先运行对应平台的 MediaCrawler 生成 JSONL；之后系统会自动读取最新结果。",
            mediacrawler_fix_actions(root_dir, runtime_id, locator),
        )
        return
    if not jsonl_path.is_file():
        add_maintenance_issue(
            issues,
            f"{runtime_id}_jsonl_not_file",
            "bad",
            runtime_id,
            f"{platform} JSONL 路径不是文件",
            f"当前路径不是可读取的 JSONL 文件：{jsonl_path}",
            "把路径改成具体的 creator_contents_*.jsonl 文件。",
            mediacrawler_fix_actions(root_dir, runtime_id, locator),
        )
        return

    stat = jsonl_path.stat()
    if stat.st_size <= 0:
        add_maintenance_issue(
            issues,
            f"{runtime_id}_jsonl_empty",
            "bad",
            runtime_id,
            f"{platform} JSONL 文件为空",
            f"{jsonl_path.name} 当前大小为 0。",
            "重新运行 MediaCrawler，确认导出的 JSONL 里有内容。",
            mediacrawler_fix_actions(root_dir, runtime_id, locator),
        )
        return

    modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    age_hours = max(0, int((now - modified_at).total_seconds() // 3600))
    if age_hours >= stale_after_hours:
        add_maintenance_issue(
            issues,
            f"{runtime_id}_jsonl_stale",
            "warn",
            runtime_id,
            f"{platform} JSONL 可能过旧",
            f"{jsonl_path.name} 上次更新约 {age_hours} 小时前。",
            "如果想看最新动态，先点对应平台的启动采集，再点读取结果。",
            mediacrawler_fix_actions(root_dir, runtime_id, locator),
        )


def is_local_http_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(value)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def check_wewe_rss_sidecar(base_url: str) -> tuple[bool, str]:
    url = base_url.rstrip("/") + "/feeds"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=LOCAL_HTTP_TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                return False, f"HTTP {response.status}"
            return True, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def read_wewe_rss_feeds(base_url: str | None = None) -> dict[str, Any]:
    resolved_base_url = (base_url or os.environ.get("WEWE_RSS_BASE_URL") or WEWE_RSS_BASE_URL_DEFAULT).strip().rstrip("/")
    if not is_local_http_url(resolved_base_url):
        return {"ok": False, "error": "wewe_rss_base_url_not_local", "base_url": resolved_base_url, "feeds": []}

    url = resolved_base_url + "/feeds"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=LOCAL_HTTP_TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                return {"ok": False, "error": f"HTTP {response.status}", "base_url": resolved_base_url, "feeds": []}
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}", "base_url": resolved_base_url, "feeds": []}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": str(exc), "base_url": resolved_base_url, "feeds": []}

    if not isinstance(payload, list):
        return {"ok": False, "error": "invalid_wewe_rss_feeds_payload", "base_url": resolved_base_url, "feeds": []}

    feeds: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        feed_id = str(item.get("id") or "").strip()
        if not feed_id or feed_id in seen:
            continue
        seen.add(feed_id)
        name = str(item.get("name") or item.get("title") or feed_id).strip() or feed_id
        feeds.append(
            {
                "id": feed_id,
                "name": name,
                "intro": str(item.get("intro") or "").strip(),
                "updateTime": item.get("updateTime"),
                "syncTime": item.get("syncTime"),
            }
        )

    return {"ok": True, "base_url": resolved_base_url, "feeds": feeds, "feed_count": len(feeds)}


def wewe_rss_sidecar_root(root_dir: Path) -> Path:
    configured = str(os.environ.get("WEWE_RSS_SIDECAR_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (root_dir.parent / WEWE_RSS_SIDECAR_DIR_NAME).resolve()


def wewe_rss_server_dir(root_dir: Path) -> Path:
    return wewe_rss_sidecar_root(root_dir) / "apps" / "server"


def wewe_rss_service_running() -> bool:
    ok, _detail = check_wewe_rss_sidecar((os.environ.get("WEWE_RSS_BASE_URL") or WEWE_RSS_BASE_URL_DEFAULT).strip().rstrip("/"))
    return ok


def start_wewe_rss_sidecar(root_dir: Path, *, execute: bool = True) -> dict[str, Any]:
    base_url = (os.environ.get("WEWE_RSS_BASE_URL") or WEWE_RSS_BASE_URL_DEFAULT).strip().rstrip("/")
    if not is_local_http_url(base_url):
        return {"ok": False, "error": "wewe_rss_base_url_not_local", "base_url": base_url}
    if wewe_rss_service_running():
        return {"ok": True, "already_running": True, "url": base_url + "/dash", "executed": False}

    server_dir = wewe_rss_server_dir(root_dir)
    entry = server_dir / "dist" / "main.js"
    if not entry.exists():
        entry = server_dir / "dist" / "main"
    if not entry.exists():
        return {"ok": False, "error": "wewe_rss_dist_not_found", "path": str(server_dir / "dist")}

    node_exe = shutil.which("node")
    if not node_exe:
        return {"ok": False, "error": "node_not_found"}
    if not execute:
        return {"ok": True, "command": [node_exe, str(entry)], "cwd": str(server_dir), "url": base_url + "/dash", "executed": False}

    env = os.environ.copy()
    env.setdefault("HOST", "127.0.0.1")
    env.setdefault("PORT", "4000")
    env.setdefault("DATABASE_TYPE", "sqlite")
    env.setdefault("DATABASE_URL", "file:../data/wewe-rss.db")
    out_log = wewe_rss_sidecar_root(root_dir) / WEWE_RSS_SIDECAR_LOG_OUT
    err_log = wewe_rss_sidecar_root(root_dir) / WEWE_RSS_SIDECAR_LOG_ERR
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with out_log.open("a", encoding="utf-8", errors="ignore") as stdout_file, err_log.open("a", encoding="utf-8", errors="ignore") as stderr_file:
        process = subprocess.Popen(
            [node_exe, str(entry)],
            cwd=server_dir,
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    return {
        "ok": True,
        "kind": "start_service",
        "action_id": "start_wewe_rss_sidecar",
        "pid": process.pid,
        "url": base_url + "/dash",
        "executed": True,
    }


def mediacrawler_local_root(root_dir: Path) -> Path:
    configured = str(os.environ.get("MEDIACRAWLER_LOCAL_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (root_dir.parent / MEDIACRAWLER_LOCAL_DIR_NAME).resolve()


def mediacrawler_python_exe(crawler_root: Path) -> str | None:
    if os.name == "nt":
        local_python = crawler_root / "venv" / "Scripts" / "python.exe"
    else:
        local_python = crawler_root / "venv" / "bin" / "python"
    if local_python.exists():
        return str(local_python)
    return shutil.which("python") or shutil.which("python3") or sys.executable


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
                check=False,
            )
        except Exception:
            return False
        return f'"{pid}"' in result.stdout or f",{pid}," in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid_file(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except Exception:
        return None


def newest_file(folder: Path, pattern: str) -> Path | None:
    if not folder.exists():
        return None
    candidates = sorted(folder.glob(pattern), key=lambda candidate: candidate.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def mediacrawler_window_summary_path(crawler_root: Path, platform: str) -> Path:
    return crawler_root / f"mediacrawler-{platform}-collection-window.json"


def read_mediacrawler_window_summary(crawler_root: Path, platform: str, jsonl: Path | None) -> dict[str, Any] | None:
    if not jsonl:
        return None
    summary_path = mediacrawler_window_summary_path(crawler_root, platform)
    if not summary_path.exists():
        return None
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(summary, dict):
        return None
    if Path(str(summary.get("path") or "")).resolve() != jsonl.resolve():
        return None
    try:
        if summary_path.stat().st_mtime < jsonl.stat().st_mtime:
            return None
    except OSError:
        return None
    return summary


def count_file_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return sum(1 for _line in handle)
    except Exception:
        return 0


def read_tail_lines(path: Path, limit: int = 80) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
    except Exception:
        return []


def last_meaningful_mediacrawler_log(lines: list[str], platform: str) -> str:
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        if platform == "douyin" and "Douyin Crawler finished" in text:
            return "采集完成"
        if platform == "xhs" and "Xhs Crawler finished" in text:
            return "采集完成"
        if platform == "douyin" and "update_douyin_aweme" in text and "title:" in text:
            return "正在写入作品：" + text.split("title:", 1)[-1].strip()[:80]
        if platform == "xhs" and "update_xhs_note" in text and "title" in text:
            return "正在写入笔记：" + text.split("title", 1)[-1].strip(" :,'{}")[:80]
        if platform == "douyin" and "get_all_user_aweme_posts" in text and "video len" in text:
            return text.split(" - ", 1)[-1].strip()
        if platform == "xhs" and "Finished getting notes for user" in text:
            return text.split(" - ", 1)[-1].strip()
        if "Sleeping for" in text:
            return "正在逐条读取作品详情"
    return ""


def mediacrawler_collector_status(root_dir: Path, runtime_id: str) -> dict[str, Any]:
    if runtime_id == "mediacrawler_xhs":
        platform = "xhs"
        platform_name = "小红书"
        output_folder = "xhs"
        pid_file = MEDIACRAWLER_XHS_PID
        err_log = MEDIACRAWLER_XHS_LOG_ERR
    else:
        platform = "douyin"
        platform_name = "抖音"
        output_folder = "douyin"
        pid_file = MEDIACRAWLER_DOUYIN_PID
        err_log = MEDIACRAWLER_DOUYIN_LOG_ERR

    crawler_root = mediacrawler_local_root(root_dir)
    pid_path = crawler_root / pid_file
    pid = read_pid_file(pid_path)
    running = process_is_running(pid or 0)
    jsonl_candidate = resolve_latest_mediacrawler_jsonl(crawler_root / "output" / output_folder / "jsonl")
    jsonl = jsonl_candidate if jsonl_candidate.exists() and jsonl_candidate.is_file() else None
    log_lines = read_tail_lines(crawler_root / err_log)
    last_log = last_meaningful_mediacrawler_log(log_lines, platform)
    finished_marker = "Xhs Crawler finished" if platform == "xhs" else "Douyin Crawler finished"
    raw_item_count = count_file_lines(jsonl) if jsonl else 0
    item_count = raw_item_count
    collection_window_hours: int | None = None
    skipped_collection_window_items: int | None = None
    window_summary = read_mediacrawler_window_summary(crawler_root, platform, jsonl)
    if window_summary:
        collection_window_hours = int(window_summary.get("window_hours") or 0) or None
        item_count = int(window_summary.get("kept") or 0)
        skipped_collection_window_items = int(window_summary.get("skipped") or 0)
    updated_at = datetime.fromtimestamp(jsonl.stat().st_mtime, timezone.utc).isoformat() if jsonl else None
    completed_by_log = any(finished_marker in line for line in log_lines[-80:])
    completed_by_output = (
        not running
        and bool(pid)
        and pid_path.exists()
        and jsonl is not None
        and raw_item_count > 0
        and jsonl.stat().st_mtime >= pid_path.stat().st_mtime
    )
    completed = completed_by_log or completed_by_output

    if running:
        phase = "running"
        title = f"{platform_name}采集中"
        next_action = "保持采集专用窗口打开；完成后这里会变成可关闭。"
        can_close_browser = False
    elif completed and jsonl:
        phase = "completed"
        title = f"{platform_name}采集已完成"
        next_action = "可以关闭采集专用窗口；回到本页点读取结果，让主站读取新 JSONL。"
        can_close_browser = True
    elif jsonl:
        phase = "idle"
        title = f"{platform_name}采集未运行"
        next_action = f"如需最新动态，点启动{platform_name}采集。"
        can_close_browser = True
    else:
        phase = "missing"
        title = f"{platform_name}还没有采集结果"
        next_action = f"点启动{platform_name}采集，完成扫码或登录后等待写出 JSONL。"
        can_close_browser = False

    return {
        "id": runtime_id,
        "platform": platform,
        "platform_name": platform_name,
        "title": title,
        "phase": phase,
        "running": running,
        "completed": completed,
        "can_close_browser": can_close_browser,
        "pid": pid,
        "item_count": item_count,
        "raw_item_count": raw_item_count,
        "collection_window_hours": collection_window_hours,
        "skipped_collection_window_items": skipped_collection_window_items,
        "latest_file": jsonl.name if jsonl else None,
        "latest_file_path": str(jsonl) if jsonl else None,
        "updated_at": updated_at,
        "last_log": last_log,
        "next_action": next_action,
    }


def mediacrawler_creator_id(root_dir: Path, crawler_root: Path, runtime_id: str) -> str:
    if runtime_id == "mediacrawler_xhs":
        configured = str(os.environ.get("MEDIACRAWLER_XHS_CREATOR_ID") or os.environ.get("MEDIACRAWLER_XIAOHONGSHU_CREATOR_ID") or "").strip()
    else:
        configured = str(os.environ.get("MEDIACRAWLER_DOUYIN_CREATOR_ID") or "").strip()
    if configured:
        return configured

    candidates: list[Path] = []
    try:
        config = read_source_config(root_dir)
    except Exception:
        config = None
    for source in enabled_source_config_records(config):
        if runtime_id not in source_config_runtime_ids(source):
            continue
        locator = str(source.get("locator") or "").strip()
        if is_url_like(locator):
            return locator
        if locator:
            candidates.append(resolve_latest_mediacrawler_jsonl(resolve_mediacrawler_locator(root_dir, runtime_id, locator)))

    if runtime_id != "mediacrawler_xhs":
        return ""

    newest = newest_file(crawler_root / "output" / "xhs" / "jsonl", "creator_contents_*.jsonl")
    if newest:
        candidates.append(newest)

    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    user_id = str(row.get("user_id") or "").strip()
                    if user_id:
                        return f"https://www.xiaohongshu.com/user/profile/{user_id}"
        except Exception:
            continue
    return ""


def mediacrawler_xhs_creator_id(root_dir: Path, crawler_root: Path) -> str:
    return mediacrawler_creator_id(root_dir, crawler_root, "mediacrawler_xhs")


def mediacrawler_start_max_notes(platform: str, collection_scope: str) -> int | None:
    if collection_scope == COLLECTION_SCOPE_24H:
        if platform == "xhs":
            return int(os.environ.get("MEDIACRAWLER_XHS_24H_MAX_NOTES") or MEDIACRAWLER_XHS_24H_MAX_NOTES)
        return int(os.environ.get("MEDIACRAWLER_DOUYIN_24H_MAX_NOTES") or MEDIACRAWLER_DOUYIN_24H_MAX_NOTES)
    if platform == "xhs":
        return int(os.environ.get("MEDIACRAWLER_XHS_MAX_NOTES") or 500)
    return None


def start_mediacrawler_platform(
    root_dir: Path,
    runtime_id: str,
    *,
    execute: bool = True,
    collection_scope: str = COLLECTION_SCOPE_24H,
) -> dict[str, Any]:
    scope = normalize_collection_scope(collection_scope)
    platform = "xhs" if runtime_id == "mediacrawler_xhs" else "douyin"
    action_id = "start_mediacrawler_xhs" if platform == "xhs" else "start_mediacrawler_douyin"
    out_log_name = MEDIACRAWLER_XHS_LOG_OUT if platform == "xhs" else MEDIACRAWLER_DOUYIN_LOG_OUT
    err_log_name = MEDIACRAWLER_XHS_LOG_ERR if platform == "xhs" else MEDIACRAWLER_DOUYIN_LOG_ERR
    pid_name = MEDIACRAWLER_XHS_PID if platform == "xhs" else MEDIACRAWLER_DOUYIN_PID
    crawler_root = mediacrawler_local_root(root_dir)
    crawler_entry = crawler_root / "main.py"
    if not crawler_entry.exists():
        return {"ok": False, "error": "mediacrawler_main_not_found", "path": str(crawler_entry)}
    entry = root_dir / "scripts" / "run_mediacrawler_douyin.py"
    if not entry.exists():
        return {"ok": False, "error": "mediacrawler_runner_not_found", "path": str(entry)}

    python_exe = mediacrawler_python_exe(crawler_root)
    if not python_exe:
        return {"ok": False, "error": "python_not_found"}

    command = [
        python_exe,
        str(entry),
        "--crawler-root",
        str(crawler_root),
        "--platform",
        platform,
    ]
    creator_id = mediacrawler_creator_id(root_dir, crawler_root, runtime_id)
    if creator_id:
        command.extend(["--creator-id", creator_id])
    if scope == COLLECTION_SCOPE_24H:
        command.extend(["--collect-window-hours", str(MEDIACRAWLER_24H_WINDOW_HOURS)])
    max_notes = mediacrawler_start_max_notes(platform, scope)
    if max_notes:
        command.extend(["--max-notes", str(max_notes)])
    if platform == "xhs":
        if not creator_id:
            return {"ok": False, "error": "mediacrawler_xhs_creator_id_missing"}
    if not execute:
        return {
            "ok": True,
            "kind": "start_service",
            "action_id": action_id,
            "collection_scope": scope,
            "command": command,
            "cwd": str(crawler_root),
            "executed": False,
        }

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    out_log = crawler_root / out_log_name
    err_log = crawler_root / err_log_name
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with out_log.open("a", encoding="utf-8", errors="ignore") as stdout_file, err_log.open("a", encoding="utf-8", errors="ignore") as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=crawler_root,
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    (crawler_root / pid_name).write_text(str(process.pid), encoding="utf-8")
    return {
        "ok": True,
        "kind": "start_service",
        "action_id": action_id,
        "collection_scope": scope,
        "pid": process.pid,
        "executed": True,
    }


def mediacrawler_douyin_collector_status(root_dir: Path) -> dict[str, Any]:
    return mediacrawler_collector_status(root_dir, "mediacrawler_douyin")


def mediacrawler_xhs_collector_status(root_dir: Path) -> dict[str, Any]:
    return mediacrawler_collector_status(root_dir, "mediacrawler_xhs")


def start_mediacrawler_douyin(
    root_dir: Path,
    *,
    execute: bool = True,
    collection_scope: str = COLLECTION_SCOPE_24H,
) -> dict[str, Any]:
    return start_mediacrawler_platform(
        root_dir,
        "mediacrawler_douyin",
        execute=execute,
        collection_scope=collection_scope,
    )


def start_mediacrawler_xhs(
    root_dir: Path,
    *,
    execute: bool = True,
    collection_scope: str = COLLECTION_SCOPE_24H,
) -> dict[str, Any]:
    return start_mediacrawler_platform(
        root_dir,
        "mediacrawler_xhs",
        execute=execute,
        collection_scope=collection_scope,
    )


def add_wewe_rss_config_issues(
    issues: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    probe_network: bool,
) -> None:
    wewe_sources = [source for source in sources if "wewe_rss" in source_config_runtime_ids(source)]
    if not wewe_sources:
        return

    missing_feed_sources = [
        str(source.get("name") or source.get("target") or source.get("id") or "未命名公众号")
        for source in wewe_sources
        if not str(source.get("locator") or "").strip()
    ]
    if missing_feed_sources:
        add_maintenance_issue(
            issues,
            "wewe_rss_feed_id_missing",
            "bad",
            "wewe_rss",
            "公众号 feed id 未配置",
            f"缺少 feed id：{'、'.join(missing_feed_sources[:3])}",
            "在 WeWe RSS 后台找到对应公众号 feed id，并填到该信源的地址 / ID / 路径。",
            wewe_fix_actions(),
        )

    base_url = (os.environ.get("WEWE_RSS_BASE_URL") or WEWE_RSS_BASE_URL_DEFAULT).strip().rstrip("/")
    if not is_local_http_url(base_url):
        add_maintenance_issue(
            issues,
            "wewe_rss_sidecar_probe_skipped",
            "warn",
            "wewe_rss",
            "WeWe RSS 不是本地地址",
            f"当前 WEWE_RSS_BASE_URL={base_url}，本地工具已跳过 HTTP 探测。",
            "如果这是你有意配置的远程服务，请手动确认它能访问；本地面板只自动探测 localhost/127.0.0.1。",
            [open_url_action("open_wewe_rss_dashboard", "打开后台", base_url + "/dash")] if base_url.startswith(("http://", "https://")) else [],
        )
        return
    if not probe_network:
        return

    ok, detail = check_wewe_rss_sidecar(base_url)
    if not ok:
        add_maintenance_issue(
            issues,
            "wewe_rss_sidecar_unreachable",
            "bad",
            "wewe_rss",
            "WeWe RSS 本地服务不可用",
            f"{base_url}/feeds 访问失败：{detail}",
            "先启动 wewe-rss-sidecar；如果后台要求重新扫码，先完成扫码登录，再回到本页面检查状态。",
            wewe_fix_actions(include_start=True),
        )


def local_config_maintenance_issues(
    root_dir: Path,
    config: dict[str, Any] | None,
    *,
    probe_network: bool = True,
    now: datetime | None = None,
    stale_after_hours: int = MEDIACRAWLER_JSONL_STALE_HOURS,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    current_time = now or datetime.now(timezone.utc)
    sources = enabled_source_config_records(config)
    for source in sources:
        runtime_ids = source_config_runtime_ids(source)
        for runtime_id in sorted(runtime_ids & {"mediacrawler_douyin", "mediacrawler_xhs"}):
            add_mediacrawler_jsonl_issue(issues, root_dir, source, runtime_id, current_time, stale_after_hours)
    add_wewe_rss_config_issues(issues, sources, probe_network)
    return dedupe_maintenance_issues(issues)


def json_response(handler: SimpleHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def is_local_origin(value: str) -> bool:
    if not value:
        return True
    return value.startswith("http://127.0.0.1:") or value.startswith("http://localhost:")


def normalize_collection_scope(raw_scope: Any) -> str:
    scope = str(raw_scope or COLLECTION_SCOPE_24H).strip().lower()
    if scope in {"24h", "24", "last_24h", "last-24h", "rolling_window"}:
        return COLLECTION_SCOPE_24H
    if scope in {"all", "all_time", "all-time", "full"}:
        return COLLECTION_SCOPE_ALL
    raise ValueError("unsupported_collection_scope")


def refresh_command(root_dir: Path, collection_scope: str = COLLECTION_SCOPE_24H) -> list[str]:
    scope = normalize_collection_scope(collection_scope)
    command = [
        sys.executable,
        str(root_dir / "scripts" / "update_news.py"),
        "--source-config",
        CONFIG_FILENAME,
        "--output-dir",
        "data",
        "--window-hours",
        "24",
        "--archive-days",
        "3650",
        "--all-time",
    ]
    if scope == COLLECTION_SCOPE_24H:
        command.extend(["--collect-window-hours", "24"])
    return command


def refresh_env(root_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    cookie_status = bilibili_cookie_status(root_dir)
    if (
        cookie_status.get("cookie_file_exists")
        and not str(env.get("BILIBILI_COOKIE_FILE") or env.get("BILIBILI_DYNAMIC_COOKIE_FILE") or "").strip()
        and not str(env.get("BILIBILI_COOKIE") or env.get("BILIBILI_DYNAMIC_COOKIE") or "").strip()
    ):
        env["BILIBILI_COOKIE_FILE"] = str(cookie_status["cookie_file"])
    return env


def source_status_summary(root_dir: Path, source_config: dict[str, Any] | None = None) -> dict[str, Any]:
    config_issues = local_config_maintenance_issues(root_dir, source_config) if source_config else []
    payload = read_source_status(root_dir)
    if not payload:
        issues = dedupe_maintenance_issues(
            [
                {
                    "id": "source_status_missing",
                    "severity": "warn",
                    "source_id": "source_status",
                    "title": "还没有刷新状态",
                    "detail": "data/source-status.json 不存在或还没生成。",
                    "action": "先点一次读取结果，生成本地源状态。",
                },
                *config_issues,
            ]
        )
        return {
            "maintenance_issues": issues,
            "issue_count": len(issues),
            "needs_attention": True,
        }
    issues = dedupe_maintenance_issues([*maintenance_issues_from_status(payload, root_dir), *config_issues])
    ok_sites = sum(1 for site in payload.get("sites", []) if isinstance(site, dict) and site.get("ok") is True)
    return {
        "generated_at": payload.get("generated_at"),
        "source_scope": payload.get("source_scope"),
        "fetched_raw_items": payload.get("fetched_raw_items"),
        "successful_sites": payload.get("successful_sites", ok_sites),
        "site_count": len(payload.get("sites", [])),
        "issue_count": len(issues),
        "needs_attention": bool(issues),
        "maintenance_issues": issues,
        "sites": [
            {
                "site_id": site.get("site_id"),
                "site_name": site.get("site_name"),
                "ok": site.get("ok"),
                "item_count": site.get("item_count"),
                "source_name": site.get("source_name"),
                "error": site.get("error"),
                "cookie_present": site.get("cookie_present"),
                "fetch_mode": site.get("fetch_mode"),
            }
            for site in payload.get("sites", [])
            if isinstance(site, dict)
        ],
        "bilibili_cookie": bilibili_cookie_status(root_dir),
    }


def source_config_summary_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"exists": False, "source_count": 0, "enabled_source_count": 0, "enabled_sources": []}
    sources = [source for source in payload.get("sources", []) if isinstance(source, dict)]
    enabled = [source for source in sources if source.get("enabled") is not False]
    return {
        "exists": True,
        "source_count": len(sources),
        "enabled_source_count": len(enabled),
        "updated_at": payload.get("updated_at"),
        "enabled_sources": [
            {
                "id": source.get("id"),
                "name": source.get("name"),
                "type": source.get("type"),
                "channel": source.get("channel"),
                "target": source.get("target"),
            }
            for source in enabled[:50]
        ],
    }


def source_config_summary(root_dir: Path) -> dict[str, Any]:
    return source_config_summary_from_payload(read_source_config(root_dir))


def local_status_payload(root_dir: Path) -> dict[str, Any]:
    config_payload: dict[str, Any] | None = None
    try:
        config_payload = read_source_config(root_dir)
        config = source_config_summary_from_payload(config_payload)
    except Exception as exc:
        config = {"exists": True, "ok": False, "error": str(exc), "source_count": 0, "enabled_source_count": 0, "enabled_sources": []}
    summary = source_status_summary(root_dir, config_payload)
    if config.get("ok") is False:
        issues = dedupe_maintenance_issues(
            [
                *summary.get("maintenance_issues", []),
                {
                    "id": "source_config_invalid",
                    "severity": "bad",
                    "source_id": "source_config",
                    "title": "sources.config.json 读取失败",
                    "detail": str(config.get("error") or "配置文件格式不正确。"),
                    "action": "在页面里重新写入配置，或检查 sources.config.json 是否是合法 JSON。",
                },
            ]
        )
        summary["maintenance_issues"] = issues
        summary["issue_count"] = len(issues)
        summary["needs_attention"] = True
    return {
        "ok": True,
        "source_config": config,
        "source_status": summary,
        "collectors": {
            "mediacrawler_douyin": mediacrawler_douyin_collector_status(root_dir),
            "mediacrawler_xhs": mediacrawler_xhs_collector_status(root_dir),
        },
        "refresh_running": REFRESH_LOCK.locked(),
    }


def maintenance_actions_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    issues = payload.get("source_status", {}).get("maintenance_issues", [])
    if not isinstance(issues, list):
        return actions
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        for action in issue.get("fix_actions") or []:
            if not isinstance(action, dict):
                continue
            action_id = str(action.get("id") or "")
            if not action_id or action_id in seen:
                continue
            seen.add(action_id)
            actions.append(action)
    return actions


def find_maintenance_action(root_dir: Path, action_id: str) -> dict[str, Any] | None:
    action_id = str(action_id or "").strip()
    if not action_id:
        return None
    for action in maintenance_actions_from_payload(local_status_payload(root_dir)):
        if action.get("id") == action_id:
            return action
    return None


def launch_open_path(target: Path) -> None:
    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def perform_maintenance_action(
    root_dir: Path,
    action_id: str,
    *,
    execute: bool = True,
    collection_scope: str = COLLECTION_SCOPE_24H,
) -> dict[str, Any]:
    scope = normalize_collection_scope(collection_scope)
    fixed_start_actions = {
        "start_mediacrawler_douyin": start_mediacrawler_douyin,
        "start_mediacrawler_xhs": start_mediacrawler_xhs,
    }
    direct_start_action = fixed_start_actions.get(str(action_id or "").strip())
    if direct_start_action:
        return direct_start_action(root_dir, execute=execute, collection_scope=scope)

    action = find_maintenance_action(root_dir, action_id)
    if not action:
        return {"ok": False, "error": "maintenance_action_not_found"}

    kind = str(action.get("kind") or "")
    if kind == "open_path":
        raw_path = str(action.get("path") or "").strip()
        if not raw_path:
            return {"ok": False, "error": "maintenance_action_path_missing"}
        if action.get("id") == "open_bilibili_cookie_folder":
            target = (root_dir / BILIBILI_DEFAULT_COOKIE_FILE.parent).resolve()
            target.mkdir(parents=True, exist_ok=True)
            if execute:
                launch_open_path(target)
            return {
                "ok": True,
                "kind": kind,
                "action_id": action.get("id"),
                "label": action.get("label"),
                "opened_path": str(target),
                "recommended_cookie_file": str(root_dir / BILIBILI_DEFAULT_COOKIE_FILE),
                "executed": execute,
            }
        target = existing_open_target(Path(raw_path))
        if not target:
            return {"ok": False, "error": "maintenance_action_path_not_found", "path": raw_path}
        if execute:
            launch_open_path(target)
        return {
            "ok": True,
            "kind": kind,
            "action_id": action.get("id"),
            "label": action.get("label"),
            "opened_path": str(target),
            "executed": execute,
        }
    if kind == "open_url":
        return {
            "ok": True,
            "kind": kind,
            "action_id": action.get("id"),
            "label": action.get("label"),
            "url": action.get("url"),
            "executed": False,
        }
    if kind == "start_service":
        action_id = str(action.get("id") or "")
        if action_id == "open_bilibili_login":
            return launch_bilibili_dedicated_browser(root_dir, execute=execute)
        if action_id == "sync_bilibili_cookie":
            return sync_bilibili_cookie(root_dir, execute=execute)
        if action_id == "start_wewe_rss_sidecar":
            return start_wewe_rss_sidecar(root_dir, execute=execute)
        if action_id == "start_mediacrawler_douyin":
            return start_mediacrawler_douyin(root_dir, execute=execute, collection_scope=scope)
        if action_id == "start_mediacrawler_xhs":
            return start_mediacrawler_xhs(root_dir, execute=execute, collection_scope=scope)
        return {"ok": False, "error": "unsupported_start_service", "action_id": action_id}
    return {"ok": False, "error": "unsupported_maintenance_action", "kind": kind}


class LocalRadarHandler(SimpleHTTPRequestHandler):
    server_version = "AIReadRadarLocal/0.1"

    @property
    def root_dir(self) -> Path:
        return Path(self.server.root_dir).resolve()  # type: ignore[attr-defined]

    @property
    def config_path(self) -> Path:
        return (self.root_dir / CONFIG_FILENAME).resolve()

    def reject_nonlocal_origin(self) -> bool:
        origin = self.headers.get("Origin", "")
        referer = self.headers.get("Referer", "")
        if is_local_origin(origin) and is_local_origin(referer):
            return False
        json_response(self, HTTPStatus.FORBIDDEN, {"ok": False, "error": "non_local_origin"})
        return True

    def do_GET(self) -> None:
        route = self.path.split("?", 1)[0]
        if route == "/api/local-status":
            try:
                json_response(self, HTTPStatus.OK, local_status_payload(self.root_dir))
            except Exception as exc:
                json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        if route == "/api/wewe-rss/feeds":
            payload = read_wewe_rss_feeds()
            status = HTTPStatus.OK if payload.get("ok") else HTTPStatus.BAD_GATEWAY
            if payload.get("error") == "wewe_rss_base_url_not_local":
                status = HTTPStatus.BAD_REQUEST
            json_response(self, status, payload)
            return
        if route == "/api/subscriptions/youtube":
            try:
                subscriptions = read_youtube_subscriptions(self.root_dir)
                json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "path": str(OPML_FILENAME).replace("\\", "/"),
                        "subscriptions": subscriptions,
                    },
                )
            except Exception as exc:
                json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        if route != "/api/source-config":
            return super().do_GET()
        if self.config_path.parent != self.root_dir or self.config_path.name != CONFIG_FILENAME:
            json_response(self, HTTPStatus.FORBIDDEN, {"ok": False, "error": "invalid_config_path"})
            return
        if not self.config_path.exists():
            json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "source_config_not_found"})
            return
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            validate_source_config(payload)
        except Exception as exc:
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        json_response(self, HTTPStatus.OK, {"ok": True, "path": CONFIG_FILENAME, "config": payload})

    def do_POST(self) -> None:
        route = self.path.split("?", 1)[0]
        if route == "/api/maintenance-action":
            self.handle_maintenance_action()
            return
        if route == "/api/refresh":
            self.handle_refresh()
            return
        if route == "/api/subscriptions/youtube":
            self.handle_youtube_subscriptions()
            return
        if route != "/api/source-config":
            json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        if self.reject_nonlocal_origin():
            return
        if self.config_path.parent != self.root_dir or self.config_path.name != CONFIG_FILENAME:
            json_response(self, HTTPStatus.FORBIDDEN, {"ok": False, "error": "invalid_config_path"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_CONFIG_BYTES:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_content_length"})
            return
        if "application/json" not in str(self.headers.get("Content-Type") or ""):
            json_response(self, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "json_required"})
            return
        try:
            raw = self.rfile.read(length)
            payload = validate_source_config(json.loads(raw.decode("utf-8")))
            payload["updated_at"] = payload.get("updated_at") or ""
            previous_config: dict[str, Any] | None = None
            if self.config_path.exists():
                try:
                    previous_config = json.loads(self.config_path.read_text(encoding="utf-8"))
                except Exception:
                    previous_config = None
            body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            tmp_path = self.config_path.with_suffix(".json.tmp")
            tmp_path.write_text(body, encoding="utf-8")
            os.replace(tmp_path, self.config_path)
        except Exception as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        purged_items: dict[str, Any]
        if REFRESH_LOCK.acquire(blocking=False):
            try:
                purged_items = purge_deleted_source_data(self.root_dir, payload, previous_config=previous_config)
            except Exception as exc:
                purged_items = {"error": str(exc)}
            finally:
                REFRESH_LOCK.release()
        else:
            purged_items = {"skipped": "refresh_in_progress"}
        json_response(
            self,
            HTTPStatus.OK,
            {
                "ok": True,
                "path": CONFIG_FILENAME,
                "source_count": len(payload.get("sources") or []),
                "purged_items": purged_items,
            },
        )

    def handle_youtube_subscriptions(self) -> None:
        if self.reject_nonlocal_origin():
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_SUBSCRIPTION_BYTES:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_content_length"})
            return
        if "application/json" not in str(self.headers.get("Content-Type") or ""):
            json_response(self, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "json_required"})
            return
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            subscriptions = write_youtube_subscriptions(self.root_dir, payload.get("subscriptions"))
        except Exception as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        json_response(
            self,
            HTTPStatus.OK,
            {
                "ok": True,
                "path": str(OPML_FILENAME).replace("\\", "/"),
                "subscription_count": len(subscriptions),
                "subscriptions": subscriptions,
            },
        )

    def handle_maintenance_action(self) -> None:
        if self.reject_nonlocal_origin():
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_ACTION_BYTES:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_content_length"})
            return
        if "application/json" not in str(self.headers.get("Content-Type") or ""):
            json_response(self, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "json_required"})
            return
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
            action_id = str(payload.get("action_id") or "").strip()
            try:
                collection_scope = normalize_collection_scope(payload.get("collection_scope"))
            except ValueError:
                json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "unsupported_collection_scope",
                        "allowed_scopes": sorted(COLLECTION_SCOPES),
                    },
                )
                return
            result = perform_maintenance_action(self.root_dir, action_id, collection_scope=collection_scope)
        except Exception as exc:
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
        json_response(self, status, result)

    def handle_refresh(self) -> None:
        if self.reject_nonlocal_origin():
            return
        if not self.config_path.exists():
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "source_config_not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length < 0 or length > MAX_ACTION_BYTES:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_content_length"})
            return
        payload: dict[str, Any] = {}
        if length:
            if "application/json" not in str(self.headers.get("Content-Type") or ""):
                json_response(self, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "json_required"})
                return
            try:
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("payload must be a JSON object")
            except Exception as exc:
                json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return
        try:
            collection_scope = normalize_collection_scope(payload.get("collection_scope"))
        except ValueError:
            json_response(
                self,
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "unsupported_collection_scope",
                    "allowed_scopes": sorted(COLLECTION_SCOPES),
                },
            )
            return
        if not REFRESH_LOCK.acquire(blocking=False):
            json_response(self, HTTPStatus.CONFLICT, {"ok": False, "error": "refresh_already_running"})
            return
        try:
            result = subprocess.run(
                refresh_command(self.root_dir, collection_scope),
                cwd=self.root_dir,
                env=refresh_env(self.root_dir),
                capture_output=True,
                text=True,
                timeout=REFRESH_TIMEOUT_SECONDS,
                check=False,
            )
            if result.returncode != 0:
                json_response(
                    self,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "refresh_failed",
                        "returncode": result.returncode,
                        "stderr_tail": result.stderr[-4000:],
                        "stdout_tail": result.stdout[-2000:],
                    },
                )
                return
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "collection_scope": collection_scope,
                    "summary": source_status_summary(self.root_dir),
                    "stdout_tail": result.stdout[-2000:],
                },
            )
        except subprocess.TimeoutExpired as exc:
            json_response(
                self,
                HTTPStatus.REQUEST_TIMEOUT,
                {
                    "ok": False,
                    "error": "refresh_timeout",
                    "timeout_seconds": REFRESH_TIMEOUT_SECONDS,
                    "stdout_tail": (exc.stdout or "")[-2000:],
                    "stderr_tail": (exc.stderr or "")[-4000:],
                },
            )
        except Exception as exc:
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
        finally:
            REFRESH_LOCK.release()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve AI News Radar locally and save sources.config.json")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host; keep 127.0.0.1 for local-only use")
    parser.add_argument("--port", type=int, default=8080, help="Bind port")
    parser.add_argument("--directory", default=".", help="Static site root")
    args = parser.parse_args()

    root_dir = Path(args.directory).resolve()
    if not root_dir.exists():
        print(f"Directory not found: {root_dir}", file=sys.stderr)
        return 2

    class Handler(LocalRadarHandler):
        def __init__(self, *handler_args: Any, **handler_kwargs: Any) -> None:
            super().__init__(*handler_args, directory=str(root_dir), **handler_kwargs)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.root_dir = root_dir  # type: ignore[attr-defined]
    print(f"Serving {root_dir} at http://{args.host}:{args.port}/")
    print(f"Config endpoint: http://{args.host}:{args.port}/api/source-config")
    print(f"Refresh endpoint: http://{args.host}:{args.port}/api/refresh")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
