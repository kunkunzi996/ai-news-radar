from __future__ import annotations

import argparse
from collections import Counter
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
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scripts.ai_relevance import add_ai_relevance_fields, score_ai_relevance

try:
    import feedparser
except ModuleNotFoundError:
    feedparser = None

from scripts.radar.common import *  # noqa: F401,F403

"""Public web and RSS source fetchers."""

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



