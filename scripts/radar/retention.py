"""雷达归档资讯保留：宽限、首次入库 14×24 小时、tombstone。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.radar.common import UTC, iso, parse_iso

RETAIN_WINDOW = timedelta(hours=14 * 24)
GRACE_WINDOW = timedelta(hours=14 * 24)
TOMBSTONE_FILE = "expired-tombstones.json"
POLICY_FILE = "retention-policy.json"
SNAPSHOT_RELATIVE = Path("retention-snapshots") / "archive-before-first-14d-prune.json"


def ensure_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def is_within_retain_window(record: dict[str, Any], now: datetime) -> bool:
    ts = parse_iso(record.get("first_seen_at"))
    if ts is None:
        return False
    return ts >= ensure_utc(now) - RETAIN_WINDOW


def grace_active(now: datetime, effective_at: datetime | None) -> bool:
    if effective_at is None:
        return False
    return ensure_utc(now) < ensure_utc(effective_at) + GRACE_WINDOW


def snapshot_path(output_dir: Path) -> Path:
    return output_dir / SNAPSHOT_RELATIVE


def snapshot_is_usable(path: Path | None) -> bool:
    if path is None or not path.exists() or not path.is_file():
        return False
    try:
        if path.stat().st_size < 3:
            return False
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return bool(raw) and raw not in ("{}", "[]", "null")


def write_first_prune_snapshot(output_dir: Path, archive_path: Path | None) -> Path | None:
    dest = snapshot_path(output_dir)
    if snapshot_is_usable(dest):
        return dest
    if archive_path is None or not archive_path.exists() or not archive_path.is_file():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(archive_path.read_bytes())
    if not snapshot_is_usable(dest):
        dest.unlink(missing_ok=True)
        return None
    return dest


def expired_read_keys(removed: dict[str, dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for record in removed.values():
        url = str(record.get("url") or "").strip()
        key = url
        if not key:
            site_id = str(record.get("site_id") or "").strip()
            item_id = str(record.get("id") or "").strip()
            if site_id and item_id:
                key = f"source:{site_id}:{item_id}"
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def apply_retention(
    archive: dict[str, dict[str, Any]],
    now: datetime,
    *,
    effective_at: datetime | None = None,
    tombstones: set[str] | None = None,
    output_dir: Path | None = None,
    archive_path: Path | None = None,
    fail_commit: bool = False,
) -> dict[str, Any]:
    marks = tombstones if tombstones is not None else set()
    current = ensure_utc(now)
    kept: dict[str, dict[str, Any]] = {}
    removed: dict[str, dict[str, Any]] = {}
    in_grace = grace_active(current, effective_at)
    last_prune_status = "skipped_grace" if in_grace else "not_run"

    if output_dir is not None and not in_grace:
        snap = write_first_prune_snapshot(output_dir, archive_path)
        if not snapshot_is_usable(snap):
            return {
                "archive": dict(archive),
                "removed": {},
                "retention": {
                    "grace_active": False,
                    "retain_hours": 14 * 24,
                    "last_prune_status": "not_run",
                    "expired_read_keys": [],
                },
            }
        last_prune_status = "failed" if fail_commit else "completed"

    for item_id, record in archive.items():
        if item_id in marks:
            removed[item_id] = record
            continue
        if in_grace or is_within_retain_window(record, current):
            kept[item_id] = record
            continue
        removed[item_id] = record
        marks.add(item_id)

    if fail_commit:
        last_prune_status = "failed"
    elif not in_grace:
        last_prune_status = "completed"

    return {
        "archive": kept,
        "removed": removed,
        "retention": {
            "grace_active": in_grace,
            "retain_hours": 14 * 24,
            "last_prune_status": last_prune_status,
            "expired_read_keys": expired_read_keys(removed),
        },
    }


def load_tombstones(output_dir: Path) -> set[str]:
    path = output_dir / TOMBSTONE_FILE
    if not path.exists():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = raw.get("ids") if isinstance(raw, dict) else raw
    if not isinstance(ids, list):
        return set()
    return {str(item_id) for item_id in ids if str(item_id).strip()}


def save_tombstones(output_dir: Path, tombstones: set[str]) -> None:
    path = output_dir / TOMBSTONE_FILE
    path.write_text(
        json.dumps({"ids": sorted(tombstones)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_or_init_effective_at(output_dir: Path, now: datetime) -> datetime:
    path = output_dir / POLICY_FILE
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        ts = parse_iso(raw.get("effective_at") if isinstance(raw, dict) else None)
        if ts is not None:
            return ts
    moment = ensure_utc(now)
    path.write_text(
        json.dumps({"effective_at": iso(moment)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return moment
