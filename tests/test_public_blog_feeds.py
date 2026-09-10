import json
import re
import unittest
from pathlib import Path

from scripts.radar.server import online_sources

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "online-sources.json"
OPML_PATH = ROOT / "feeds" / "online-sources.opml"

# 生产当前打开的 RSS/YouTube 订阅成员。
ENABLED_FEED_IDS = (
    "online_feed_microsoft_ai_blog",
    "online_feed_simon_willison",
    "online_youtube_mrbrain",
    "online_youtube_xiaodaodalang",
)
# 名单里还在、但必须停用。
DISABLED_FEED_IDS = (
    "online_feed_openai_news",
    "online_youtube_highlevelz",
)
# 已从名单拿掉；若以后加回，也必须停用。
ABSENT_OR_DISABLED_FEED_IDS = (
    "online_feed_hugging_face_blog",
    "online_feed_google_ai_blog",
    "online_feed_google_deepmind_blog",
)
ENABLED_FEED_URLS = (
    "https://news.microsoft.com/source/topics/ai/feed/",
    "https://simonwillison.net/atom/everything/",
    "https://www.youtube.com/feeds/videos.xml?channel_id=UC26hLZoe-haxcuLYxzWAiNg",
    "https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw",
)
OMITTED_FEED_URLS = (
    "https://openai.com/news/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://blog.google/technology/ai/rss/",
    "https://deepmind.google/blog/rss.xml",
    "https://www.youtube.com/feeds/videos.xml?channel_id=UCzkPX3KCIVquUPa8oXjHn0g",
)


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def sources_by_id(config: dict) -> dict:
    return {str(item.get("id") or ""): item for item in config.get("sources") or []}


def xml_urls(text: str) -> set[str]:
    return set(re.findall(r'xmlUrl="([^"]+)"', text))


class PublicBlogFeedsMatchConfigTests(unittest.TestCase):
    def test_enabled_feeds_stay_on(self) -> None:
        by_id = sources_by_id(load_config())
        for source_id in ENABLED_FEED_IDS:
            self.assertIn(source_id, by_id, source_id)
            self.assertIs(by_id[source_id].get("enabled"), True, source_id)

    def test_disabled_feeds_stay_off(self) -> None:
        by_id = sources_by_id(load_config())
        for source_id in DISABLED_FEED_IDS:
            self.assertIn(source_id, by_id, source_id)
            self.assertIs(by_id[source_id].get("enabled"), False, source_id)
        for source_id in ABSENT_OR_DISABLED_FEED_IDS:
            source = by_id.get(source_id)
            if source is None:
                continue
            self.assertIs(source.get("enabled"), False, source_id)

    def test_youtube_and_opml_container_stay_enabled(self) -> None:
        by_id = sources_by_id(load_config())
        self.assertIs(by_id["online_opmlrss"].get("enabled"), True)

    def test_opml_lists_enabled_feeds_only(self) -> None:
        text = OPML_PATH.read_text(encoding="utf-8")
        for url in ENABLED_FEED_URLS:
            self.assertIn(url, text, url)
        for url in OMITTED_FEED_URLS:
            self.assertNotIn(url, text, url)

    def test_rendered_opml_matches_disk(self) -> None:
        config = load_config()
        rendered, _feeds = online_sources.render_online_opml_bytes(config.get("sources") or [])
        disk_urls = xml_urls(OPML_PATH.read_text(encoding="utf-8"))
        rendered_urls = xml_urls(rendered.decode("utf-8"))
        self.assertEqual(rendered_urls, disk_urls)
