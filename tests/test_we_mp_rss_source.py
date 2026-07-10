from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts.radar.config_runtime import apply_source_config_runtime
from scripts.update_news import (
    discover_we_mp_rss_feeds,
    fetch_we_mp_rss_subscription,
    parse_we_mp_rss_feed_items,
)


def rss_xml(items: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>WeRSS</title>
    <link>http://127.0.0.1:8001</link>
    <description>test feed</description>
    {items}
  </channel>
</rss>
""".encode("utf-8")


class FakeResponse:
    def __init__(self, content: bytes, error: Exception | None = None):
        self.content = content
        self.error = error

    def raise_for_status(self):
        if self.error is not None:
            raise self.error


class WeMpRssSourceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 11, tzinfo=timezone.utc)

    def test_parse_we_mp_rss_feed_items_returns_complete_raw_item(self):
        content = rss_xml(
            """
            <item>
              <title>猫笔刀新文章</title>
              <link>https://mp.weixin.qq.com/s/example</link>
              <pubDate>Fri, 10 Jul 2026 08:30:00 GMT</pubDate>
              <description>文章摘要</description>
            </item>
            """
        )

        items = parse_we_mp_rss_feed_items(
            content,
            self.now,
            source_name="猫笔刀",
            feed_id="maobidao",
            max_items=20,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].site_id, "we_mp_rss")
        self.assertEqual(items[0].site_name, "WeRSS 公众号")
        self.assertEqual(items[0].source, "猫笔刀")
        self.assertEqual(items[0].title, "猫笔刀新文章")
        self.assertEqual(items[0].url, "https://mp.weixin.qq.com/s/example")
        self.assertEqual(items[0].published_at, datetime(2026, 7, 10, 8, 30, tzinfo=timezone.utc))
        self.assertEqual(items[0].meta["summary"], "文章摘要")
        self.assertEqual(items[0].meta["source_kind"], "we_mp_rss_wechat_subscription")
        self.assertEqual(items[0].meta["wechat_account"], "猫笔刀")
        self.assertEqual(items[0].meta["we_mp_feed_id"], "maobidao")
        self.assertEqual(items[0].meta["search_surface"], "we_mp_rss_xml_feed")

    def test_parse_we_mp_rss_feed_items_deduplicates_and_truncates(self):
        content = rss_xml(
            """
            <item><title>第一篇</title><link>https://example.com/1</link></item>
            <item><title>第一篇重复</title><link>https://example.com/1</link></item>
            <item><title>第二篇</title><link>https://example.com/2</link></item>
            <item><title>第三篇</title><link>https://example.com/3</link></item>
            """
        )

        items = parse_we_mp_rss_feed_items(
            content,
            self.now,
            source_name="测试号",
            feed_id="test-feed",
            max_items=2,
        )

        self.assertEqual([item.url for item in items], ["https://example.com/1", "https://example.com/2"])

    def test_discover_we_mp_rss_feeds_extracts_ids_and_skips_other_links(self):
        class FakeSession:
            def get(self, url, **kwargs):
                self.url = url
                self.kwargs = kwargs
                return FakeResponse(
                    rss_xml(
                        """
                        <item><title>猫笔刀</title><link>rss/MP_WXS_3198966508</link></item>
                        <item><title>绝对URL</title><link>http://127.0.0.1:8001/rss/maobidao</link></item>
                        <item><title>无效链接</title><link>http://127.0.0.1:8001/feed/all.rss</link></item>
                        """
                    )
                )

        session = FakeSession()
        feeds = discover_we_mp_rss_feeds(session, "http://127.0.0.1:8001")

        # sidecar 真实输出是无前导斜杠的相对 link（rss/MP_WXS_xxx），也要兼容绝对 URL 形式
        self.assertEqual(
            feeds,
            [
                {"id": "MP_WXS_3198966508", "name": "猫笔刀"},
                {"id": "maobidao", "name": "绝对URL"},
            ],
        )
        self.assertEqual(session.url, "http://127.0.0.1:8001/rss")
        self.assertEqual(session.kwargs["params"], {"limit": 30})

    def test_fetch_we_mp_rss_subscription_keeps_single_feed_failure_local(self):
        class FakeSession:
            def get(self, url, **kwargs):
                return FakeResponse(b"", RuntimeError("feed http error"))

        items, status = fetch_we_mp_rss_subscription(
            FakeSession(),
            self.now,
            base_url="http://127.0.0.1:8001",
            feeds_config="猫笔刀:maobidao",
        )

        self.assertEqual(items, [])
        self.assertFalse(status["ok"])
        self.assertEqual(status["error"], "failed_we_mp_rss_feeds:1")
        self.assertEqual(status["feeds"][0]["id"], "maobidao")
        self.assertEqual(status["feeds"][0]["error"], "feed http error")

    def test_fetch_we_mp_rss_subscription_accepts_no_discovered_feeds(self):
        class FakeSession:
            def get(self, url, **kwargs):
                return FakeResponse(rss_xml(""))

        items, status = fetch_we_mp_rss_subscription(
            FakeSession(),
            self.now,
            base_url="http://127.0.0.1:8001",
            feeds_config="",
        )

        self.assertEqual(items, [])
        self.assertTrue(status["ok"])
        self.assertEqual(status["error"], "we_mp_rss_no_feeds")

    def test_fetch_we_mp_rss_subscription_ignores_bad_feed_xml(self):
        class FakeSession:
            def get(self, url, **kwargs):
                return FakeResponse(b"not xml")

        items, status = fetch_we_mp_rss_subscription(
            FakeSession(),
            self.now,
            base_url="http://127.0.0.1:8001",
            feeds_config="猫笔刀:maobidao",
        )

        self.assertEqual(items, [])
        self.assertTrue(status["ok"])
        self.assertEqual(status["item_count"], 0)
        self.assertEqual(status["feeds"][0]["item_count"], 0)

    def test_apply_source_config_runtime_enables_we_mp_rss_without_empty_feeds_env(self):
        config = {
            "sources": [
                {
                    "id": "we_mp_rss_maobidao",
                    "type": "we_mp_rss",
                    "enabled": True,
                    "target": "猫笔刀",
                    "locator": "",
                }
            ]
        }

        with patch.dict(os.environ, {}, clear=True):
            runtime = apply_source_config_runtime(config)

            self.assertEqual(os.environ["WE_MP_RSS_ENABLED"], "1")
            self.assertNotIn("WE_MP_RSS_FEEDS", os.environ)
            self.assertIn("we_mp_rss", runtime["enabled_site_ids"])


if __name__ == "__main__":
    unittest.main()
