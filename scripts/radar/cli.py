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

"""Command-line entry point for update_news."""

def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate AI news updates from multiple sources")
    parser.add_argument("--output-dir", default="data", help="Directory for output JSON files")
    parser.add_argument("--window-hours", type=int, default=24, help="24h window size")
    parser.add_argument(
        "--collect-window-hours",
        type=int,
        default=0,
        help="Limit newly accepted raw items to this recent publish window; 0 keeps all fetched items",
    )
    parser.add_argument("--archive-days", type=int, default=21, help="Keep archive for N days")
    parser.add_argument("--translate-max-new", type=int, default=80, help="Max new EN->ZH title translations per run")
    parser.add_argument("--rss-opml", default="", help="Optional OPML file path to include RSS sources")
    parser.add_argument("--rss-max-feeds", type=int, default=0, help="Optional max OPML RSS feeds to fetch (0 means all)")
    parser.add_argument(
        "--source-config",
        default="",
        help="Optional sources.config.json exported from the dashboard; defaults to ./sources.config.json when present",
    )
    parser.add_argument("--bilibili-only", action="store_true", help="Publish only the configured Bilibili dynamic accounts")
    parser.add_argument(
        "--source-scope",
        default=os.environ.get("RADAR_SOURCE_SCOPE") or DEPLOYED_SOURCE_SCOPE_DEFAULT,
        help="Source set to publish: tested_creator_sources (default) or all_sources",
    )
    parser.add_argument("--all-time", action="store_true", help="Publish all retained records instead of the rolling window")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    source_config, source_config_status = load_source_config(args.source_config, output_dir=output_dir)
    if source_config_status.get("enabled") and source_config_status.get("ok") is False:
        print(f"Source config error: {source_config_status.get('error')}", file=sys.stderr)
        return 2
    source_config_runtime = apply_source_config_runtime(source_config)
    configured_source_ids = frozenset(source_config_runtime.get("enabled_site_ids") or [])
    source_config_active = bool(source_config_status.get("ok") and source_config)
    source_scope = (
        SOURCE_SCOPE_BILIBILI_ONLY
        if args.bilibili_only or env_flag("BILIBILI_ONLY_MODE")
        else SOURCE_SCOPE_CONFIGURED if source_config_active
        else normalize_source_scope(args.source_scope)
    )
    active_source_ids = configured_source_ids if source_config_active else source_ids_for_scope(source_scope)
    scoped_to_tested_creators = source_scope == SOURCE_SCOPE_TESTED_CREATORS
    scoped_by_config = source_scope == SOURCE_SCOPE_CONFIGURED
    all_time = bool(args.all_time or env_flag("RADAR_ALL_TIME"))
    collect_window_hours = max(0, int(args.collect_window_hours or 0))
    wewe_rss_enabled = env_flag("WEWE_RSS_ENABLED") and (
        active_source_ids is None or WEWE_RSS_SITE_ID in active_source_ids
    )
    if wewe_rss_enabled and active_source_ids is not None:
        active_source_ids = frozenset(site_id for site_id in active_source_ids if site_id != MAOBIDAO_WECHAT_SITE_ID)

    now = utc_now()
    output_dir.mkdir(parents=True, exist_ok=True)

    archive_path = output_dir / "archive.json"
    latest_path = output_dir / "latest-24h.json"
    latest_all_path = output_dir / "latest-24h-all.json"
    status_path = output_dir / "source-status.json"
    daily_brief_path = output_dir / "daily-brief.json"
    stories_merged_path = output_dir / "stories-merged.json"
    merge_log_path = output_dir / "merge-log.json"
    waytoagi_path = output_dir / "waytoagi-7d.json"
    title_cache_path = output_dir / "title-zh-cache.json"
    email_digest_path = output_dir / AGENTMAIL_DIGEST_FILE
    paid_source_state_path = output_dir / PAID_SOURCE_STATE_FILE

    archive = filter_archive_by_source_ids(load_archive(archive_path), active_source_ids)
    paid_source_state = load_paid_source_state(paid_source_state_path)

    session = create_session()
    if scoped_to_tested_creators:
        raw_items, statuses = [], []
    elif scoped_by_config:
        raw_items, statuses = collect_all(session, now, allowed_site_ids=active_source_ids)
    else:
        raw_items, statuses = collect_all(session, now)
    rss_feed_statuses: list[dict[str, Any]] = []
    github_repo_error = None
    github_repo_start = time.perf_counter()
    github_repo_items: list[RawItem] = []
    github_repo_enabled = active_source_ids is None or GITHUB_REPO_SUBSCRIPTION_SITE_ID in active_source_ids
    if github_repo_enabled:
        github_subscriptions = source_config_subscriptions_for_site(source_config, GITHUB_REPO_SUBSCRIPTION_SITE_ID) if scoped_by_config else []
        if not github_subscriptions:
            github_subscriptions = [
                {
                    "name": "AlkaidLab/foundation-sunshine",
                    "target": "AlkaidLab/foundation-sunshine",
                    "locator": GITHUB_REPO_SUBSCRIPTION_API_URL,
                }
            ]
        github_status_children: list[dict[str, Any]] = []
        try:
            for subscription in github_subscriptions:
                api_url = github_release_api_url_from_config(subscription.get("locator", ""))
                repo_label = github_release_repo_label_from_config(
                    subscription.get("locator", ""),
                    subscription.get("target") or subscription.get("name") or "GitHub Repo",
                )
                display_name = str(subscription.get("target") or subscription.get("name") or repo_label).strip()
                items = fetch_github_repo_subscription(
                    session,
                    now,
                    api_url=api_url,
                    repo_label=repo_label,
                    site_name=subscription.get("name") or GITHUB_REPO_SUBSCRIPTION_SITE_NAME,
                    display_name=display_name,
                )
                github_repo_items.extend(items)
                github_status_children.append(
                    {
                        "repo": repo_label,
                        "api_url": api_url,
                        "ok": True,
                        "item_count": len(items),
                    }
                )
            raw_items.extend(github_repo_items)
        except Exception as exc:
            github_repo_error = str(exc)
        statuses.append(
            {
                "site_id": GITHUB_REPO_SUBSCRIPTION_SITE_ID,
                "site_name": GITHUB_REPO_SUBSCRIPTION_SITE_NAME,
                "ok": github_repo_error is None,
                "item_count": len(github_repo_items),
                "duration_ms": int((time.perf_counter() - github_repo_start) * 1000),
                "error": github_repo_error,
                "source_kind": "github_release_subscription",
                "repo": ", ".join(item.get("repo", "") for item in github_status_children if item.get("repo")) or "AlkaidLab/foundation-sunshine",
                "repos": github_status_children,
                "max_items": GITHUB_REPO_SUBSCRIPTION_MAX_ITEMS,
            }
        )
    if wewe_rss_enabled:
        wewe_rss_items, wewe_rss_status = fetch_wewe_rss_subscription(session, now)
        raw_items.extend(wewe_rss_items)
        statuses.append(
            {
                "site_id": WEWE_RSS_SITE_ID,
                "site_name": WEWE_RSS_SITE_NAME,
                "ok": bool(wewe_rss_status.get("ok")),
                "item_count": int(wewe_rss_status.get("item_count") or 0),
                "duration_ms": int(wewe_rss_status.get("duration_ms") or 0),
                "error": wewe_rss_status.get("error"),
                "source_kind": wewe_rss_status.get("source_kind"),
                "base_url": wewe_rss_status.get("base_url"),
                "max_items_per_feed": wewe_rss_status.get("max_items_per_feed"),
                "feeds": wewe_rss_status.get("feeds"),
                "coverage_note": wewe_rss_status.get("coverage_note"),
                "privacy": wewe_rss_status.get("privacy"),
            }
        )
    elif active_source_ids is None or MAOBIDAO_WECHAT_SITE_ID in active_source_ids:
        maobidao_error = None
        maobidao_start = time.perf_counter()
        maobidao_items: list[RawItem] = []
        try:
            maobidao_items = fetch_maobidao_wechat_subscription(session, now)
            raw_items.extend(maobidao_items)
        except Exception as exc:
            maobidao_error = str(exc)
        statuses.append(
            {
                "site_id": MAOBIDAO_WECHAT_SITE_ID,
                "site_name": MAOBIDAO_WECHAT_SITE_NAME,
                "ok": maobidao_error is None,
                "item_count": len(maobidao_items),
                "duration_ms": int((time.perf_counter() - maobidao_start) * 1000),
                "error": maobidao_error,
                "source_kind": "wechat_public_account_backup",
                "source_name": "猫笔刀公众号",
                "source_origin": MAOBIDAO_WECHAT_HOME_URL,
                "max_items": MAOBIDAO_WECHAT_MAX_ITEMS,
                "coverage_note": "reads_public_discourse_backup_json_not_wechat_login",
            }
        )
    bilibili_dynamic_status = bilibili_dynamic_status_base()
    if active_source_ids is None or "bilibili_dynamic" in active_source_ids:
        bilibili_dynamic_items, bilibili_dynamic_status = maybe_fetch_bilibili_dynamic(session, now)
        if bilibili_dynamic_status.get("enabled"):
            raw_items.extend(bilibili_dynamic_items)
            statuses.append(
                {
                    "site_id": "bilibili_dynamic",
                    "site_name": "Bilibili Dynamic",
                    "ok": bool(bilibili_dynamic_status.get("ok")) if bilibili_dynamic_status.get("ok") is not None else True,
                    "item_count": int(bilibili_dynamic_status.get("item_count") or 0),
                    "duration_ms": int(bilibili_dynamic_status.get("duration_ms") or 0),
                    "error": bilibili_dynamic_status.get("error"),
                    "uid": bilibili_dynamic_status.get("uid"),
                    "uids": bilibili_dynamic_status.get("uids"),
                    "uid_count": bilibili_dynamic_status.get("uid_count"),
                    "source_name": bilibili_dynamic_status.get("source_name"),
                    "privacy": bilibili_dynamic_status.get("privacy"),
                    "coverage_note": bilibili_dynamic_status.get("coverage_note"),
                    "cookie_present": bool(bilibili_dynamic_status.get("cookie_present")),
                    "fetch_mode": bilibili_dynamic_status.get("fetch_mode"),
                    "fallback_reason": bilibili_dynamic_status.get("fallback_reason"),
                    "partial_failure_count": bilibili_dynamic_status.get("partial_failure_count"),
                    "max_items": bilibili_dynamic_status.get("max_items"),
                    "max_items_per_account": bilibili_dynamic_status.get("max_items_per_account"),
                    "max_pages": bilibili_dynamic_status.get("max_pages"),
                    "accounts": bilibili_dynamic_status.get("accounts"),
                }
            )
    mediacrawler_douyin_status = {
        "enabled": False,
        "ok": None,
        "item_count": 0,
        "disabled_reason": "disabled_by_source_config" if scoped_by_config else "disabled_by_source_scope",
    }
    if active_source_ids is None or MEDIACRAWLER_DOUYIN_SITE_ID in active_source_ids:
        douyin_subscriptions = source_config_subscriptions_for_site(source_config, MEDIACRAWLER_DOUYIN_SITE_ID) if scoped_by_config else []
        mediacrawler_douyin_items, mediacrawler_douyin_status = fetch_mediacrawler_douyin_subscriptions(douyin_subscriptions, now)
        if mediacrawler_douyin_status.get("enabled"):
            raw_items.extend(mediacrawler_douyin_items)
            statuses.append(
                {
                    "site_id": MEDIACRAWLER_DOUYIN_SITE_ID,
                    "site_name": MEDIACRAWLER_DOUYIN_SITE_NAME,
                    "ok": bool(mediacrawler_douyin_status.get("ok")) if mediacrawler_douyin_status.get("ok") is not None else True,
                    "item_count": int(mediacrawler_douyin_status.get("item_count") or 0),
                    "duration_ms": int(mediacrawler_douyin_status.get("duration_ms") or 0),
                    "error": mediacrawler_douyin_status.get("error"),
                    "source_name": mediacrawler_douyin_status.get("source_name"),
                    "privacy": mediacrawler_douyin_status.get("privacy"),
                    "coverage_note": mediacrawler_douyin_status.get("coverage_note"),
                    "source_kind": mediacrawler_douyin_status.get("source_kind"),
                    "jsonl_path_configured": bool(mediacrawler_douyin_status.get("jsonl_path_configured")),
                    "jsonl_file": mediacrawler_douyin_status.get("jsonl_file"),
                    "max_items": mediacrawler_douyin_status.get("max_items"),
                    "subscriptions": mediacrawler_douyin_status.get("subscriptions"),
                    "subscription_count": mediacrawler_douyin_status.get("subscription_count"),
                }
            )
    mediacrawler_xhs_status = {
        "enabled": False,
        "ok": None,
        "item_count": 0,
        "disabled_reason": "disabled_by_source_config" if scoped_by_config else "disabled_by_source_scope",
    }
    if active_source_ids is None or MEDIACRAWLER_XHS_SITE_ID in active_source_ids:
        xhs_subscriptions = source_config_subscriptions_for_site(source_config, MEDIACRAWLER_XHS_SITE_ID) if scoped_by_config else []
        mediacrawler_xhs_items, mediacrawler_xhs_status = fetch_mediacrawler_xhs_subscriptions(xhs_subscriptions, now)
        if mediacrawler_xhs_status.get("enabled"):
            raw_items.extend(mediacrawler_xhs_items)
            statuses.append(
                {
                    "site_id": MEDIACRAWLER_XHS_SITE_ID,
                    "site_name": MEDIACRAWLER_XHS_SITE_NAME,
                    "ok": bool(mediacrawler_xhs_status.get("ok")) if mediacrawler_xhs_status.get("ok") is not None else True,
                    "item_count": int(mediacrawler_xhs_status.get("item_count") or 0),
                    "duration_ms": int(mediacrawler_xhs_status.get("duration_ms") or 0),
                    "error": mediacrawler_xhs_status.get("error"),
                    "source_name": mediacrawler_xhs_status.get("source_name"),
                    "privacy": mediacrawler_xhs_status.get("privacy"),
                    "coverage_note": mediacrawler_xhs_status.get("coverage_note"),
                    "source_kind": mediacrawler_xhs_status.get("source_kind"),
                    "jsonl_path_configured": bool(mediacrawler_xhs_status.get("jsonl_path_configured")),
                    "jsonl_file": mediacrawler_xhs_status.get("jsonl_file"),
                    "max_items": mediacrawler_xhs_status.get("max_items"),
                    "subscriptions": mediacrawler_xhs_status.get("subscriptions"),
                    "subscription_count": mediacrawler_xhs_status.get("subscription_count"),
                }
            )
    advanced_source_ids = frozenset({
        "agentmail",
        "xapi",
        "socialdata_x",
        "tikhub_douyin",
        "tikhub_xiaohongshu",
        "waytoagi",
    })
    advanced_sources_enabled = active_source_ids is None or bool(active_source_ids.intersection(advanced_source_ids))
    if scoped_to_tested_creators or not advanced_sources_enabled:
        email_digest_payload = None
        disabled_reason = "disabled_by_source_config" if scoped_by_config else "disabled_by_source_scope"
        agentmail_status = {
            "enabled": False,
            "ok": None,
            "item_count": 0,
            "privacy": "metadata_only_no_body",
            "published_by_default": False,
            "disabled_reason": disabled_reason,
        }
        x_api_status = {
            "enabled": False,
            "ok": None,
            "item_count": 0,
            "disabled_reason": disabled_reason,
        }
        socialdata_status = {
            "enabled": False,
            "ok": None,
            "item_count": 0,
            "disabled_reason": disabled_reason,
        }
        tikhub_status = {
            "enabled": False,
            "ok": None,
            "item_count": 0,
            "disabled_reason": disabled_reason,
        }
        waytoagi_payload = {
            "generated_at": iso(now),
            "timezone": "Asia/Shanghai",
            "root_url": WAYTOAGI_DEFAULT,
            "history_url": None,
            "window_days": 7,
            "count_7d": 0,
            "updates_7d": [],
            "skipped": True,
            "skip_reason": disabled_reason,
        }
    else:
        if active_source_ids is None or "agentmail" in active_source_ids:
            email_digest_payload, agentmail_status = maybe_fetch_agentmail_digest(
                session,
                generated_at=iso(now),
                after=iso(now - timedelta(hours=args.window_hours)),
                window_hours=args.window_hours,
            )
        else:
            email_digest_payload = None
            agentmail_status = {
                "enabled": False,
                "ok": None,
                "item_count": 0,
                "privacy": "metadata_only_no_body",
                "published_by_default": False,
                "disabled_reason": "disabled_by_source_config",
            }
        if active_source_ids is None or "xapi" in active_source_ids:
            x_api_items, x_api_status = maybe_fetch_x_api_updates(session, now)
        else:
            x_api_items, x_api_status = [], {"enabled": False, "ok": None, "item_count": 0, "disabled_reason": "disabled_by_source_config"}
        if x_api_status.get("enabled"):
            raw_items.extend(x_api_items)
            statuses.append(
                {
                    "site_id": "xapi",
                    "site_name": "X API",
                    "ok": bool(x_api_status.get("ok")) if x_api_status.get("ok") is not None else True,
                    "item_count": int(x_api_status.get("item_count") or 0),
                    "duration_ms": 0,
                    "error": x_api_status.get("error"),
                    "skipped": bool(x_api_status.get("skipped")),
                    "skip_reason": x_api_status.get("skip_reason"),
                }
            )
        if active_source_ids is None or "socialdata_x" in active_source_ids:
            socialdata_items, socialdata_status = maybe_fetch_socialdata_updates(session, now, paid_source_state)
            update_paid_source_state(paid_source_state, "socialdata", socialdata_status, now)
            sync_paid_source_status_timestamps(socialdata_status, paid_source_state, "socialdata")
        else:
            socialdata_items, socialdata_status = [], {"enabled": False, "ok": None, "item_count": 0, "disabled_reason": "disabled_by_source_config"}
        if socialdata_status.get("enabled"):
            raw_items.extend(socialdata_items)
            statuses.append(
                {
                    "site_id": "socialdata_x",
                    "site_name": "SocialData X",
                    "ok": bool(socialdata_status.get("ok")) if socialdata_status.get("ok") is not None else True,
                    "item_count": int(socialdata_status.get("item_count") or 0),
                    "duration_ms": 0,
                    "error": socialdata_status.get("error"),
                    "skipped": bool(socialdata_status.get("skipped")),
                    "skip_reason": socialdata_status.get("skip_reason"),
                }
            )
        if active_source_ids is None or active_source_ids.intersection({"tikhub_douyin", "tikhub_xiaohongshu"}):
            tikhub_items, tikhub_status = maybe_fetch_tikhub_updates(session, now, paid_source_state)
            update_paid_source_state(paid_source_state, "tikhub", tikhub_status, now)
            sync_paid_source_status_timestamps(tikhub_status, paid_source_state, "tikhub")
        else:
            tikhub_items, tikhub_status = [], {"enabled": False, "ok": None, "item_count": 0, "disabled_reason": "disabled_by_source_config"}
        if tikhub_status.get("enabled"):
            raw_items.extend(tikhub_items)
            tikhub_counts: dict[str, int] = {}
            for item in tikhub_items:
                tikhub_counts[item.site_id] = tikhub_counts.get(item.site_id, 0) + 1
            for site_id, site_name in (
                ("tikhub_douyin", "TikHub Douyin"),
                ("tikhub_xiaohongshu", "TikHub Xiaohongshu"),
            ):
                if site_id.split("_", 1)[1] not in set(tikhub_status.get("platforms") or []):
                    continue
                statuses.append(
                    {
                        "site_id": site_id,
                        "site_name": site_name,
                        "ok": bool(tikhub_status.get("ok")) if tikhub_status.get("ok") is not None else True,
                        "item_count": tikhub_counts.get(site_id, 0),
                        "duration_ms": 0,
                        "error": tikhub_status.get("error"),
                        "skipped": bool(tikhub_status.get("skipped")),
                        "skip_reason": tikhub_status.get("skip_reason"),
                    }
                )

        waytoagi_started = time.perf_counter()
        if active_source_ids is not None and "waytoagi" not in active_source_ids:
            waytoagi_payload = {
                "generated_at": iso(now),
                "timezone": "Asia/Shanghai",
                "root_url": WAYTOAGI_DEFAULT,
                "history_url": None,
                "window_days": 7,
                "count_7d": 0,
                "updates_7d": [],
                "skipped": True,
                "skip_reason": "disabled_by_source_config",
            }
        else:
            try:
                waytoagi_payload = fetch_waytoagi_recent_7d(session, now, WAYTOAGI_DEFAULT)
                waytoagi_items = waytoagi_updates_to_raw_items(waytoagi_payload, now)
                raw_items.extend(waytoagi_items)
                statuses.append(
                    {
                        "site_id": "waytoagi",
                        "site_name": "WaytoAGI",
                        "ok": True,
                        "item_count": len(waytoagi_items),
                        "duration_ms": int((time.perf_counter() - waytoagi_started) * 1000),
                        "error": None,
                    }
                )
            except Exception as exc:
                waytoagi_payload = {
                    "generated_at": iso(now),
                    "timezone": "Asia/Shanghai",
                    "root_url": WAYTOAGI_DEFAULT,
                    "history_url": None,
                    "window_days": 7,
                    "count_7d": 0,
                    "updates_7d": [],
                    "warning": "WaytoAGI 近7日更新抓取失败",
                    "has_error": True,
                    "error": str(exc),
                }
                statuses.append(
                    {
                        "site_id": "waytoagi",
                        "site_name": "WaytoAGI",
                        "ok": False,
                        "item_count": 0,
                        "duration_ms": int((time.perf_counter() - waytoagi_started) * 1000),
                        "error": str(exc),
                    }
                )

    rss_opml_path = str(source_config_runtime.get("rss_opml") or args.rss_opml or "").strip()
    rss_opml_enabled = bool(
        rss_opml_path
        and not scoped_to_tested_creators
        and (active_source_ids is None or "opmlrss" in active_source_ids)
    )
    if rss_opml_enabled:
        opml_path = Path(rss_opml_path).expanduser()
        if opml_path.exists():
            rss_items, rss_summary_status, rss_feed_statuses = fetch_opml_rss(
                now,
                opml_path,
                max_feeds=max(0, int(args.rss_max_feeds)),
            )
            raw_items.extend(rss_items)
            statuses.append(rss_summary_status)
        else:
            statuses.append(
                {
                    "site_id": "opmlrss",
                    "site_name": "OPML RSS",
                    "ok": False,
                    "item_count": 0,
                    "duration_ms": 0,
                    "error": f"OPML not found: {opml_path}",
                    "feed_count": 0,
                    "ok_feed_count": 0,
                    "failed_feed_count": 0,
                }
            )

    if active_source_ids is not None:
        raw_items = [item for item in raw_items if item.site_id in active_source_ids]
        statuses = [status for status in statuses if str(status.get("site_id") or "") in active_source_ids]
    raw_items_before_collect_window = len(raw_items)
    raw_item_counts_by_site = Counter(item.site_id for item in raw_items)
    raw_items, skipped_collect_window_items = filter_raw_items_by_collect_window(
        raw_items,
        now,
        collect_window_hours,
        existing_source_counts=archive_source_counts(archive),
    )
    window_item_counts_by_site = Counter(item.site_id for item in raw_items)
    for status in statuses:
        site_id = str(status.get("site_id") or "")
        if not site_id:
            continue
        raw_count = int(raw_item_counts_by_site.get(site_id, status.get("item_count") or 0))
        status["raw_item_count"] = raw_count
        status["window_item_count"] = int(window_item_counts_by_site.get(site_id, 0))
        status["collection_window_hours"] = collect_window_hours

    seen_this_run: set[str] = set()

    for raw in raw_items:
        title = raw.title.strip()
        url = normalize_url(raw.url)
        if not title or not url:
            continue
        if not url.startswith("http"):
            continue

        item_id = make_item_id(raw.site_id, raw.source, title, url)
        seen_this_run.add(item_id)

        existing = archive.get(item_id)
        if existing is None:
            archive[item_id] = {
                "id": item_id,
                "site_id": raw.site_id,
                "site_name": raw.site_name,
                "source": raw.source,
                "title": title,
                "url": url,
                "published_at": iso(raw.published_at),
                "first_seen_at": iso(now),
                "last_seen_at": iso(now),
            }
            apply_public_raw_meta(archive[item_id], raw)
        else:
            existing["site_id"] = raw.site_id
            existing["site_name"] = raw.site_name
            existing["source"] = raw.source
            existing["title"] = title
            existing["url"] = url
            if raw.published_at:
                # OPML RSS may fix previously wrong publish times; allow overwrite.
                if raw.site_id == "opmlrss" or not existing.get("published_at"):
                    existing["published_at"] = iso(raw.published_at)
            existing["last_seen_at"] = iso(now)
            apply_public_raw_meta(existing, raw)

    backfill_bilibili_archive_publish_times(session, archive)

    # Prune old archive unless the generated view intentionally needs all retained history.
    if not all_time:
        keep_after = now - timedelta(days=args.archive_days)
        pruned: dict[str, dict[str, Any]] = {}
        for item_id, record in archive.items():
            ts = (
                parse_iso(record.get("last_seen_at"))
                or parse_iso(record.get("published_at"))
                or parse_iso(record.get("first_seen_at"))
                or now
            )
            if ts >= keep_after:
                pruned[item_id] = record
        archive = pruned

    window_start = datetime.min.replace(tzinfo=UTC) if all_time else now - timedelta(hours=args.window_hours)
    latest_items_all: list[dict[str, Any]] = []
    for record in archive.values():
        if active_source_ids is not None and str(record.get("site_id") or "") not in active_source_ids:
            continue
        if not all_time and not parse_iso(record.get("published_at")):
            continue
        ts = event_time(record)
        if not ts:
            continue
        if ts >= window_start:
            normalized = dict(record)
            normalized["title"] = maybe_fix_mojibake(str(normalized.get("title") or ""))
            normalized["source"] = maybe_fix_mojibake(normalize_source_for_display(
                str(normalized.get("site_id") or ""),
                str(normalized.get("source") or ""),
                str(normalized.get("url") or ""),
            ))
            if str(normalized.get("site_id") or "") == "aihubtoday" and is_hubtoday_placeholder_title(
                str(normalized.get("title") or "")
            ):
                continue
            normalized = add_ai_relevance_fields(normalized)
            normalized = add_source_tier_fields(normalized)
            latest_items_all.append(normalized)

    latest_items_all = normalize_aihubtoday_records(latest_items_all)

    latest_items_all.sort(key=lambda x: event_time(x) or datetime.min.replace(tzinfo=UTC), reverse=True)
    latest_items = [record for record in latest_items_all if record.get("ai_is_related", is_ai_related_record(record))]
    title_cache = load_title_zh_cache(title_cache_path)
    latest_items, latest_items_all, title_cache = add_bilingual_fields(
        latest_items,
        latest_items_all,
        session,
        title_cache,
        max_new_translations=max(0, args.translate_max_new),
    )
    creator_window_hours = None if all_time else args.window_hours
    creator_window_days = None if all_time else max(1, (args.window_hours + 23) // 24)
    creator_items_ai = build_creator_hot_items(
        archive,
        now,
        ai_only=True,
        window_days=creator_window_days,
        window_hours=creator_window_hours,
    )
    creator_items_all = build_creator_hot_items(
        archive,
        now,
        ai_only=False,
        window_days=creator_window_days,
        window_hours=creator_window_hours,
    )
    creator_items_ai, creator_items_all, title_cache = add_bilingual_fields(
        creator_items_ai,
        creator_items_all,
        session,
        title_cache,
        max_new_translations=0,
    )
    latest_items_ai_dedup = suppress_near_duplicate_items(dedupe_items_by_title_url(latest_items, random_pick=False))
    latest_items_all_dedup = dedupe_items_by_title_url(latest_items_all, random_pick=True)
    stories, merge_events = merge_story_items(latest_items_ai_dedup, now=now, window_hours=args.window_hours)
    generated_at = iso(now)
    daily_brief_payload = build_daily_brief_payload(stories, generated_at=generated_at, window_hours=args.window_hours)
    stories_merged_payload = build_stories_payload(stories, generated_at=generated_at, window_hours=args.window_hours)
    merge_log_payload = build_merge_log_payload(merge_events, generated_at=generated_at)

    # site stats
    site_stat: dict[str, dict[str, Any]] = {}
    raw_count_by_site: dict[str, int] = {}
    for record in latest_items_all:
        sid = record["site_id"]
        raw_count_by_site[sid] = raw_count_by_site.get(sid, 0) + 1

    site_name_by_id: dict[str, str] = {}
    for record in latest_items_all:
        site_name_by_id[record["site_id"]] = record["site_name"]
    for s in statuses:
        sid = s["site_id"]
        if sid not in site_name_by_id:
            site_name_by_id[sid] = s.get("site_name") or sid

    for record in latest_items_ai_dedup:
        sid = record["site_id"]
        if sid not in site_stat:
            site_stat[sid] = {
                "site_id": sid,
                "site_name": record["site_name"],
                "count": 0,
                "raw_count": raw_count_by_site.get(sid, 0),
            }
        site_stat[sid]["count"] += 1

    for sid, site_name in site_name_by_id.items():
        if sid in site_stat:
            continue
        site_stat[sid] = {
            "site_id": sid,
            "site_name": site_name,
            "count": 0,
            "raw_count": raw_count_by_site.get(sid, 0),
        }

    latest_payload = {
        "generated_at": generated_at,
        "window_hours": args.window_hours,
        "time_scope": "all_time" if all_time else "rolling_window",
        "source_scope": source_scope,
        "collection_window_hours": collect_window_hours,
        "total_items": len(latest_items_ai_dedup),
        "total_items_ai_raw": len(latest_items),
        "total_items_raw": len(latest_items_all),
        "total_items_all_mode": len(latest_items_all_dedup),
        "topic_filter": "ai_relevance_scoring_v0_4",
        "ai_relevance_threshold": 0.65,
        "archive_total": len(archive),
        "site_count": len(site_stat),
        "source_count": len({f"{i['site_id']}::{i['source']}" for i in latest_items_ai_dedup}),
        "site_stats": sorted(site_stat.values(), key=lambda x: x["count"], reverse=True),
        "creator_window_days": 0 if creator_window_days is None else creator_window_days,
        "creator_window_hours": 0 if creator_window_hours is None else creator_window_hours,
        "creator_time_scope": "all_time" if creator_window_days is None else "rolling_window",
        "creator_ranking": "engagement_85_fresh_24h_bonus_15_v1",
        "creator_items_ai": creator_items_ai,
        "creator_items_all": creator_items_all,
        "items": latest_items_ai_dedup,
        "items_ai": latest_items_ai_dedup,
        "items_all_raw": latest_items_all,
        "items_all": latest_items_all_dedup,
    }

    archive_payload = {
        "generated_at": generated_at,
        "total_items": len(archive),
        "items": sorted(
            archive.values(),
            key=lambda x: parse_iso(x.get("last_seen_at")) or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        ),
    }

    empty_advanced_sources = [
        {
            "site_id": s["site_id"],
            "site_name": s.get("site_name") or s["site_id"],
            "reason": "connected_no_matching_results",
        }
        for s in statuses
        if s.get("ok")
        and int(s.get("item_count") or 0) == 0
        and str(s.get("site_id") or "") in {
            "xapi",
            "socialdata_x",
            "tikhub_douyin",
            "tikhub_xiaohongshu",
            MEDIACRAWLER_DOUYIN_SITE_ID,
            MEDIACRAWLER_XHS_SITE_ID,
        }
        and not s.get("skipped")
    ]
    empty_advanced_site_ids = {item["site_id"] for item in empty_advanced_sources}

    status_payload = {
        "generated_at": generated_at,
        "sites": statuses,
        "time_scope": "all_time" if all_time else "rolling_window",
        "source_scope": source_scope,
        "collection_window_hours": collect_window_hours,
        "successful_sites": sum(1 for s in statuses if s["ok"]),
        "failed_sites": [s["site_id"] for s in statuses if not s["ok"]],
        "zero_item_sites": [
            s["site_id"]
            for s in statuses
            if s.get("ok")
            and int(s.get("item_count") or 0) == 0
            and not s.get("skipped")
            and str(s.get("site_id") or "") not in empty_advanced_site_ids
        ],
        "empty_advanced_sources": empty_advanced_sources,
        "fetched_raw_items": len(raw_items),
        "raw_items_before_collection_window": raw_items_before_collect_window,
        "skipped_collection_window_items": skipped_collect_window_items,
        "items_before_topic_filter": len(latest_items_all),
        "items_in_24h": len(latest_items_ai_dedup),
        "rss_opml": {
            "enabled": rss_opml_enabled,
            "path": "configured" if rss_opml_enabled else None,
            "disabled_reason": "disabled_by_source_scope" if rss_opml_path and not rss_opml_enabled else None,
            "feed_total": len(rss_feed_statuses),
            "effective_feed_total": sum(1 for s in rss_feed_statuses if not s.get("skipped")),
            "ok_feeds": sum(1 for s in rss_feed_statuses if s["ok"] and not s.get("skipped")),
            "failed_feeds": [s.get("effective_feed_url") or s["feed_url"] for s in rss_feed_statuses if not s["ok"]],
            "zero_item_feeds": [
                s.get("effective_feed_url") or s["feed_url"]
                for s in rss_feed_statuses
                if s["ok"] and not s.get("skipped") and int(s.get("item_count") or 0) == 0
            ],
            "skipped_feeds": [
                {"feed_url": s["feed_url"], "reason": s.get("skip_reason")}
                for s in rss_feed_statuses
                if s.get("skipped")
            ],
            "replaced_feeds": [
                {"from": s["feed_url"], "to": s.get("effective_feed_url")}
                for s in rss_feed_statuses
                if s.get("replaced") and s.get("effective_feed_url")
            ],
            "feeds": rss_feed_statuses,
        },
        "agentmail": agentmail_status,
        "x_api": x_api_status,
        "socialdata": socialdata_status,
        "tikhub": tikhub_status,
        "mediacrawler_douyin": mediacrawler_douyin_status,
        "mediacrawler_xhs": mediacrawler_xhs_status,
        "source_config": {
            **source_config_status,
            **source_config_runtime,
            "active": source_config_active,
        },
    }

    latest_payload, latest_all_payload = build_latest_payloads(latest_payload)

    latest_path.write_text(json.dumps(sanitize_public_payload(latest_payload), ensure_ascii=False, indent=2), encoding="utf-8")
    latest_all_path.write_text(json.dumps(sanitize_public_payload(latest_all_payload), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    daily_brief_path.write_text(
        json.dumps(sanitize_public_payload(daily_brief_payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    stories_merged_path.write_text(
        json.dumps(sanitize_public_payload(stories_merged_payload), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    merge_log_path.write_text(
        json.dumps(sanitize_public_payload(merge_log_payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    archive_path.write_text(
        json.dumps(sanitize_public_payload(archive_payload), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    status_path.write_text(json.dumps(sanitize_public_payload(status_payload), ensure_ascii=False, indent=2), encoding="utf-8")
    paid_source_state_path.write_text(
        json.dumps(sanitize_public_payload(paid_source_state), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if email_digest_payload is not None:
        email_digest_path.write_text(
            json.dumps(sanitize_public_payload(email_digest_payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    waytoagi_path.write_text(json.dumps(sanitize_public_payload(waytoagi_payload), ensure_ascii=False, indent=2), encoding="utf-8")
    title_cache_path.write_text(json.dumps(sanitize_public_payload(title_cache), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote: {latest_path} ({len(latest_items)} items)")
    print(f"Wrote: {latest_all_path} ({len(latest_items_all_dedup)} all-mode items)")
    print(f"Wrote: {daily_brief_path} ({daily_brief_payload.get('total_items', 0)} brief items)")
    print(f"Wrote: {stories_merged_path} ({stories_merged_payload.get('total_stories', 0)} stories)")
    print(f"Wrote: {merge_log_path} ({len(merge_events)} merge events)")
    print(f"Wrote: {archive_path} ({len(archive)} items)")
    print(f"Wrote: {status_path}")
    print(f"Wrote: {paid_source_state_path}")
    if email_digest_payload is not None:
        print(f"Wrote: {email_digest_path} ({email_digest_payload.get('total_messages', 0)} email items)")
    print(f"Wrote: {waytoagi_path} ({waytoagi_payload.get('count_7d', 0)} items)")
    print(f"Wrote: {title_cache_path} ({len(title_cache)} entries)")

    return 0


