from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from scripts.radar.common import (
    DEPLOYED_SOURCE_SCOPE_DEFAULT,
    ENUMERABLE_SUBSCRIPTION_SITE_IDS,
    MEDIACRAWLER_DOUYIN_SITE_ID,
    MEDIACRAWLER_XHS_SITE_ID,
    PAID_SOURCE_DEFAULT_INTERVAL_HOURS,
    PAID_SOURCE_DEFAULT_INTERVAL_HOURS_BY_PREFIX,
    PAID_SOURCE_MAX_INTERVAL_HOURS,
    SOURCE_CONFIG_DEFAULT_FILENAMES,
    SOURCE_CONFIG_ID_SITE_IDS,
    SOURCE_CONFIG_TYPE_SITE_IDS,
    SOURCE_SCOPE_ALL,
    SOURCE_SCOPE_BILIBILI_ONLY,
    SOURCE_SCOPE_TESTED_CREATORS,
    TESTED_CREATOR_SOURCE_IDS,
    UTC,
    WE_MP_RSS_JSONL_SITE_ID,
    WE_MP_RSS_SITE_ID,
    WEWE_RSS_SITE_ID,
    env_flag,
    env_int,
    iso,
    parse_iso,
)
from scripts.radar.fetchers.mediacrawler import douyin_sec_uid_from_locator

"""Source configuration and paid-source runtime state."""

def normalize_source_scope(raw_scope: str | None) -> str:
    raw = str(raw_scope or "").strip().lower().replace("-", "_")
    if raw in {"", "tested", "tested_creators", "tested_creator_sources", "creator_sources", "social_sources"}:
        return SOURCE_SCOPE_TESTED_CREATORS
    if raw in {"all", "all_sources", "legacy_all_sources"}:
        return SOURCE_SCOPE_ALL
    if raw in {"bilibili", "bilibili_only"}:
        return SOURCE_SCOPE_BILIBILI_ONLY
    return DEPLOYED_SOURCE_SCOPE_DEFAULT


def source_ids_for_scope(source_scope: str) -> frozenset[str] | None:
    if source_scope == SOURCE_SCOPE_BILIBILI_ONLY:
        return frozenset({"bilibili_dynamic"})
    if source_scope == SOURCE_SCOPE_TESTED_CREATORS:
        return TESTED_CREATOR_SOURCE_IDS
    return None


def source_config_candidate_paths(raw_path: str | None, output_dir: Path | None = None) -> list[Path]:
    if raw_path:
        return [Path(raw_path).expanduser()]
    env_path = str(os.environ.get("RADAR_SOURCE_CONFIG") or "").strip()
    if env_path:
        return [Path(env_path).expanduser()]
    candidates = [Path(name) for name in SOURCE_CONFIG_DEFAULT_FILENAMES]
    if output_dir is not None:
        candidates.append(output_dir / "sources.config.json")
    return candidates


def load_source_config(raw_path: str | None, output_dir: Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    candidates = source_config_candidate_paths(raw_path, output_dir=output_dir)
    explicit = bool(raw_path or os.environ.get("RADAR_SOURCE_CONFIG"))
    status: dict[str, Any] = {
        "enabled": False,
        "ok": None,
        "path": None,
        "candidate_paths": [str(path) for path in candidates],
        "error": None,
    }
    for path in candidates:
        if not path.exists():
            continue
        status["enabled"] = True
        status["path"] = str(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("source config root must be a JSON object")
            sources = payload.get("sources")
            if not isinstance(sources, list):
                raise ValueError("source config must contain a sources array")
            status["ok"] = True
            status["source_count"] = len(sources)
            return payload, status
        except Exception as exc:
            status["ok"] = False
            status["error"] = str(exc)
            return None, status
    if explicit:
        status["enabled"] = True
        status["ok"] = False
        status["error"] = "source_config_not_found"
    return None, status


def source_config_record_site_ids(record: dict[str, Any]) -> tuple[str, ...]:
    raw_id = str(record.get("id") or "").strip()
    raw_type = str(record.get("type") or "").strip()
    if raw_id in SOURCE_CONFIG_ID_SITE_IDS:
        return SOURCE_CONFIG_ID_SITE_IDS[raw_id]
    if raw_id in SOURCE_CONFIG_TYPE_SITE_IDS:
        return SOURCE_CONFIG_TYPE_SITE_IDS[raw_id]
    if raw_type == "mediacrawler_jsonl":
        channel = str(record.get("channel") or "").lower()
        target = str(record.get("target") or "").lower()
        locator = str(record.get("locator") or "").lower()
        haystack = f"{raw_id} {channel} {target} {locator}"
        if "xhs" in haystack or "xiaohongshu" in haystack or "小红书" in haystack:
            return (MEDIACRAWLER_XHS_SITE_ID,)
        if "douyin" in haystack or "抖音" in haystack:
            return (MEDIACRAWLER_DOUYIN_SITE_ID,)
    return SOURCE_CONFIG_TYPE_SITE_IDS.get(raw_type, ())


def source_config_enabled_sources(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not config:
        return []
    sources = config.get("sources")
    if not isinstance(sources, list):
        return []
    return [
        source
        for source in sources
        if isinstance(source, dict) and source.get("enabled") is not False
    ]


def source_config_enabled_site_ids(config: dict[str, Any] | None) -> frozenset[str]:
    enabled: set[str] = set()
    for source in source_config_enabled_sources(config):
        enabled.update(source_config_record_site_ids(source))
    return frozenset(enabled)


def set_env_from_source_config(name: str, value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    os.environ[name] = value
    return True


def apply_source_config_runtime(config: dict[str, Any] | None) -> dict[str, Any]:
    enabled_sources = source_config_enabled_sources(config)
    enabled_site_ids = source_config_enabled_site_ids(config)
    applied_env: list[str] = []
    bilibili_uids: list[str] = []
    bilibili_names: list[str] = []
    wewe_feeds: list[str] = []
    we_mp_feeds: list[str] = []
    we_mp_jsonl_dirs: list[str] = []
    douyin_jsonls: list[str] = []
    douyin_names: list[str] = []
    xhs_jsonls: list[str] = []
    xhs_names: list[str] = []
    opml_path = ""

    for source in enabled_sources:
        site_ids = source_config_record_site_ids(source)
        locator = str(source.get("locator") or "").strip()
        name = str(source.get("name") or source.get("target") or "").strip()
        target = str(source.get("target") or name).strip()

        if "bilibili_dynamic" in site_ids and locator:
            bilibili_uids.append(locator)
            bilibili_names.append(target or name or f"Bilibili {locator}")
        if WEWE_RSS_SITE_ID in site_ids and locator:
            wewe_feeds.append(f"{target or name or locator}:{locator}")
        if WE_MP_RSS_SITE_ID in site_ids and locator:
            we_mp_feeds.append(f"{target or name or locator}:{locator}")
        if WE_MP_RSS_JSONL_SITE_ID in site_ids and locator:
            we_mp_jsonl_dirs.append(locator)
        if "opmlrss" in site_ids and locator:
            opml_path = locator
        if MEDIACRAWLER_DOUYIN_SITE_ID in site_ids:
            applied_env.append("MEDIACRAWLER_DOUYIN_ENABLED")
            os.environ["MEDIACRAWLER_DOUYIN_ENABLED"] = "1"
            if locator and not douyin_jsonls and set_env_from_source_config("MEDIACRAWLER_DOUYIN_JSONL", locator):
                applied_env.append("MEDIACRAWLER_DOUYIN_JSONL")
            if locator:
                douyin_jsonls.append(locator)
            if (target or name) and not douyin_names and set_env_from_source_config("MEDIACRAWLER_DOUYIN_SOURCE_NAME", target or name):
                applied_env.append("MEDIACRAWLER_DOUYIN_SOURCE_NAME")
            if target or name:
                douyin_names.append(target or name)
        if MEDIACRAWLER_XHS_SITE_ID in site_ids:
            applied_env.append("MEDIACRAWLER_XHS_ENABLED")
            os.environ["MEDIACRAWLER_XHS_ENABLED"] = "1"
            if locator and not xhs_jsonls and set_env_from_source_config("MEDIACRAWLER_XHS_JSONL", locator):
                applied_env.append("MEDIACRAWLER_XHS_JSONL")
            if locator:
                xhs_jsonls.append(locator)
            if (target or name) and not xhs_names and set_env_from_source_config("MEDIACRAWLER_XHS_SOURCE_NAME", target or name):
                applied_env.append("MEDIACRAWLER_XHS_SOURCE_NAME")
            if target or name:
                xhs_names.append(target or name)

    if bilibili_uids:
        os.environ["BILIBILI_DYNAMIC_ENABLED"] = "1"
        os.environ["BILIBILI_DYNAMIC_UIDS"] = ",".join(bilibili_uids)
        os.environ["BILIBILI_DYNAMIC_SOURCE_NAMES"] = ",".join(bilibili_names)
        applied_env.extend(["BILIBILI_DYNAMIC_ENABLED", "BILIBILI_DYNAMIC_UIDS", "BILIBILI_DYNAMIC_SOURCE_NAMES"])
    if WEWE_RSS_SITE_ID in enabled_site_ids:
        os.environ["WEWE_RSS_ENABLED"] = "1"
        applied_env.append("WEWE_RSS_ENABLED")
        if wewe_feeds:
            os.environ["WEWE_RSS_FEEDS"] = ";".join(wewe_feeds)
            applied_env.append("WEWE_RSS_FEEDS")
    if WE_MP_RSS_SITE_ID in enabled_site_ids:
        os.environ["WE_MP_RSS_ENABLED"] = "1"
        applied_env.append("WE_MP_RSS_ENABLED")
        if we_mp_feeds:
            os.environ["WE_MP_RSS_FEEDS"] = ";".join(we_mp_feeds)
            applied_env.append("WE_MP_RSS_FEEDS")
    if WE_MP_RSS_JSONL_SITE_ID in enabled_site_ids:
        os.environ["WE_MP_RSS_JSONL_ENABLED"] = "1"
        applied_env.append("WE_MP_RSS_JSONL_ENABLED")
        if we_mp_jsonl_dirs and set_env_from_source_config("WE_MP_RSS_JSONL_DIR", we_mp_jsonl_dirs[0]):
            applied_env.append("WE_MP_RSS_JSONL_DIR")
    if douyin_jsonls:
        os.environ["MEDIACRAWLER_DOUYIN_JSONLS"] = ";".join(douyin_jsonls)
        applied_env.append("MEDIACRAWLER_DOUYIN_JSONLS")
        if douyin_names:
            os.environ["MEDIACRAWLER_DOUYIN_SOURCE_NAMES"] = ";".join(douyin_names)
            applied_env.append("MEDIACRAWLER_DOUYIN_SOURCE_NAMES")
    if xhs_jsonls:
        os.environ["MEDIACRAWLER_XHS_JSONLS"] = ";".join(xhs_jsonls)
        applied_env.append("MEDIACRAWLER_XHS_JSONLS")
        if xhs_names:
            os.environ["MEDIACRAWLER_XHS_SOURCE_NAMES"] = ";".join(xhs_names)
            applied_env.append("MEDIACRAWLER_XHS_SOURCE_NAMES")
    if "xapi" in enabled_site_ids:
        os.environ["X_API_ENABLED"] = "1"
        applied_env.append("X_API_ENABLED")
    if "socialdata_x" in enabled_site_ids:
        os.environ["SOCIALDATA_ENABLED"] = "1"
        applied_env.append("SOCIALDATA_ENABLED")
    if enabled_site_ids.intersection({"tikhub_douyin", "tikhub_xiaohongshu"}):
        os.environ["TIKHUB_ENABLED"] = "1"
        applied_env.append("TIKHUB_ENABLED")
    if "agentmail" in enabled_site_ids:
        os.environ["EMAIL_DIGEST_ENABLED"] = "1"
        applied_env.append("EMAIL_DIGEST_ENABLED")

    return {
        "enabled_source_count": len(enabled_sources),
        "enabled_site_ids": sorted(enabled_site_ids),
        "applied_env": sorted(set(applied_env)),
        "rss_opml": opml_path,
    }


def github_release_api_url_from_config(locator: str) -> str:
    raw = str(locator or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.netloc.lower() == "api.github.com" and parsed.path.startswith("/repos/") and parsed.path.endswith("/releases"):
        return raw
    if parsed.netloc.lower() in {"github.com", "www.github.com"}:
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            return f"https://api.github.com/repos/{parts[0]}/{parts[1]}/releases"
    if re.match(r"^[^/\s]+/[^/\s]+$", raw):
        return f"https://api.github.com/repos/{raw}/releases"
    return raw


def github_release_repo_label_from_config(locator: str, fallback: str = "") -> str:
    raw = str(locator or "").strip()
    parsed = urlparse(raw)
    if parsed.netloc.lower() == "api.github.com":
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 3 and parts[0] == "repos":
            return f"{parts[1]}/{parts[2]}"
    if parsed.netloc.lower() in {"github.com", "www.github.com"}:
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    if re.match(r"^[^/\s]+/[^/\s]+$", raw):
        return raw
    return fallback or raw


def source_config_subscriptions_for_site(config: dict[str, Any] | None, site_id: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for source in source_config_enabled_sources(config):
        if site_id not in source_config_record_site_ids(source):
            continue
        locator = str(source.get("locator") or "").strip()
        target = str(source.get("target") or source.get("name") or "").strip()
        name = str(source.get("name") or target or locator).strip()
        if not locator:
            continue
        out.append(
            {
                "id": str(source.get("id") or "").strip(),
                "name": name,
                "target": target or name,
                "locator": locator,
            }
        )
    return out


ONLINE_PANEL_CONFIG_MODE = "online-public-source-config"


def is_online_panel_config(config: dict[str, Any] | None) -> bool:
    """是否为一条记录对应一个订阅对象的线上面板配置。"""
    if not isinstance(config, dict):
        return False
    return str(config.get("mode") or "").strip() == ONLINE_PANEL_CONFIG_MODE


@dataclass(frozen=True)
class SubscriptionAllowlist:
    """某通道仍在订阅的显示名和抖音 sec_uid。"""

    names: frozenset[str]
    sec_uids: frozenset[str]


def source_config_enabled_subscription_names(
    config: dict[str, Any] | None,
) -> dict[str, SubscriptionAllowlist]:
    """返回面板配置中可枚举通道下启用的订阅对象。"""
    if not is_online_panel_config(config):
        return {}

    names_by_site: dict[str, set[str]] = {}
    sec_uids_by_site: dict[str, set[str]] = {}
    for source in source_config_enabled_sources(config):
        for site_id in source_config_record_site_ids(source):
            if site_id not in ENUMERABLE_SUBSCRIPTION_SITE_IDS:
                continue
            name = str(source.get("target") or source.get("name") or "").strip()
            if name:
                names_by_site.setdefault(site_id, set()).add(name)
            if site_id == MEDIACRAWLER_DOUYIN_SITE_ID:
                sec_uid = douyin_sec_uid_from_locator(str(source.get("locator") or ""))
                if sec_uid:
                    sec_uids_by_site.setdefault(site_id, set()).add(sec_uid)

    return {
        site_id: SubscriptionAllowlist(
            names=frozenset(names_by_site.get(site_id) or ()),
            sec_uids=frozenset(sec_uids_by_site.get(site_id) or ()),
        )
        for site_id in set(names_by_site) | set(sec_uids_by_site)
    }



def load_paid_source_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        sources = {}
    return {"schema_version": 1, "sources": sources}


def paid_source_interval_hours(prefix: str) -> int:
    default = PAID_SOURCE_DEFAULT_INTERVAL_HOURS_BY_PREFIX.get(prefix, PAID_SOURCE_DEFAULT_INTERVAL_HOURS)
    interval = env_int(f"{prefix}_RUN_INTERVAL_HOURS", default)
    return max(1, min(interval, PAID_SOURCE_MAX_INTERVAL_HOURS))


def paid_source_state_entry(state: dict[str, Any] | None, source_key: str) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    sources = state.get("sources")
    if not isinstance(sources, dict):
        return {}
    entry = sources.get(source_key)
    return entry if isinstance(entry, dict) else {}


def paid_source_run_gate(
    prefix: str,
    source_key: str,
    now: datetime,
    state: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    if env_flag(f"{prefix}_FORCE_RUN"):
        return True, None

    current = now.astimezone(UTC)
    interval_hours = paid_source_interval_hours(prefix)
    entry = paid_source_state_entry(state, source_key)
    last_run = parse_iso(str(entry.get("last_run_at") or ""))
    if last_run:
        due_at = last_run.astimezone(UTC) + timedelta(hours=interval_hours)
        if current < due_at:
            return False, f"before_{source_key}_run_interval"
        return True, None

    run_hour = max(0, min(env_int(f"{prefix}_RUN_UTC_HOUR", 0), 23))
    minute_max = max(0, min(env_int(f"{prefix}_RUN_UTC_MINUTE_MAX", 10), 59))
    if current.hour == run_hour and current.minute <= minute_max:
        return True, None
    return False, f"outside_{source_key}_initial_window"


def update_paid_source_state(
    state: dict[str, Any],
    source_key: str,
    status: dict[str, Any],
    now: datetime,
) -> None:
    if not status.get("attempted"):
        return
    sources = state.setdefault("sources", {})
    if not isinstance(sources, dict):
        sources = {}
        state["sources"] = sources
    entry = sources.setdefault(source_key, {})
    if not isinstance(entry, dict):
        entry = {}
        sources[source_key] = entry
    entry["last_run_at"] = iso(now)
    entry["last_ok"] = bool(status.get("ok"))
    entry["last_item_count"] = int(status.get("item_count") or 0)
    if status.get("ok"):
        entry["last_success_at"] = iso(now)
        entry.pop("last_error", None)
    elif status.get("error"):
        entry["last_error"] = status.get("error")


def sync_paid_source_status_timestamps(
    status: dict[str, Any],
    state: dict[str, Any],
    source_key: str,
) -> None:
    """Keep the published status aligned with the state used by the run gate."""
    entry = paid_source_state_entry(state, source_key)
    status["last_run_at"] = entry.get("last_run_at")
    status["last_success_at"] = entry.get("last_success_at")



