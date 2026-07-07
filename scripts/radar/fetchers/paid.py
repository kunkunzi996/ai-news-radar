from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any

import requests

from scripts.radar.common import (
    RawItem,
    SOCIALDATA_API_BASE_DEFAULT,
    SOCIALDATA_DEFAULT_MAX_RESULTS,
    SOCIALDATA_DEFAULT_QUERY,
    SOCIALDATA_LIST_ALLOWED_TYPES,
    SOCIALDATA_LIST_DEFAULT_EXCLUDE,
    SOCIALDATA_LIST_DEFAULT_MAX_RESULTS,
    SOCIALDATA_LIST_ID_DEFAULT,
    SOCIALDATA_LIST_MAX_PAGES,
    SOCIALDATA_MAX_QUERY_CHARS,
    SOCIALDATA_RECENCY_DAYS,
    SOCIALDATA_TWEET_READ_COST_USD,
    TIKHUB_API_BASE_DEFAULT,
    TIKHUB_DEFAULT_MAX_RESULTS,
    TIKHUB_DEFAULT_PLATFORMS,
    TIKHUB_DEFAULT_QUERY,
    TIKHUB_DOUYIN_PUBLISH_TIME,
    TIKHUB_DOUYIN_SORT_TYPE,
    TIKHUB_MAX_QUERY_CHARS,
    TIKHUB_RECENCY_DAYS,
    TIKHUB_RESPONSE_SCAN_LIMIT,
    TIKHUB_XHS_NOTE_TYPE,
    TIKHUB_XHS_SORT,
    TIKHUB_XHS_TIME_FILTER,
    UTC,
    compact_public_snippet,
    creator_metric_count,
    env_flag_default,
    env_int,
    first_non_empty,
    normalize_url,
    parse_date_any,
    parse_iso,
    parse_unix_timestamp,
)
from scripts.radar.config_runtime import (
    paid_source_interval_hours,
    paid_source_run_gate,
    paid_source_state_entry,
)

"""Paid source fetchers for SocialData and TikHub."""

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


