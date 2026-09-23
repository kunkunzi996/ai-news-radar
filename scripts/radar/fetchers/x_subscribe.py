"""指定推特号的快照读取。

云端不拿登录态。NUC 上的 RSSHub 先把指定号收成 JSONL，
采集时只读这份快照，条目进「推特订阅」，不进 AI HOT。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from scripts.radar.common import RawItem, make_item_id, parse_date_any

X_SUBSCRIBE_SITE_ID = "x_subscribe"
X_SUBSCRIBE_SITE_NAME = "推特订阅"
X_SUBSCRIBE_JSONL = Path("feeds") / "x-subscribe.jsonl"
_TAG_RE = re.compile(r"<[^>]+>")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,20}$")
_STATUS_RE = re.compile(
    r"^https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,20})/status/\d+",
    re.I,
)


def x_subscribe_jsonl_path() -> Path:
    raw = str(os.environ.get("X_SUBSCRIBE_JSONL") or "").strip()
    return Path(raw) if raw else X_SUBSCRIBE_JSONL


def normalize_x_handle(value: str) -> str:
    return str(value or "").strip().lstrip("@")


def _plain_text(value: str) -> str:
    text = unescape(str(value or ""))
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = _TAG_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _row_from_rss_item(item: ElementTree.Element) -> dict[str, str] | None:
    link = str(item.findtext("link") or item.findtext("guid") or "").strip()
    matched = _STATUS_RE.match(link)
    if not matched:
        return None
    title = _plain_text(item.findtext("title") or "")
    if not title:
        return None
    author = _plain_text(item.findtext("author") or "")
    summary = _plain_text(item.findtext("description") or "")
    return {
        "handle": matched.group(1),
        "name": author,
        "title": title[:180],
        "url": link,
        "published_at": str(item.findtext("pubDate") or "").strip(),
        "summary": (summary or title)[:280],
    }


def rows_from_rss_xml(text: str) -> list[dict[str, str]]:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return []
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in root.findall("./channel/item"):
        row = _row_from_rss_item(item)
        if not row or row["url"] in seen:
            continue
        seen.add(row["url"])
        rows.append(row)
    return rows


def parse_x_subscribe_jsonl(
    text: str,
    *,
    now: datetime,
    allowed_handles: set[str] | None = None,
    names_by_handle: dict[str, str] | None = None,
    max_items: int = 100,
) -> list[RawItem]:
    names = {key.lower(): value for key, value in (names_by_handle or {}).items()}
    allowed = {handle.lower() for handle in allowed_handles} if allowed_handles is not None else None
    items: list[RawItem] = []
    for line in text.splitlines():
        if len(items) >= max_items:
            break
        raw = line.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        matched = _STATUS_RE.match(url)
        title = _plain_text(str(row.get("title") or ""))
        if not matched or not title:
            continue
        handle = normalize_x_handle(str(row.get("handle") or matched.group(1)))
        if not _HANDLE_RE.fullmatch(handle):
            continue
        if allowed is not None and handle.lower() not in allowed:
            continue
        display = names.get(handle.lower()) or _plain_text(str(row.get("name") or "")) or handle
        summary = _plain_text(str(row.get("summary") or "")) or title
        items.append(
            RawItem(
                site_id=X_SUBSCRIBE_SITE_ID,
                site_name=X_SUBSCRIBE_SITE_NAME,
                source=display[:120],
                title=title[:180],
                url=url,
                published_at=parse_date_any(row.get("published_at"), now),
                meta={
                    "summary": summary[:280],
                    "x_handle": handle,
                    "item_id": make_item_id(X_SUBSCRIBE_SITE_ID, display, title, url),
                },
            )
        )
    return items


def fetch_x_subscribe_items(
    subscriptions: list[dict[str, Any]],
    now: datetime,
) -> tuple[list[RawItem], dict[str, Any]]:
    path = x_subscribe_jsonl_path()
    allowed = {
        normalize_x_handle(str(item.get("locator") or "")).lower()
        for item in subscriptions
        if normalize_x_handle(str(item.get("locator") or ""))
    }
    names = {
        normalize_x_handle(str(item.get("locator") or "")).lower(): str(item.get("name") or item.get("target") or "").strip()
        for item in subscriptions
        if normalize_x_handle(str(item.get("locator") or ""))
    }
    status: dict[str, Any] = {
        "enabled": True,
        "ok": None,
        "item_count": 0,
        "source_kind": X_SUBSCRIBE_SITE_ID,
        "privacy": "snapshot_only_no_login_state",
        "coverage_note": "reads_x_subscribe_jsonl",
        "jsonl_file": path.name,
        "subscription_count": len(allowed),
    }
    if not path.is_file():
        status["ok"] = False
        status["error"] = "x_subscribe_jsonl_not_found"
        return [], status
    try:
        items = parse_x_subscribe_jsonl(
            path.read_text(encoding="utf-8"),
            now=now,
            allowed_handles=allowed or None,
            names_by_handle=names,
        )
    except OSError as exc:
        status["ok"] = False
        status["error"] = str(exc)
        return [], status
    status["ok"] = True
    status["item_count"] = len(items)
    if not items:
        status["error"] = "x_subscribe_no_items"
    return items, status
