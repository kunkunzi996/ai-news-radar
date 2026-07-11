from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from scripts.radar.common import (
    BROWSER_UA,
    GITHUB_REPO_SUBSCRIPTION_API_URL,
    GITHUB_REPO_SUBSCRIPTION_BACKFILL_MAX_ITEMS,
    GITHUB_REPO_SUBSCRIPTION_HTML_URL,
    GITHUB_REPO_SUBSCRIPTION_MAX_ITEMS,
    GITHUB_REPO_SUBSCRIPTION_SITE_ID,
    GITHUB_REPO_SUBSCRIPTION_SITE_NAME,
    MAOBIDAO_WECHAT_API_URL,
    MAOBIDAO_WECHAT_HOME_URL,
    MAOBIDAO_WECHAT_MAX_ITEMS,
    MAOBIDAO_WECHAT_SITE_ID,
    MAOBIDAO_WECHAT_SITE_NAME,
    OPML_RSS_DEFAULT_MAX_ITEMS_PER_FEED,
    RSS_FEED_REPLACEMENTS,
    RSS_FEED_SKIP_EXACT,
    RSS_FEED_SKIP_PREFIXES,
    RawItem,
    UTC,
    WE_MP_RSS_BASE_URL_DEFAULT,
    WE_MP_RSS_DEFAULT_MAX_ITEMS,
    WE_MP_RSS_JSONL_DEFAULT_MAX_ITEMS,
    WE_MP_RSS_JSONL_SITE_ID,
    WE_MP_RSS_JSONL_SITE_NAME,
    WE_MP_RSS_SITE_ID,
    WE_MP_RSS_SITE_NAME,
    WEWE_RSS_BASE_URL_DEFAULT,
    WEWE_RSS_DEFAULT_MAX_ITEMS,
    WEWE_RSS_SITE_ID,
    WEWE_RSS_SITE_NAME,
    env_int,
    first_collect_backfill_days,
    first_non_empty,
    trim_first_collect_backfill_items,
    host_of_url,
    normalize_url,
    parse_date_any,
    parse_feed_entries_via_xml,
)

try:
    import feedparser
except ModuleNotFoundError:
    feedparser = None

"""Subscription and bridge source fetchers."""

def fetch_github_repo_subscription(
    session: requests.Session,
    now: datetime,
    *,
    api_url: str = GITHUB_REPO_SUBSCRIPTION_API_URL,
    repo_label: str = "AlkaidLab/foundation-sunshine",
    site_name: str = GITHUB_REPO_SUBSCRIPTION_SITE_NAME,
    display_name: str = "",
    max_items: int = GITHUB_REPO_SUBSCRIPTION_MAX_ITEMS,
    first_collect_backfill: bool = False,
) -> list[RawItem]:
    fetch_count = GITHUB_REPO_SUBSCRIPTION_BACKFILL_MAX_ITEMS if first_collect_backfill else int(max_items or 1)
    params = {"per_page": max(1, min(100, fetch_count))}
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AI-News-Radar/0.7 github-release-subscription",
    }
    github_token = str(os.environ.get("GITHUB_TOKEN") or "").strip()
    if github_token and urlparse(api_url).netloc.lower() == "api.github.com":
        headers["Authorization"] = f"Bearer {github_token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    resp = session.get(
        api_url,
        params=params,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list):
        return []

    out: list[RawItem] = []
    seen: set[str] = set()
    for release in payload[:fetch_count]:
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
        title = f"{repo_label} {release_type}: {name}"
        out.append(
            RawItem(
                site_id=GITHUB_REPO_SUBSCRIPTION_SITE_ID,
                site_name=site_name,
                source=display_name or "GitHub版本订阅",
                title=title,
                url=url,
                published_at=published,
                meta={
                    "summary": title,
                    "source_kind": "github_release_subscription",
                    "repo": repo_label,
                    "tag_name": tag,
                    "release_name": name,
                    "prerelease": bool(release.get("prerelease")),
                },
            )
        )
    if first_collect_backfill:
        out = trim_first_collect_backfill_items(out, now, keep_latest=int(max_items or 1))
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


def we_mp_rss_base_url() -> str:
    return (os.environ.get("WE_MP_RSS_BASE_URL") or WE_MP_RSS_BASE_URL_DEFAULT).strip().rstrip("/")


def parse_we_mp_rss_feed_items(
    feed_content: bytes,
    now: datetime,
    *,
    source_name: str,
    feed_id: str,
    max_items: int,
) -> list[RawItem]:
    if feedparser is None:
        return []
    parsed = feedparser.parse(feed_content)
    out: list[RawItem] = []
    seen: set[str] = set()
    for entry in parsed.entries:
        if len(out) >= max_items:
            break
        title = clean_wp_rendered_text(entry.get("title"), max_chars=160)
        url = normalize_url(first_non_empty(entry.get("link")))
        if not title or not url:
            continue
        key = url or title
        if key in seen:
            continue
        seen.add(key)
        published = parse_date_any(
            first_non_empty(entry.get("published"), entry.get("updated")),
            now,
        ) or now
        summary = clean_wp_rendered_text(
            first_non_empty(entry.get("summary"), entry.get("description")),
            max_chars=220,
        )
        out.append(
            RawItem(
                site_id=WE_MP_RSS_SITE_ID,
                site_name=WE_MP_RSS_SITE_NAME,
                source=source_name or "WeRSS",
                title=title,
                url=url,
                published_at=published,
                meta={
                    "summary": summary or title,
                    "source_kind": "we_mp_rss_wechat_subscription",
                    "wechat_account": source_name,
                    "we_mp_feed_id": feed_id,
                    "search_surface": "we_mp_rss_xml_feed",
                },
            )
        )
    return out


def discover_we_mp_rss_feeds(session: requests.Session, base: str) -> list[dict[str, str]]:
    """从 {base}/rss 的订阅列表 RSS 里提取 feed id（item link 形如 .../rss/{feed_id}）。"""
    resp = session.get(
        f"{base}/rss",
        params={"limit": 30},
        headers={"Accept": "application/xml", "User-Agent": "AI-News-Radar/0.7 we-mp-rss-bridge"},
        timeout=15,
    )
    resp.raise_for_status()
    if feedparser is None:
        return []
    parsed = feedparser.parse(resp.content)
    feeds: list[dict[str, str]] = []
    for entry in parsed.entries:
        # sidecar 的 /rss 列表里 item link/guid 形如 "rss/MP_WXS_xxx"（无前导斜杠），
        # 也可能是 "/rss/xxx" 或绝对 URL；放宽匹配，不强制前导斜杠。
        link = first_non_empty(entry.get("link")) or first_non_empty(entry.get("id")) or ""
        match = re.search(r"(?:^|/)rss/([^/?#]+)", link)
        if not match:
            continue
        feeds.append({"id": match.group(1), "name": first_non_empty(entry.get("title")) or match.group(1)})
    return feeds


def fetch_we_mp_rss_subscription(
    session: requests.Session,
    now: datetime,
    *,
    base_url: str | None = None,
    feeds_config: str | None = None,
    max_items: int | None = None,
) -> tuple[list[RawItem], dict[str, Any]]:
    start = time.perf_counter()
    base = (base_url or we_mp_rss_base_url()).strip().rstrip("/")
    max_items_per_feed = max(1, min(100, int(max_items or env_int("WE_MP_RSS_MAX_ITEMS", WE_MP_RSS_DEFAULT_MAX_ITEMS))))
    status: dict[str, Any] = {
        "enabled": True,
        "ok": False,
        "item_count": 0,
        "duration_ms": 0,
        "error": None,
        "source_kind": "we_mp_rss_wechat_subscription",
        "base_url": base,
        "max_items_per_feed": max_items_per_feed,
        "feeds": [],
        "coverage_note": "reads_local_we_mp_rss_xml_feed_without_wechat_login_state",
        "privacy": "local_sidecar_no_cookies_in_radar_repo",
    }
    if not base:
        status["error"] = "missing_we_mp_rss_base_url"
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)
        return [], status
    if feedparser is None:
        status["error"] = "feedparser_missing"
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)
        return [], status

    configured_feeds = wewe_rss_feeds_from_env(feeds_config if feeds_config is not None else os.environ.get("WE_MP_RSS_FEEDS"))
    try:
        feeds = configured_feeds or discover_we_mp_rss_feeds(session, base)
        if not feeds:
            status["ok"] = True
            status["error"] = "we_mp_rss_no_feeds"
            return [], status

        all_items: list[RawItem] = []
        feed_statuses: list[dict[str, Any]] = []
        for feed in feeds:
            feed_id = feed["id"]
            source_name = feed.get("name") or feed_id
            feed_status = {"id": feed_id, "name": source_name, "ok": False, "item_count": 0, "error": None}
            try:
                resp = session.get(
                    f"{base}/feed/{feed_id}.rss",
                    params={"limit": max_items_per_feed},
                    headers={"Accept": "application/xml", "User-Agent": "AI-News-Radar/0.7 we-mp-rss-bridge"},
                    timeout=20,
                )
                resp.raise_for_status()
                items = parse_we_mp_rss_feed_items(
                    resp.content,
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
            status["error"] = f"failed_we_mp_rss_feeds:{len(failed)}"
        return all_items, status
    except Exception as exc:
        status["error"] = str(exc)
        return [], status
    finally:
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)



def parse_we_mp_rss_jsonl_items(
    jsonl_text: str,
    now: datetime,
    *,
    max_items: int,
) -> list[RawItem]:
    out: list[RawItem] = []
    seen_urls: set[str] = set()
    limit = max(1, min(1000, int(max_items)))
    for line in str(jsonl_text or "").splitlines():
        if len(out) >= limit:
            break
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        url = normalize_url(first_non_empty(payload.get("url")))
        title = clean_wp_rendered_text(payload.get("title"), max_chars=160)
        if not url or not title or url in seen_urls:
            continue
        seen_urls.add(url)
        account = clean_wp_rendered_text(payload.get("account"), max_chars=80) or WE_MP_RSS_JSONL_SITE_NAME
        summary = clean_wp_rendered_text(payload.get("summary"), max_chars=500)
        feed_id = first_non_empty(payload.get("feed_id"))
        published_at = parse_date_any(payload.get("published_at"), now)
        out.append(
            RawItem(
                site_id=WE_MP_RSS_JSONL_SITE_ID,
                site_name=WE_MP_RSS_JSONL_SITE_NAME,
                source=account,
                title=title,
                url=url,
                published_at=published_at,
                meta={
                    "summary": summary,
                    "we_mp_feed_id": feed_id,
                    "source_kind": "we_mp_rss_wechat_subscription",
                    "search_surface": "we_mp_rss_jsonl_bridge",
                },
            )
        )
    return out


def fetch_we_mp_rss_jsonl_subscription(
    session: requests.Session,
    now: datetime,
    *,
    jsonl_dir: str | None = None,
    max_items: int | None = None,
) -> tuple[list[RawItem], dict[str, Any]]:
    del session
    start = time.perf_counter()
    configured_dir = str(jsonl_dir if jsonl_dir is not None else os.environ.get("WE_MP_RSS_JSONL_DIR") or "").strip()
    limit = max(1, min(1000, int(max_items or env_int("WE_MP_RSS_JSONL_MAX_ITEMS", WE_MP_RSS_JSONL_DEFAULT_MAX_ITEMS))))
    jsonl_path = Path(configured_dir).expanduser() / "wechat_contents_latest.jsonl" if configured_dir else Path()
    status: dict[str, Any] = {
        "enabled": True,
        "ok": False,
        "item_count": 0,
        "duration_ms": 0,
        "error": None,
        "source_kind": WE_MP_RSS_JSONL_SITE_ID,
        "jsonl_dir": configured_dir,
        "jsonl_file": jsonl_path.name if configured_dir else None,
        "max_items": limit,
        "coverage_note": "reads_we_mp_rss_bridge_jsonl",
        "privacy": "public_article_fields_only_no_cookies_or_auth_state",
    }
    try:
        if not configured_dir or not jsonl_path.is_file():
            status["error"] = "missing_we_mp_rss_jsonl"
            return [], status
        items = parse_we_mp_rss_jsonl_items(jsonl_path.read_text(encoding="utf-8-sig"), now, max_items=limit)
        status["ok"] = True
        status["item_count"] = len(items)
        return items, status
    except OSError as exc:
        status["error"] = str(exc)
        return [], status
    finally:
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)


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
    existing_source_keys: frozenset[tuple[str, str]] | set[tuple[str, str]] | None = None,
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

        first_collect_backfill = False
        if local_items:
            local_items.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=UTC), reverse=True)
            backfill_days = first_collect_backfill_days()
            # 归档里从未出现过的 feed：首采回填，保留窗口内全部条目而非只截最近 5 条。
            first_collect_backfill = (
                existing_source_keys is not None
                and backfill_days > 0
                and all(("opmlrss", item.source) not in existing_source_keys for item in local_items)
            )
            if first_collect_backfill:
                local_items = trim_first_collect_backfill_items(
                    local_items,
                    now,
                    keep_latest=OPML_RSS_DEFAULT_MAX_ITEMS_PER_FEED,
                    backfill_days=backfill_days,
                )
            else:
                local_items = local_items[:OPML_RSS_DEFAULT_MAX_ITEMS_PER_FEED]

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
            "max_items": OPML_RSS_DEFAULT_MAX_ITEMS_PER_FEED,
            "first_collect_backfill": first_collect_backfill,
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
        "max_items_per_feed": OPML_RSS_DEFAULT_MAX_ITEMS_PER_FEED,
    }
    return out, summary_status, feed_statuses



