from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.radar.common import UTC, utc_now  # noqa: E402
from scripts.radar.fetchers.subscriptions import fetch_we_mp_rss_subscription  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export public WeRSS articles to bridge JSONL.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-items", type=int, default=20)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    session = requests.Session()
    session.trust_env = False
    now = utc_now()
    items, status = fetch_we_mp_rss_subscription(
        session,
        now,
        base_url=args.base_url,
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
    print(f"exported {len(items)} public article(s) to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
