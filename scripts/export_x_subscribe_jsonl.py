"""把本机 RSSHub 的指定推特号收成 JSONL。

不读取、不写出登录态。默认读 NUC 本机 RSSHub，写到仓库外或 feeds/x-subscribe.jsonl。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

from scripts.radar.fetchers.x_subscribe import rows_from_rss_xml

DEFAULT_RSS_URL = "http://127.0.0.1:1200/twitter/user/vista8/exclude_rts_replies"


def export_rss(url: str, output: Path) -> int:
    request = Request(url, headers={"Accept": "application/rss+xml", "User-Agent": "AI-News-Radar/0.7"})
    with urlopen(request, timeout=40) as response:
        text = response.read().decode("utf-8")
    rows = rows_from_rss_xml(text)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    output.write_text(payload, encoding="utf-8")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="把 RSSHub 的指定推特号导出成 JSONL")
    parser.add_argument("--rss-url", default=DEFAULT_RSS_URL)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    count = export_rss(args.rss_url, args.output)
    print(f"wrote {count} items to {args.output}")


if __name__ == "__main__":
    main()
