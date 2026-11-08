"""频道 RSS 地址按订阅去拉，不能写进 OPML 文件路径。"""
from datetime import datetime, timezone
from unittest.mock import patch

from scripts.radar.config_runtime import apply_source_config_runtime
from scripts.radar.fetchers.subscriptions import fetch_opml_rss


def test_channel_url_does_not_replace_opml_file():
    runtime = apply_source_config_runtime({
        "sources": [
            {
                "type": "rss",
                "name": "脑总MrBrain",
                "enabled": True,
                "locator": "https://www.youtube.com/feeds/videos.xml?channel_id=UC26hLZoe-haxcuLYxzWAiNg",
            },
            {
                "type": "rss",
                "name": "小岛大浪吹-非正经政经频道",
                "enabled": True,
                "locator": "https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw",
            },
            {
                "type": "opmlrss",
                "name": "线上 RSS/YouTube 订阅包",
                "enabled": True,
                "locator": "feeds/online-sources.opml",
            },
        ]
    })

    assert runtime["rss_opml"] == "feeds/online-sources.opml"
    assert [feed["xml_url"] for feed in runtime["rss_feeds"]] == [
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC26hLZoe-haxcuLYxzWAiNg",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw",
    ]


def test_http_locator_on_opml_source_is_a_feed_not_a_file():
    runtime = apply_source_config_runtime({
        "sources": [
            {
                "type": "opmlrss",
                "name": "小岛大浪吹-非正经政经频道",
                "enabled": True,
                "locator": "https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw",
            }
        ]
    })

    assert runtime["rss_opml"] == ""
    assert runtime["rss_feeds"][0]["xml_url"].startswith("https://www.youtube.com/feeds/")


def test_direct_feed_is_requested_without_an_opml_file():
    class FakeResp:
        status_code = 200
        content = (
            "<rss><channel><title>小岛</title><item>"
            "<title>new</title><link>https://www.youtube.com/watch?v=new1</link>"
            "<pubDate>Mon, 08 Sep 2026 00:00:00 GMT</pubDate>"
            "</item></channel></rss>"
        ).encode("utf-8")
        text = content.decode("utf-8")

        def raise_for_status(self):
            return None

    seen = []

    def fake_get(url, timeout=None, headers=None):
        seen.append(url)
        return FakeResp()

    with patch("scripts.radar.fetchers.subscriptions.requests.get", side_effect=fake_get):
        items, summary, statuses = fetch_opml_rss(
            datetime(2026, 9, 8, tzinfo=timezone.utc),
            None,
            extra_feeds=[{
                "title": "小岛大浪吹-非正经政经频道",
                "xml_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw",
                "html_url": "",
            }],
            sleeper=lambda _seconds: None,
        )

    assert seen == ["https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw"]
    assert [item.title for item in items] == ["new"]
    assert summary["ok"] is True
    assert statuses[0]["feed_title"] == "小岛大浪吹-非正经政经频道"
