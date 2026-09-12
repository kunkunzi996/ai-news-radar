from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from scripts.radar.common import MEDIACRAWLER_DOUYIN_SITE_ID
from scripts.radar.deleted_sources import (
    DELETED_SOURCE_SITE_IDS,
    DELETED_SOURCES_KEY,
    record_matches_deleted_sources,
)
from scripts.radar.config_runtime import (
    record_is_youtube_member,
    subscription_member_id,
    youtube_channel_id_from_locator,
)
from scripts.radar.fetchers.mediacrawler import douyin_sec_uid_from_locator
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
    "deleted_source_names_by_site",
    "is_item_orphaned",
    "opml_path",
    "orphan_history_preview",
    "purge_selected_sources",
    "read_source_config",
    "read_youtube_subscriptions",
    "resolve_config_path",
    "source_config_runtime_ids",
    "validate_source_config",
    "write_youtube_subscriptions",
]

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


# 与 deleted_sources 台账认同一批通道；台账口径见 scripts/radar/deleted_sources.py。
PURGE_TRACKED_SITE_IDS = DELETED_SOURCE_SITE_IDS

# 「清理已退订信源」预览只能覆盖「配置声明即权威」的通道——手填 UID/repo，
# 配置里的存活名单与 archive 实际 source 一一对应，「不在配置里」才等于「已退订」。
#
# 严禁把桥接/动态发现型通道加进来（we_mp_rss_jsonl / wewe_rss / we_mp_rss）：
# 微信 JSONL 由 WeRSS sidecar 把后台**所有**公众号导出后采集，配置里往往只显式声明
# 其中一个（如猫笔刀），其余号是桥接自动带进来的正常在采内容。若用配置存活名单做
# 孤儿判定，会把这些「从没配过、但一直在采」的号误判成已退订（2026-07-14 真踩过：
# 卡尔的AI沃茨、数字生命卡兹克被列进待清理）。这与 ENUMERABLE_SUBSCRIPTION_SITE_IDS
# 只放 bilibili+douyin 是同一个道理——桥接通道的成员不由配置说了算。
# opmlrss 是容器型订阅包，source_identity_names 本就跳过它，这里再排除一次兜底。
PREVIEW_ELIGIBLE_SITE_IDS = frozenset(
    {
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
            locator = str(source.get("locator") or "").strip()
            if site_id == "opmlrss" and source_type == "rss":
                display = str(source.get("name") or "").strip()
                identity_key = youtube_channel_id_from_locator(locator) or record_id
            elif site_id == MEDIACRAWLER_DOUYIN_SITE_ID:
                display = str(source.get("target") or source.get("name") or "").strip()
                identity_key = douyin_sec_uid_from_locator(locator) or record_id
            else:
                display = str(source.get("target") or source.get("name") or "").strip()
                identity_key = record_id
            if identity_key and display:
                identities[site_id][identity_key] = display
    return identities


def _purge_tokens(site_id: str, mapping: dict[str, str]) -> set[str]:
    if site_id in {"bilibili_dynamic", MEDIACRAWLER_DOUYIN_SITE_ID}:
        return set(mapping)
    if site_id == "opmlrss":
        tokens: set[str] = set()
        for key, name in mapping.items():
            if str(key).startswith("UC"):
                tokens.add(key)
            else:
                tokens.add(name)
        return tokens
    return set(mapping.values())


def alive_source_names_by_site(
    config: dict[str, Any],
    previous_config: dict[str, Any] | None = None,
) -> dict[str, set[str]]:
    current = source_identity_names(config)
    previous = source_identity_names(previous_config) if previous_config else {}
    alive: dict[str, set[str]] = {}
    for site_id in PURGE_TRACKED_SITE_IDS:
        tokens = _purge_tokens(site_id, current.get(site_id, {}))
        for identity_key, old_name in previous.get(site_id, {}).items():
            if identity_key not in current.get(site_id, {}):
                continue
            if site_id in {"bilibili_dynamic", MEDIACRAWLER_DOUYIN_SITE_ID} or (
                site_id == "opmlrss" and str(identity_key).startswith("UC")
            ):
                tokens.add(identity_key)
            else:
                tokens.add(old_name)
        alive[site_id] = tokens
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
        removed: set[str] = set()
        for identity_key, old_name in previous.get(site_id, {}).items():
            if identity_key in current_identities:
                continue
            if site_id in {"bilibili_dynamic", MEDIACRAWLER_DOUYIN_SITE_ID} or (
                site_id == "opmlrss" and str(identity_key).startswith("UC")
            ):
                removed.add(identity_key)
            else:
                removed.add(old_name)
        if removed:
            deleted[site_id] = removed
    return deleted


def is_item_orphaned(record: dict[str, Any], alive_names: dict[str, set[str]]) -> bool:
    site_id = str(record.get("site_id") or "").strip()
    if site_id not in alive_names:
        return False
    member_id = subscription_member_id(record)
    if member_id:
        return member_id not in alive_names[site_id]
    if site_id in {"bilibili_dynamic", MEDIACRAWLER_DOUYIN_SITE_ID} or record_is_youtube_member(record):
        return False
    source_name = str(record.get("source") or "").strip()
    return source_name not in alive_names[site_id]


def _record_matches_tokens(record: dict[str, Any], tokens_by_site: dict[str, set[str]]) -> bool:
    return record_matches_deleted_sources(record, tokens_by_site)


def write_json_atomic(path: Path, payload: Any, *, compact: bool) -> None:
    text = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if compact
        else json.dumps(payload, ensure_ascii=False, indent=2)
    )
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def orphan_history_preview(root_dir: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """扫描 archive，返回「配置里已彻底消失的源」的历史条目分组，供手动确认删除。

    安全规则（对照 CLAUDE.md 清理禁区，宁可少删不可错删）：
    - 只覆盖「配置声明即权威」的通道（PREVIEW_ELIGIBLE_SITE_IDS）。微信桥接（we_mp_rss*
      /wewe_rss）的成员由 WeRSS 后台自动发现、不由 online-sources.json 决定，配置存活名单
      天然不完整，拿它做孤儿判定会把正在采集的号误判成已退订（2026-07-14 卡尔的AI沃茨/
      数字生命卡兹克真被误列）。这类通道整体不进预览。
    - opmlrss 等容器型通道在 source_identity_names 里本就被跳过，存活名单恒为空。
    - 存活名单用 include_disabled=True 构建：源只要还在配置里（哪怕 enabled:false 停用），
      其历史就不算孤儿。只有从配置里彻底删除的源才会被列出。
    - 某通道存活名单为空时整体跳过（删掉通道最后一个源的场景）——绝不把整通道判成孤儿，
      这是与 is_item_orphaned 的关键区别，后者对空名单会把整通道条目全判成孤儿。
    """
    identities = source_identity_names(config, include_disabled=True)
    alive_by_site = {
        site_id: _purge_tokens(site_id, names)
        for site_id, names in identities.items()
        if site_id in PREVIEW_ELIGIBLE_SITE_IDS
    }

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
        if _record_matches_tokens(record, {site_id: alive}):
            continue
        if site_id in {"bilibili_dynamic", MEDIACRAWLER_DOUYIN_SITE_ID} or record_is_youtube_member(record):
            if not subscription_member_id(record):
                continue
        source_name = str(record.get("source") or subscription_member_id(record) or "").strip()
        if not source_name:
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
    """把用户勾选的 (site_id, source) 登记进 deleted_sources 台账并同步到云端。

    2026-09-12 起不再就地改写本机 ``data/**``（那会让 NUC 工作区变脏、挡住 RadarAutoFF），
    改为：从归档里找出这些条目的稳定 ID（没有 ID 的通道用显示名）作为 token，随配置一起
    提交；云端管线下一轮写出 data/** 前剔除。返回值保留 ``removed`` / ``backup`` 两个旧键，
    ``recorded`` 是这次登记的 token，``sync`` 是同步结果。
    """
    from scripts.radar.server.online_sources import (
        read_online_source_config,
        save_and_sync_online_source_config,
    )

    wanted: set[tuple[str, str]] = set()
    for pair in pairs if isinstance(pairs, list) else []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        site_id = str(pair[0] or "").strip()
        source_name = str(pair[1] or "").strip()
        if site_id and source_name and site_id in PURGE_TRACKED_SITE_IDS:
            wanted.add((site_id, source_name))
    if not wanted:
        return {"removed": {}, "backup": None, "selected": 0, "recorded": {}, "sync": None}

    tokens_by_site: dict[str, set[str]] = {}
    archive_path = root_dir / "data" / "archive.json"
    if archive_path.exists():
        try:
            payload = json.loads(archive_path.read_text(encoding="utf-8"))
        except Exception:
            payload = None
        items = payload.get("items") if isinstance(payload, dict) else None
        for record in items if isinstance(items, list) else []:
            if not isinstance(record, dict):
                continue
            site_id = str(record.get("site_id") or "").strip()
            source_name = str(record.get("source") or "").strip()
            member_id = subscription_member_id(record)
            if (site_id, source_name) not in wanted and (site_id, member_id) not in wanted:
                continue
            if site_id in {"bilibili_dynamic", MEDIACRAWLER_DOUYIN_SITE_ID} or record_is_youtube_member(record):
                # 名称型通道只认稳定 ID；条目没有 ID 就不登记，宁可不删。
                if member_id:
                    tokens_by_site.setdefault(site_id, set()).add(member_id)
                continue
            tokens_by_site.setdefault(site_id, set()).add(source_name)
    for site_id, source_name in wanted:
        if site_id in {"bilibili_dynamic", MEDIACRAWLER_DOUYIN_SITE_ID}:
            continue
        tokens_by_site.setdefault(site_id, set()).add(source_name)

    recorded = {site_id: sorted(tokens) for site_id, tokens in sorted(tokens_by_site.items()) if tokens}
    if not recorded:
        return {"removed": {}, "backup": None, "selected": len(wanted), "recorded": {}, "sync": None}

    current = read_online_source_config(root_dir)
    payload = {
        "sources": [dict(source) for source in current["config"].get("sources", []) if isinstance(source, dict)],
        DELETED_SOURCES_KEY: recorded,
    }
    sync = save_and_sync_online_source_config(root_dir, payload, if_match=current["etag"])
    return {
        "removed": {},
        "backup": None,
        "selected": len(wanted),
        "recorded": recorded,
        "sync": {
            "ok": sync.get("ok"),
            "outcome": sync.get("outcome"),
            "pushed": sync.get("pushed"),
            "etag": sync.get("etag"),
        },
    }
