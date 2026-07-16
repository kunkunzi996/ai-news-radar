#!/usr/bin/env python3
"""One-time WeChat archive identity migration. Dry-run is the default."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def bridge_head(bridge_repo: Path) -> str:
    return subprocess.check_output(["git", "-C", str(bridge_repo), "rev-parse", "HEAD"], text=True).strip()


def account_feed_ids_from_history(bridge_repo: Path) -> dict[str, set[str]]:
    shallow = subprocess.check_output(
        ["git", "-C", str(bridge_repo), "rev-parse", "--is-shallow-repository"], text=True
    ).strip()
    if shallow != "false":
        raise ValueError("bridge_history_is_shallow")
    objects = subprocess.check_output(
        ["git", "-C", str(bridge_repo), "rev-list", "--objects", "--all"], text=True, encoding="utf-8"
    )
    blobs = {
        line.split(" ", 1)[0]
        for line in objects.splitlines()
        if " " in line and line.split(" ", 1)[1].replace("\\", "/").endswith("wechat_contents_latest.jsonl")
    }
    if not blobs:
        raise ValueError("bridge_history_has_no_wechat_jsonl")
    mapping: dict[str, set[str]] = {}
    for blob in sorted(blobs):
        content = subprocess.check_output(["git", "-C", str(bridge_repo), "cat-file", "-p", blob])
        for raw_line in content.decode("utf-8-sig").splitlines():
            if not raw_line.strip():
                continue
            row = json.loads(raw_line)
            account = str(row.get("account") or "").strip()
            feed_id = str(row.get("feed_id") or "").strip()
            if account and feed_id:
                mapping.setdefault(account, set()).add(feed_id)
    return mapping


def _archive_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    if all(isinstance(value, dict) for value in payload.values()):
        return list(payload.values())
    raise ValueError("invalid_archive_shape")


def plan_migration(
    archive_payload: dict[str, Any], account_mapping: dict[str, set[str]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    migrated = deepcopy(archive_payload)
    original_items = _archive_items(archive_payload)
    migrated_items = _archive_items(migrated)
    unmatched_sources: set[str] = set()
    conflict_sources: set[str] = set()
    fillable = 0
    for original, record in zip(original_items, migrated_items, strict=True):
        if str(original.get("site_id") or "") != "we_mp_rss_jsonl" or str(original.get("we_mp_feed_id") or "").strip():
            continue
        source = str(original.get("source") or "").strip()
        ids = account_mapping.get(source, set())
        if not ids:
            unmatched_sources.add(source)
        elif len(ids) > 1:
            conflict_sources.add(source)
        else:
            record["we_mp_feed_id"] = next(iter(ids))
            fillable += 1
    wechat = [item for item in migrated_items if str(item.get("site_id") or "") == "we_mp_rss_jsonl"]
    with_id = sum(bool(str(item.get("we_mp_feed_id") or "").strip()) for item in wechat)
    before_without_id = sum(
        str(item.get("site_id") or "") == "we_mp_rss_jsonl" and not str(item.get("we_mp_feed_id") or "").strip()
        for item in original_items
    )
    report = {
        "total_records_before": len(original_items),
        "total_records_after": len(migrated_items),
        "wechat_records": len(wechat),
        "without_id_before": before_without_id,
        "fillable_records": fillable,
        "unmatched_records": sum(
            str(item.get("site_id") or "") == "we_mp_rss_jsonl"
            and not str(item.get("we_mp_feed_id") or "").strip()
            and str(item.get("source") or "").strip() in unmatched_sources
            for item in original_items
        ),
        "conflict_records": sum(
            str(item.get("site_id") or "") == "we_mp_rss_jsonl"
            and not str(item.get("we_mp_feed_id") or "").strip()
            and str(item.get("source") or "").strip() in conflict_sources
            for item in original_items
        ),
        "unmatched_sources": sorted(unmatched_sources),
        "conflict_sources": sorted(conflict_sources),
        "with_id_after": with_id,
        "coverage_after": 1.0 if not wechat else with_id / len(wechat),
        "deleted_records": len(original_items) - len(migrated_items),
    }
    return migrated, report


def main() -> int:
    parser = argparse.ArgumentParser(description="微信公众号历史记录 feed_id 一次性迁移（默认 dry-run）")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--bridge-repo", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-bridge-head")
    parser.add_argument("--expected-archive-sha256")
    parser.add_argument("--report")
    args = parser.parse_args()
    archive_path = Path(args.archive).resolve()
    bridge_repo = Path(args.bridge_repo).resolve()
    archive_bytes = archive_path.read_bytes()
    archive_hash = sha256_bytes(archive_bytes)
    head = bridge_head(bridge_repo)
    if args.apply and (args.expected_bridge_head != head or args.expected_archive_sha256 != archive_hash):
        raise SystemExit("apply_refused_stale_baseline")
    migrated, report = plan_migration(
        json.loads(archive_bytes.decode("utf-8-sig")), account_feed_ids_from_history(bridge_repo)
    )
    report.update({"mode": "apply" if args.apply else "dry-run", "bridge_head": head, "archive_sha256": archive_hash})
    hard_ok = (
        report["fillable_records"] == report["without_id_before"]
        and report["unmatched_records"] == 0
        and report["conflict_records"] == 0
        and report["deleted_records"] == 0
        and report["coverage_after"] == 1.0
    )
    report["hard_conditions_passed"] = hard_ok
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if args.apply:
        if not hard_ok:
            return 2
        temporary = archive_path.with_suffix(archive_path.suffix + ".tmp")
        temporary.write_text(json.dumps(migrated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(archive_path)
    return 0 if hard_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
