from __future__ import annotations

import json
import os
import shutil
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.radar.server import OPML_FILENAME
from scripts.radar.server.common import (
    enabled_source_config_records as enabled_source_config_records,
    read_source_config as read_source_config,
    resolve_config_path as resolve_config_path,
    source_config_runtime_ids as source_config_runtime_ids,
    validate_source_config as validate_source_config,
)

"""Source config and subscription persistence helpers."""

__all__ = [
    "PURGE_TRACKED_SITE_IDS",
    "alive_source_names_by_site",
    "enabled_source_config_records",
    "flush_pending_purge",
    "is_item_orphaned",
    "opml_path",
    "orphan_history_preview",
    "purge_deleted_source_data",
    "purge_selected_sources",
    "queue_pending_purge",
    "read_source_config",
    "read_youtube_subscriptions",
    "resolve_config_path",
    "source_config_runtime_ids",
    "validate_source_config",
    "write_youtube_subscriptions",
]

PENDING_PURGE_FILENAME = "pending-purge.json"
PENDING_PURGE_LOCK = threading.Lock()


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


PURGE_TRACKED_SITE_IDS = frozenset(
    {
        "wewe_rss",
        "we_mp_rss",
        "we_mp_rss_jsonl",
        "bilibili_dynamic",
        "mediacrawler_douyin",
        "mediacrawler_xhs",
        "github_foundation_sunshine_releases",
        "opmlrss",
    }
)


def purge_tracked_site_ids(source: dict[str, Any]) -> set[str]:
    ids = set(source_config_runtime_ids(source))
    if str(source.get("type") or "").strip().lower() == "github_release":
        ids.add("github_foundation_sunshine_releases")
    return ids & PURGE_TRACKED_SITE_IDS


def source_identity_names(
    config: dict[str, Any],
    *,
    include_disabled: bool = False,
) -> dict[str, dict[str, str]]:
    identities: dict[str, dict[str, str]] = {site_id: {} for site_id in PURGE_TRACKED_SITE_IDS}
    sources = config.get("sources") if isinstance(config, dict) else None
    if not isinstance(sources, list):
        return identities
    for source in sources:
        if not isinstance(source, dict):
            continue
        if not include_disabled and source.get("enabled") is False:
            continue
        source_type = str(source.get("type") or "").strip().lower()
        if source_type == "opmlrss":
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
            if site_id == "opmlrss" and source_type == "rss":
                display = str(source.get("name") or "").strip()
            else:
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


def deleted_source_names_by_site(
    config: dict[str, Any],
    previous_config: dict[str, Any],
) -> dict[str, set[str]]:
    current = source_identity_names(config)
    previous = source_identity_names(previous_config)
    deleted: dict[str, set[str]] = {}
    for site_id in PURGE_TRACKED_SITE_IDS:
        current_identities = current.get(site_id, {})
        removed_names = {
            old_name
            for identity_key, old_name in previous.get(site_id, {}).items()
            if identity_key not in current_identities
        }
        if removed_names:
            deleted[site_id] = removed_names
    return deleted


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


def pending_purge_path(root_dir: Path) -> Path:
    return root_dir / "data" / PENDING_PURGE_FILENAME


def read_pending_purge(root_dir: Path) -> dict[str, set[str]]:
    path = pending_purge_path(root_dir)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(raw_sources, dict):
        raise ValueError("pending purge ledger must contain a sources object")
    return {
        str(site_id): {str(name).strip() for name in names if str(name).strip()}
        for site_id, names in raw_sources.items()
        if site_id in PURGE_TRACKED_SITE_IDS and isinstance(names, list)
    }


def write_pending_purge(root_dir: Path, pending: dict[str, set[str]]) -> None:
    path = pending_purge_path(root_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sources": {
            site_id: sorted(names)
            for site_id, names in sorted(pending.items())
            if names
        },
    }
    write_json_atomic(path, payload, compact=False)


def queue_pending_purge(
    root_dir: Path,
    deleted_names: dict[str, set[str]],
    current_config: dict[str, Any],
) -> dict[str, list[str]]:
    with PENDING_PURGE_LOCK:
        path_exists = pending_purge_path(root_dir).exists()
        pending = read_pending_purge(root_dir)
        for site_id, names in deleted_names.items():
            if site_id in PURGE_TRACKED_SITE_IDS:
                pending.setdefault(site_id, set()).update(names)

        alive_names = alive_source_names_by_site(current_config)
        for site_id in list(pending):
            pending[site_id].difference_update(alive_names.get(site_id, set()))
            if not pending[site_id]:
                del pending[site_id]

        if pending or path_exists:
            write_pending_purge(root_dir, pending)
        return {site_id: sorted(names) for site_id, names in sorted(pending.items())}


def current_online_source_config(root_dir: Path) -> dict[str, Any]:
    path = root_dir / "config" / "online-sources.json"
    if not path.exists():
        return {"sources": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ValueError("online source config must contain a sources array")
    return payload


def purge_matching_source_data(
    root_dir: Path,
    should_purge: Callable[[dict[str, Any]], bool],
) -> dict[str, int]:
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
            kept = [item for item in items if not (isinstance(item, dict) and should_purge(item))]
            removed = len(items) - len(kept)
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
        kept = []
        removed = 0
        for story in payload[list_key]:
            if not isinstance(story, dict):
                kept.append(story)
                continue
            members = story.get("items")
            if not isinstance(members, list):
                members = story.get("sources") if isinstance(story.get("sources"), list) else []
            if any(isinstance(member, dict) and should_purge(member) for member in members):
                removed += 1
                continue
            kept.append(story)
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


def purge_deleted_source_data(
    root_dir: Path,
    config: dict[str, Any],
    *,
    previous_config: dict[str, Any] | None = None,
) -> dict[str, int]:
    if previous_config is not None:
        deleted_names = deleted_source_names_by_site(config, previous_config)

        def should_purge(record: dict[str, Any]) -> bool:
            site_id = str(record.get("site_id") or "").strip()
            source_name = str(record.get("source") or "").strip()
            return source_name in deleted_names.get(site_id, set())

    else:
        alive_names = alive_source_names_by_site(config)

        def should_purge(record: dict[str, Any]) -> bool:
            return is_item_orphaned(record, alive_names)

    return purge_matching_source_data(root_dir, should_purge)


def orphan_history_preview(root_dir: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """扫描 archive，返回「配置里已彻底消失的源」的历史条目分组，供手动确认删除。

    安全规则（对照 CLAUDE.md 清理禁区，宁可少删不可错删）：
    - 只覆盖有逐对象身份的通道。opmlrss 等容器型通道在 source_identity_names 里
      本就被跳过，其存活名单恒为空，不会进预览。
    - 存活名单用 include_disabled=True 构建：源只要还在配置里（哪怕 enabled:false 停用），
      其历史就不算孤儿。只有从配置里彻底删除的源才会被列出。
    - 某通道存活名单为空时整体跳过（删掉通道最后一个源的场景）——绝不把整通道判成孤儿，
      这是与 is_item_orphaned 的关键区别，后者对空名单会把整通道条目全判成孤儿。
    """
    identities = source_identity_names(config, include_disabled=True)
    alive_by_site = {site_id: set(names.values()) for site_id, names in identities.items()}

    archive_path = root_dir / "data" / "archive.json"
    if not archive_path.exists():
        return []
    try:
        payload = json.loads(archive_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for record in items:
        if not isinstance(record, dict):
            continue
        site_id = str(record.get("site_id") or "").strip()
        alive = alive_by_site.get(site_id)
        # 通道不可逐对象识别，或存活名单为空 → 跳过（安全豁免）
        if not alive:
            continue
        source_name = str(record.get("source") or "").strip()
        if source_name in alive:
            continue
        key = (site_id, source_name)
        entry = grouped.get(key)
        if entry is None:
            grouped[key] = {
                "site_id": site_id,
                "site_name": str(record.get("site_name") or "").strip() or site_id,
                "source": source_name,
                "count": 1,
            }
        else:
            entry["count"] += 1
    return sorted(grouped.values(), key=lambda e: (e["site_id"], e["source"]))


def purge_selected_sources(
    root_dir: Path,
    pairs: list[Any],
) -> dict[str, Any]:
    """按用户勾选的 (site_id, source) 对清理全部数据文件。清理前先备份 archive.json。"""
    wanted: set[tuple[str, str]] = set()
    for pair in pairs if isinstance(pairs, list) else []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        site_id = str(pair[0] or "").strip()
        source_name = str(pair[1] or "").strip()
        if site_id and source_name:
            wanted.add((site_id, source_name))
    if not wanted:
        return {"removed": {}, "backup": None, "selected": 0}

    archive_path = root_dir / "data" / "archive.json"
    backup_path: Path | None = None
    if archive_path.exists():
        plan_dir = root_dir / "计划"
        plan_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_path = plan_dir / f"archive.backup-{stamp}.json"
        shutil.copy2(archive_path, backup_path)

    def should_purge(record: dict[str, Any]) -> bool:
        site_id = str(record.get("site_id") or "").strip()
        source_name = str(record.get("source") or "").strip()
        return (site_id, source_name) in wanted

    summary = purge_matching_source_data(root_dir, should_purge)
    return {
        "removed": summary,
        "backup": str(backup_path) if backup_path else None,
        "selected": len(wanted),
    }


def flush_pending_purge(root_dir: Path) -> dict[str, int]:
    with PENDING_PURGE_LOCK:
        pending = read_pending_purge(root_dir)
        if not pending:
            return {}

        alive_names = alive_source_names_by_site(current_online_source_config(root_dir))
        confirmed = {
            site_id: names - alive_names.get(site_id, set())
            for site_id, names in pending.items()
        }
        confirmed = {site_id: names for site_id, names in confirmed.items() if names}
        if not confirmed:
            write_pending_purge(root_dir, {})
            return {}

        def should_purge(record: dict[str, Any]) -> bool:
            site_id = str(record.get("site_id") or "").strip()
            source_name = str(record.get("source") or "").strip()
            return source_name in confirmed.get(site_id, set())

        summary = purge_matching_source_data(root_dir, should_purge)
        write_pending_purge(root_dir, {})
        return summary


