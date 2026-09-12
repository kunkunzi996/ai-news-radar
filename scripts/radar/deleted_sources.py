"""已删信源台账：随 ``config/online-sources.json`` 一起提交，由采集管线剔除历史。

背景（2026-09-11）：删源时 NUC 本地就地改写 ``data/**`` 剔条目，这些未提交改动既挡住
``RadarAutoFF`` 的 ``--ff-only``，又在 ``merge_sync`` 结束时被 stash 原样盖回合并后的新数据，
``radar.wanyouomnia.cn`` 因此停更 13 小时。根治办法是让「删了谁」跟着配置一起进仓库，
在云端写出 ``data/**`` 之前剔除；NUC 不再写 ``data/**``，变成纯镜像。

台账形状（挂在 online-sources.json 顶层 ``deleted_sources``）::

    {"opmlrss": {"Simon Willison": "2026-09-12T00:17:49Z"},
     "mediacrawler_douyin": {"MS4wLjAB…": "2026-09-12T01:38:48Z"}}

键是 site_id，值是「token → 删除时刻」。token 与本地清理一直用的口径相同：抖音 / B 站 / 油管
按稳定 ID（sec_uid / uid / UC 频道号），其它通道按显示名。匹配规则见
:func:`record_matches_deleted_sources`，与 ``subscriptions_store._record_matches_tokens`` 是同一份。
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from scripts.radar.common import MEDIACRAWLER_DOUYIN_SITE_ID
from scripts.radar.config_runtime import record_is_youtube_member, subscription_member_id

DELETED_SOURCES_KEY = "deleted_sources"
# 归档首次入库后保留 14×24 小时；多留一倍余量后台账条目再没有可匹配对象，可以掉。
DELETED_SOURCE_LEDGER_DAYS = 30

DELETED_SOURCE_SITE_IDS: frozenset[str] = frozenset(
    {
        "wewe_rss",
        "we_mp_rss",
        "we_mp_rss_jsonl",
        "bilibili_dynamic",
        MEDIACRAWLER_DOUYIN_SITE_ID,
        "mediacrawler_xhs",
        "github_foundation_sunshine_releases",
        "opmlrss",
    }
)

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def utc_now_iso(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not _TIMESTAMP_RE.match(text):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_deleted_sources(raw: Any) -> dict[str, dict[str, str]]:
    """校验并规范台账；缺省 / null 视为空，结构不对就报错，不猜。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("deleted_sources_invalid: deleted_sources must be an object")
    ledger: dict[str, dict[str, str]] = {}
    for site_id, entries in raw.items():
        site = str(site_id).strip()
        if site not in DELETED_SOURCE_SITE_IDS:
            raise ValueError(f"deleted_sources_invalid: unknown site_id {site!r}")
        if not isinstance(entries, dict):
            raise ValueError(f"deleted_sources_invalid: {site} entries must be an object")
        normalized_entries: dict[str, str] = {}
        for token, deleted_at in entries.items():
            token_text = str(token).strip()
            if not token_text:
                raise ValueError(f"deleted_sources_invalid: {site} has an empty token")
            if _parse_iso(str(deleted_at)) is None:
                raise ValueError(f"deleted_sources_invalid: {site}/{token_text} deleted_at is not an ISO UTC timestamp")
            normalized_entries[token_text] = str(deleted_at).strip()
        if normalized_entries:
            ledger[site] = dict(sorted(normalized_entries.items()))
    return dict(sorted(ledger.items()))


def record_deleted_sources(
    ledger: dict[str, dict[str, str]],
    deleted_names: dict[str, set[str]] | dict[str, list[str]],
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, str]]:
    """把这次删掉的 token 记进台账。再次删除同一个源会刷新时刻（中间可能重新采过）。"""
    stamp = utc_now_iso(now)
    merged: dict[str, dict[str, str]] = {site: dict(entries) for site, entries in ledger.items()}
    for site_id, tokens in deleted_names.items():
        site = str(site_id).strip()
        if site not in DELETED_SOURCE_SITE_IDS:
            continue
        for token in tokens:
            token_text = str(token).strip()
            if token_text:
                merged.setdefault(site, {})[token_text] = stamp
    return normalize_deleted_sources(merged)


def prune_deleted_sources(
    ledger: dict[str, dict[str, str]],
    alive_tokens: dict[str, set[str]] | None,
    *,
    now: datetime | None = None,
    max_age_days: int = DELETED_SOURCE_LEDGER_DAYS,
) -> dict[str, dict[str, str]]:
    """源已加回则划掉；老过保留余量的条目也掉——它们已经没有可匹配的归档条目。"""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - timedelta(days=max_age_days)
    pruned: dict[str, dict[str, str]] = {}
    for site_id, entries in ledger.items():
        alive = (alive_tokens or {}).get(site_id, set())
        kept: dict[str, str] = {}
        for token, deleted_at in entries.items():
            if token in alive:
                continue
            parsed = _parse_iso(deleted_at)
            if parsed is None or parsed < cutoff:
                continue
            kept[token] = deleted_at
        if kept:
            pruned[site_id] = kept
    return normalize_deleted_sources(pruned)


def merge_deleted_sources(
    local: dict[str, dict[str, str]] | None,
    remote: dict[str, dict[str, str]] | None,
) -> dict[str, dict[str, str]]:
    """两边并集，同一 token 取较晚的删除时刻。"""
    merged: dict[str, dict[str, str]] = {}
    for ledger in (local or {}, remote or {}):
        for site_id, entries in ledger.items():
            bucket = merged.setdefault(site_id, {})
            for token, deleted_at in entries.items():
                previous = bucket.get(token)
                if previous is None or str(deleted_at) > previous:
                    bucket[token] = str(deleted_at)
    return normalize_deleted_sources(merged)


def deleted_source_tokens(ledger: dict[str, dict[str, str]] | None) -> dict[str, set[str]]:
    return {site_id: set(entries) for site_id, entries in (ledger or {}).items() if entries}


def record_matches_deleted_sources(record: dict[str, Any], tokens_by_site: dict[str, set[str]]) -> bool:
    """名称型通道只认稳定 ID；没有 ID 的抖音 / B 站 / 油管条目宁可不删。"""
    site_id = str(record.get("site_id") or "").strip()
    tokens = tokens_by_site.get(site_id, set())
    if not tokens:
        return False
    member_id = subscription_member_id(record)
    if member_id:
        return member_id in tokens
    if site_id in {"bilibili_dynamic", MEDIACRAWLER_DOUYIN_SITE_ID} or record_is_youtube_member(record):
        return False
    source_name = str(record.get("source") or "").strip()
    return bool(source_name) and source_name in tokens


def filter_archive_by_deleted_sources(
    archive: dict[str, dict[str, Any]],
    ledger: dict[str, dict[str, str]] | None,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], int]]:
    """按台账剔除归档条目，返回 (保留的归档, {(site_id, source): 条数})。台账为空时原样返回。"""
    tokens = deleted_source_tokens(ledger)
    if not tokens:
        return archive, {}
    removed: Counter[tuple[str, str]] = Counter()
    kept: dict[str, dict[str, Any]] = {}
    for item_id, record in archive.items():
        if isinstance(record, dict) and record_matches_deleted_sources(record, tokens):
            removed[(str(record.get("site_id") or ""), str(record.get("source") or ""))] += 1
            continue
        kept[item_id] = record
    if not removed:
        return archive, {}
    return kept, dict(removed)


def deleted_source_cleanup_status(
    ledger: dict[str, dict[str, str]] | None,
    removed: dict[tuple[str, str], int],
) -> dict[str, Any]:
    """写进 source-status.json 顶层，让人能看到云端到底按台账剔了什么。"""
    tokens = deleted_source_tokens(ledger)
    return {
        "enabled": bool(tokens),
        "token_count": sum(len(values) for values in tokens.values()),
        "sites": {site_id: sorted(values) for site_id, values in sorted(tokens.items())},
        "removed_total": sum(removed.values()),
        "removed": [
            {"site_id": site_id, "source": source, "count": count}
            for (site_id, source), count in sorted(removed.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }
