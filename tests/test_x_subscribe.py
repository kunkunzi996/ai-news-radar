import json
import unittest
from datetime import datetime, timezone

from scripts.radar.fetchers.x_subscribe import (
    X_SUBSCRIBE_SITE_ID,
    parse_x_subscribe_jsonl,
    rows_from_rss_xml,
)
from scripts.radar.server.online_sources import normalize_online_source_record


NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)
RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>乔木的一条更新</title>
  <description>正文&lt;br&gt;第二行</description>
  <link>https://x.com/vista8/status/2102714888783368455</link>
  <pubDate>Wed, 23 Sep 2026 11:01:10 GMT</pubDate>
  <author>向阳乔木</author>
</item>
<item>
  <title>别人的推文</title>
  <link>https://x.com/other/status/1</link>
  <pubDate>Wed, 23 Sep 2026 10:00:00 GMT</pubDate>
  <author>别人</author>
</item>
</channel></rss>
"""


class XSubscribeTests(unittest.TestCase):
    def test_rss_rows_keep_status_links(self) -> None:
        rows = rows_from_rss_xml(RSS)
        self.assertEqual([row["handle"] for row in rows], ["vista8", "other"])
        self.assertEqual(rows[0]["name"], "向阳乔木")
        self.assertIn("第二行", rows[0]["summary"])

    def test_jsonl_keeps_named_handles_out_of_aihot(self) -> None:
        rows = rows_from_rss_xml(RSS)
        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        items = parse_x_subscribe_jsonl(
            text,
            now=NOW,
            allowed_handles={"vista8"},
            names_by_handle={"vista8": "向阳乔木"},
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].site_id, X_SUBSCRIBE_SITE_ID)
        self.assertEqual(items[0].source, "向阳乔木")
        self.assertNotIn("aihot_selected", items[0].meta)
        self.assertEqual(items[0].published_at.isoformat(), "2026-09-23T11:01:10+00:00")

    def test_online_config_keeps_handle(self) -> None:
        record = normalize_online_source_record(
            {
                "id": "online_x_vista8",
                "name": "向阳乔木",
                "type": "x_subscribe",
                "enabled": True,
                "locator": "@vista8",
            },
            0,
            existing=True,
        )
        self.assertEqual(record["type"], "x_subscribe")
        self.assertEqual(record["locator"], "vista8")
        self.assertEqual(record["channel"], "推特订阅")


if __name__ == "__main__":
    unittest.main()
