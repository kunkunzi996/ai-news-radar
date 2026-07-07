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

"""Local MediaCrawler JSONL bridge fetchers."""

def fetch_mediacrawler_douyin_subscriptions(
    subscriptions: list[dict[str, str]],
    now: datetime,
) -> tuple[list[RawItem], dict[str, Any]]:
    if not subscriptions:
        return maybe_fetch_mediacrawler_douyin(now)

    start = time.perf_counter()
    out: list[RawItem] = []
    children: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_items = max(1, min(env_int("MEDIACRAWLER_DOUYIN_MAX_ITEMS", 200), 1000))
    for subscription in subscriptions:
        raw_locator = str(subscription.get("locator") or "").strip()
        jsonl_path_raw = mediacrawler_jsonl_locator(raw_locator, MEDIACRAWLER_DOUYIN_SITE_ID)
        source_name = str(subscription.get("target") or subscription.get("name") or "").strip()
        child = {
            "name": source_name,
            "locator": raw_locator,
            "locator_kind": "homepage_url" if is_url_like(raw_locator) else "jsonl_path",
            "jsonl_file_configured": Path(jsonl_path_raw).name if jsonl_path_raw else None,
            "item_count": 0,
            "ok": None,
        }
        try:
            jsonl_path = resolve_latest_mediacrawler_jsonl(jsonl_path_raw)
            child["jsonl_file"] = jsonl_path.name
            if jsonl_path.name != child.get("jsonl_file_configured"):
                child["jsonl_file_resolved_from"] = child.get("jsonl_file_configured")
            if not jsonl_path.exists():
                child["ok"] = False
                child["error"] = "mediacrawler_douyin_jsonl_not_found"
                children.append(child)
                continue
            items = parse_mediacrawler_douyin_jsonl(
                jsonl_path.read_text(encoding="utf-8", errors="ignore"),
                now=now,
                source_name=source_name,
                max_items=max_items,
            )
            items = [
                item
                for item in items
                if douyin_item_matches_subscription(item, locator=raw_locator, source_name=source_name)
            ]
            for item in items:
                key = f"{item.site_id}:{normalize_url(item.url)}:{item.title}"
                if key in seen:
                    continue
                seen.add(key)
                out.append(item)
            child["ok"] = bool(items)
            child["item_count"] = len(items)
            if not items:
                child["error"] = "mediacrawler_douyin_no_items"
        except Exception as exc:
            child["ok"] = False
            child["error"] = str(exc)
        children.append(child)

    return out, {
        "enabled": True,
        "ok": bool(out),
        "item_count": len(out),
        "source_kind": MEDIACRAWLER_DOUYIN_SITE_ID,
        "privacy": "local_jsonl_only_no_cookies",
        "coverage_note": "reads_mediacrawler_douyin_creator_jsonl",
        "jsonl_path_configured": any(child.get("jsonl_file_configured") for child in children),
        "jsonl_file": children[0].get("jsonl_file") if children else None,
        "source_name": ", ".join(child.get("name") or "" for child in children if child.get("name")),
        "max_items": max_items,
        "subscriptions": children,
        "subscription_count": len(children),
        "error": None if out else "mediacrawler_douyin_no_items",
        "duration_ms": int((time.perf_counter() - start) * 1000),
    }


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
            row.get("nickname"),
            row.get("user_nickname"),
            row.get("user_id"),
            source_name,
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


def xiaohongshu_item_matches_subscription(item: RawItem, *, locator: str, source_name: str) -> bool:
    expected_user_id = xiaohongshu_user_id_from_locator(locator)
    if expected_user_id:
        return str(item.meta.get("xiaohongshu_user_id") or "").strip() == expected_user_id
    if source_name:
        return str(item.source or "").strip() == source_name
    return True


def maybe_fetch_mediacrawler_xhs(now: datetime) -> tuple[list[RawItem], dict[str, Any]]:
    raw_locator = mediacrawler_env_first("MEDIACRAWLER_XHS_JSONL", "MEDIACRAWLER_XIAOHONGSHU_JSONL")
    jsonl_path_raw = mediacrawler_jsonl_locator(raw_locator, MEDIACRAWLER_XHS_SITE_ID)
    max_items = max(1, min(mediacrawler_env_int_any(200, "MEDIACRAWLER_XHS_MAX_ITEMS", "MEDIACRAWLER_XIAOHONGSHU_MAX_ITEMS"), 1000))
    status: dict[str, Any] = {
        "enabled": mediacrawler_env_flag_any("MEDIACRAWLER_XHS_ENABLED", "MEDIACRAWLER_XIAOHONGSHU_ENABLED"),
        "ok": None,
        "item_count": 0,
        "source_kind": MEDIACRAWLER_XHS_SITE_ID,
        "privacy": "local_jsonl_only_no_cookies",
        "coverage_note": "reads_mediacrawler_xhs_creator_jsonl",
        "jsonl_path_configured": bool(raw_locator or jsonl_path_raw),
        "locator": raw_locator,
        "locator_kind": "homepage_url" if is_url_like(raw_locator) else "jsonl_path",
        "jsonl_file_configured": Path(jsonl_path_raw).name if jsonl_path_raw else None,
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
        jsonl_path = resolve_latest_mediacrawler_jsonl(jsonl_path_raw)
        status["jsonl_file"] = jsonl_path.name
        if jsonl_path.name != status.get("jsonl_file_configured"):
            status["jsonl_file_resolved_from"] = status.get("jsonl_file_configured")
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


def fetch_mediacrawler_xhs_subscriptions(
    subscriptions: list[dict[str, str]],
    now: datetime,
) -> tuple[list[RawItem], dict[str, Any]]:
    if not subscriptions:
        return maybe_fetch_mediacrawler_xhs(now)

    start = time.perf_counter()
    out: list[RawItem] = []
    children: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_items = max(1, min(mediacrawler_env_int_any(200, "MEDIACRAWLER_XHS_MAX_ITEMS", "MEDIACRAWLER_XIAOHONGSHU_MAX_ITEMS"), 1000))
    for subscription in subscriptions:
        raw_locator = str(subscription.get("locator") or "").strip()
        jsonl_path_raw = mediacrawler_jsonl_locator(raw_locator, MEDIACRAWLER_XHS_SITE_ID)
        source_name = str(subscription.get("target") or subscription.get("name") or "").strip()
        child = {
            "name": source_name,
            "locator": raw_locator,
            "locator_kind": "homepage_url" if is_url_like(raw_locator) else "jsonl_path",
            "jsonl_file_configured": Path(jsonl_path_raw).name if jsonl_path_raw else None,
            "item_count": 0,
            "ok": None,
        }
        try:
            jsonl_path = resolve_latest_mediacrawler_jsonl(jsonl_path_raw)
            child["jsonl_file"] = jsonl_path.name
            if jsonl_path.name != child.get("jsonl_file_configured"):
                child["jsonl_file_resolved_from"] = child.get("jsonl_file_configured")
            if not jsonl_path.exists():
                child["ok"] = False
                child["error"] = "mediacrawler_xhs_jsonl_not_found"
                children.append(child)
                continue
            items = parse_mediacrawler_xhs_jsonl(
                jsonl_path.read_text(encoding="utf-8", errors="ignore"),
                now=now,
                source_name=source_name,
                max_items=max_items,
            )
            items = [
                item
                for item in items
                if xiaohongshu_item_matches_subscription(item, locator=raw_locator, source_name=source_name)
            ]
            for item in items:
                key = f"{item.site_id}:{normalize_url(item.url)}:{item.title}"
                if key in seen:
                    continue
                seen.add(key)
                out.append(item)
            child["ok"] = bool(items)
            child["item_count"] = len(items)
            if not items:
                child["error"] = "mediacrawler_xhs_no_items"
        except Exception as exc:
            child["ok"] = False
            child["error"] = str(exc)
        children.append(child)

    return out, {
        "enabled": True,
        "ok": bool(out),
        "item_count": len(out),
        "source_kind": MEDIACRAWLER_XHS_SITE_ID,
        "privacy": "local_jsonl_only_no_cookies",
        "coverage_note": "reads_mediacrawler_xhs_creator_jsonl",
        "jsonl_path_configured": any(child.get("jsonl_file_configured") for child in children),
        "jsonl_file": children[0].get("jsonl_file") if children else None,
        "source_name": ", ".join(child.get("name") or "" for child in children if child.get("name")),
        "max_items": max_items,
        "subscriptions": children,
        "subscription_count": len(children),
        "error": None if out else "mediacrawler_xhs_no_items",
        "duration_ms": int((time.perf_counter() - start) * 1000),
    }


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



