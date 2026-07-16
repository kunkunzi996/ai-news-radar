#!/usr/bin/env python3
"""Precisely restore selected WeChat records without replacing the archive."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


def _item_map(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], bool]:
    if isinstance(payload.get("items"), list):
        return {
            str(item.get("id") or ""): item
            for item in payload["items"]
            if isinstance(item, dict) and str(item.get("id") or "")
        }, True
    if all(isinstance(value, dict) for value in payload.values()):
        return {str(item_id): record for item_id, record in payload.items()}, False
    raise ValueError("invalid_archive_shape")


def restore_items_by_id(
    current: dict[str, Any],
    before: dict[str, Any],
    item_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    restored = deepcopy(current)
    current_items, current_envelope = _item_map(current)
    before_items, _before_envelope = _item_map(before)
    requested = list(dict.fromkeys(str(value).strip() for value in item_ids if str(value).strip()))
    missing_ids: list[str] = []
    conflict_ids: list[str] = []
    planned: list[str] = []
    for item_id in requested:
        if item_id in current_items:
            conflict_ids.append(item_id)
        elif item_id not in before_items or str(before_items[item_id].get("site_id") or "") != "we_mp_rss_jsonl":
            missing_ids.append(item_id)
        else:
            planned.append(item_id)
    # A mixed request must never partly apply: one conflict/missing ID fuses the whole batch.
    restored_ids: list[str] = []
    if not missing_ids and not conflict_ids:
        if current_envelope:
            target_items = restored["items"]
            for item_id in planned:
                target_items.append(deepcopy(before_items[item_id]))
                restored_ids.append(item_id)
            if isinstance(restored.get("total_items"), int):
                restored["total_items"] = len(target_items)
        else:
            for item_id in planned:
                restored[item_id] = deepcopy(before_items[item_id])
                restored_ids.append(item_id)
    return restored, {
        "restored_item_ids": restored_ids,
        "already_present_item_ids": conflict_ids,
        "conflict_item_ids": conflict_ids,
        "missing_item_ids": missing_ids,
        "fail_safe": bool(missing_ids or conflict_ids),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="按 item_id 精确恢复微信公众号归档")
    parser.add_argument("--current", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--item-id", action="append", required=True)
    parser.add_argument("--apply", action="store_true", help="默认仅审计；显式指定才写回 current")
    args = parser.parse_args()
    current_path = Path(args.current)
    current = json.loads(current_path.read_text(encoding="utf-8"))
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    restored, report = restore_items_by_id(current, before, args.item_id)
    print(json.dumps({"apply": args.apply, **report}, ensure_ascii=False))
    if args.apply and not report["fail_safe"]:
        temporary = current_path.with_suffix(current_path.suffix + ".tmp")
        temporary.write_text(json.dumps(restored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(current_path)
    return 0 if not report["fail_safe"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
