from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from scripts.radar.common import (
    MEDIACRAWLER_DOUYIN_SITE_ID,
    MEDIACRAWLER_DOUYIN_SITE_NAME,
    MEDIACRAWLER_XHS_SITE_ID,
    MEDIACRAWLER_XHS_SITE_NAME,
    RawItem,
    UTC,
    X_API_BASE_DEFAULT,
    X_API_DEFAULT_MAX_RESULTS,
    X_API_DEFAULT_QUERY,
    X_API_MAX_QUERY_CHARS,
    X_API_POST_READ_COST_USD,
    compact_public_snippet,
    env_flag,
    env_flag_default,
    env_int,
    first_non_empty,
    normalize_url,
    parse_date_any,
    parse_iso,
    parse_unix_timestamp,
)

"""Local MediaCrawler JSONL bridge fetchers."""


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


def mediacrawler_local_root() -> Path:
    configured = str(os.environ.get("MEDIACRAWLER_LOCAL_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root.parent / "MediaCrawler-local-test"


def is_url_like(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def default_mediacrawler_jsonl_dir(site_id: str) -> Path:
    folder = "xhs" if site_id == MEDIACRAWLER_XHS_SITE_ID else "douyin"
    return mediacrawler_local_root() / "output" / folder / "jsonl"


def mediacrawler_jsonl_locator(raw_locator: str, site_id: str) -> str:
    locator = str(raw_locator or "").strip()
    if not locator or is_url_like(locator):
        return str(default_mediacrawler_jsonl_dir(site_id))
    return locator


def resolve_latest_mediacrawler_jsonl(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
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


def douyin_sec_uid_from_locator(locator: str) -> str:
    parsed = urlparse(str(locator or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return ""
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part == "user" and index + 1 < len(parts):
            return parts[index + 1].strip()
    return ""


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
            row.get("nickname"),
            row.get("user_nickname"),
            row.get("user_unique_id"),
            row.get("sec_user_id"),
            source_name,
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
        sec_user_id = first_non_empty(row.get("sec_uid"), row.get("sec_user_id"), row.get("user_id"))
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


def douyin_item_matches_subscription(item: RawItem, *, locator: str, source_name: str) -> bool:
    expected_sec_uid = douyin_sec_uid_from_locator(locator)
    if expected_sec_uid:
        return str(item.meta.get("douyin_sec_user_id") or "").strip() == expected_sec_uid
    if source_name:
        return str(item.source or "").strip() == source_name
    return True


def xiaohongshu_user_id_from_locator(locator: str) -> str:
    parsed = urlparse(str(locator or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return ""
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part == "profile" and index + 1 < len(parts):
            return parts[index + 1].strip()
    return ""


def maybe_fetch_mediacrawler_douyin(now: datetime) -> tuple[list[RawItem], dict[str, Any]]:
    raw_locator = str(os.environ.get("MEDIACRAWLER_DOUYIN_JSONL") or "").strip()
    jsonl_path_raw = mediacrawler_jsonl_locator(raw_locator, MEDIACRAWLER_DOUYIN_SITE_ID)
    max_items = max(1, min(env_int("MEDIACRAWLER_DOUYIN_MAX_ITEMS", 200), 1000))
    status: dict[str, Any] = {
        "enabled": env_flag("MEDIACRAWLER_DOUYIN_ENABLED"),
        "ok": None,
        "item_count": 0,
        "source_kind": MEDIACRAWLER_DOUYIN_SITE_ID,
        "privacy": "local_jsonl_only_no_cookies",
        "coverage_note": "reads_mediacrawler_douyin_creator_jsonl",
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
        status["error"] = "missing_mediacrawler_douyin_jsonl"
        return [], status

    start = time.perf_counter()
    try:
        jsonl_path = resolve_latest_mediacrawler_jsonl(jsonl_path_raw)
        status["jsonl_file"] = jsonl_path.name
        if jsonl_path.name != status.get("jsonl_file_configured"):
            status["jsonl_file_resolved_from"] = status.get("jsonl_file_configured")
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




