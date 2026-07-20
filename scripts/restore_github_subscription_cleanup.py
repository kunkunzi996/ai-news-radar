#!/usr/bin/env python3
"""Precisely restore selected GitHub archive records without replacing the archive."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.radar.common import GITHUB_REPO_SUBSCRIPTION_SITE_ID
from scripts.radar.server import online_sources as _online_sources


def _item_map(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], bool]:
    if isinstance(payload.get("items"), list):
        raw_items = payload["items"]
        envelope = True
    elif all(isinstance(value, dict) for value in payload.values()):
        raw_items = list(payload.values())
        envelope = False
    else:
        raise ValueError("invalid_archive_shape")

    mapped: dict[str, dict[str, Any]] = {}
    for record in raw_items:
        if not isinstance(record, dict):
            raise ValueError("invalid_archive_shape")
        # The CLI's --item-id maps to the record's real id field, never to a
        # hypothetical item_id JSON field or an enclosing object key.
        item_id = record.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in mapped:
            raise ValueError("invalid_archive_item_id")
        mapped[item_id] = record
    return mapped, envelope


def restore_github_items_by_id(
    current: dict[str, Any],
    before: dict[str, Any],
    item_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    current_items, current_envelope = _item_map(current)
    before_items, _before_envelope = _item_map(before)
    requested = list(dict.fromkeys(value.strip() for value in item_ids if isinstance(value, str) and value.strip()))
    missing_ids: list[str] = []
    conflict_ids: list[str] = []
    planned: list[str] = []
    for item_id in requested:
        if item_id in current_items:
            conflict_ids.append(item_id)
        elif item_id not in before_items or before_items[item_id].get("site_id") != GITHUB_REPO_SUBSCRIPTION_SITE_ID:
            missing_ids.append(item_id)
        else:
            planned.append(item_id)

    report = {
        "restored_item_ids": [],
        "already_present_item_ids": conflict_ids,
        "conflict_item_ids": conflict_ids,
        "missing_item_ids": missing_ids,
        "fail_safe": bool(conflict_ids or missing_ids),
    }
    if report["fail_safe"]:
        return deepcopy(current), report

    restored = deepcopy(current)
    if current_envelope:
        target_items = restored["items"]
        for item_id in planned:
            target_items.append(deepcopy(before_items[item_id]))
            report["restored_item_ids"].append(item_id)
        if isinstance(restored.get("total_items"), int):
            restored["total_items"] = len(target_items)
    else:
        for item_id in planned:
            restored[item_id] = deepcopy(before_items[item_id])
            report["restored_item_ids"].append(item_id)
    return restored, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Precisely restore selected GitHub archive records")
    parser.add_argument("--current", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--item-id", action="append", required=True)
    parser.add_argument("--apply", action="store_true", help="Write only after a successful full precheck")
    args = parser.parse_args()

    current_path = Path(args.current)
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
        before = json.loads(Path(args.before).read_text(encoding="utf-8"))
        if not isinstance(current, dict) or not isinstance(before, dict):
            raise ValueError("invalid_archive_shape")
        restored, report = restore_github_items_by_id(current, before, args.item_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"apply": args.apply, "fail_safe": True, "error": str(exc) or "invalid_archive"}))
        return 2

    print(json.dumps({"apply": args.apply, **report}, ensure_ascii=False))
    if args.apply and not report["fail_safe"]:
        try:
            _online_sources.write_json_atomic(current_path, restored)
        except OSError:
            return 2
    return 0 if not report["fail_safe"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
