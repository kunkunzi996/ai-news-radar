from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.radar.common import UTC, utc_now  # noqa: E402
from scripts.radar.fetchers.subscriptions import fetch_we_mp_rss_subscription  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export public WeRSS articles to bridge JSONL.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--subscriptions-in", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--snapshot-out", required=True)
    parser.add_argument("--previous-snapshot", default="")
    parser.add_argument("--max-items", type=int, default=20)
    return parser


def validate_authority_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("invalid_we_mp_authority_schema")
    if payload.get("authority_source") != "sidecar_db_feed_table":
        raise ValueError("invalid_we_mp_authority_source")
    if payload.get("retention_policy") != "feed_row_exists":
        raise ValueError("invalid_we_mp_retention_policy")
    if payload.get("active_policy") != "status_1_excluding_featured_v1":
        raise ValueError("invalid_we_mp_active_policy")
    feeds = payload.get("feeds")
    if not isinstance(feeds, list):
        raise ValueError("invalid_we_mp_authority_feeds")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in feeds:
        if not isinstance(row, dict):
            raise ValueError("invalid_we_mp_authority_feed")
        feed_id = str(row.get("feed_id") or "").strip()
        account = str(row.get("account") or "").strip()
        status = row.get("status")
        active = row.get("active")
        if not feed_id or not account or feed_id in seen:
            raise ValueError("invalid_we_mp_authority_identity")
        if status not in (0, 1) or not isinstance(active, bool) or active != (status == 1):
            raise ValueError(f"invalid_we_mp_authority_status:{feed_id}")
        seen.add(feed_id)
        normalized.append(
            {"feed_id": feed_id, "account": account, "status": int(status), "active": active}
        )
    normalized.sort(key=lambda row: row["feed_id"])
    active_count = sum(1 for row in normalized if row["active"])
    if payload.get("known_count") != len(normalized) or payload.get("active_count") != active_count:
        raise ValueError("invalid_we_mp_authority_counts")
    out = dict(payload)
    out["feeds"] = normalized
    return out


def active_feed_configs(authority: dict[str, Any]) -> list[dict[str, str]]:
    normalized = validate_authority_payload(authority)
    return [
        {"id": row["feed_id"], "name": row["account"]}
        for row in normalized["feeds"]
        if row["active"]
    ]


def build_subscription_snapshot(
    authority: dict[str, Any],
    *,
    source_jsonl_sha256: str,
    previous_snapshot: dict[str, Any] | None,
    generated_at: str,
) -> dict[str, Any]:
    normalized = validate_authority_payload(authority)
    known_count = len(normalized["feeds"])
    previous_empty = 0
    if isinstance(previous_snapshot, dict) and previous_snapshot.get("known_count") == 0:
        previous_empty = max(0, min(2, int(previous_snapshot.get("empty_confirmations") or 0)))
    empty_confirmations = min(2, previous_empty + 1) if known_count == 0 else 0
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "complete": normalized.get("complete") is True,
        "reason": normalized.get("reason"),
        "authority_source": normalized["authority_source"],
        "retention_policy": normalized["retention_policy"],
        "active_policy": normalized["active_policy"],
        "source_jsonl_sha256": source_jsonl_sha256.lower(),
        "known_count": known_count,
        "active_count": int(normalized["active_count"]),
        "empty_confirmations": empty_confirmations,
        "feeds": normalized["feeds"],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    args = build_parser().parse_args()
    authority = validate_authority_payload(
        json.loads(Path(args.subscriptions_in).read_text(encoding="utf-8-sig"))
    )
    session = requests.Session()
    session.trust_env = False
    now = utc_now()
    items, status = fetch_we_mp_rss_subscription(
        session,
        now,
        base_url=args.base_url,
        feeds=active_feed_configs(authority),
        max_items=args.max_items,
    )
    if not status.get("ok"):
        raise RuntimeError(str(status.get("error") or "we_mp_rss_export_failed"))

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in items:
            payload = {
                "title": item.title,
                "url": item.url,
                "published_at": (item.published_at or now).astimezone(UTC).isoformat(),
                "account": item.source,
                "feed_id": str(item.meta.get("we_mp_feed_id") or ""),
                "summary": str(item.meta.get("summary") or ""),
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    source_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    previous_snapshot = None
    if args.previous_snapshot and Path(args.previous_snapshot).is_file():
        try:
            candidate = json.loads(Path(args.previous_snapshot).read_text(encoding="utf-8-sig"))
            if isinstance(candidate, dict):
                previous_snapshot = candidate
        except (OSError, json.JSONDecodeError):
            previous_snapshot = None
    snapshot = build_subscription_snapshot(
        authority,
        source_jsonl_sha256=source_hash,
        previous_snapshot=previous_snapshot,
        generated_at=now.astimezone(UTC).isoformat(),
    )
    write_json(Path(args.snapshot_out), snapshot)
    print(f"exported {len(items)} public article(s) to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
