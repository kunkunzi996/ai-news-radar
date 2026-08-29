import json
import re
import unittest
from pathlib import Path

from scripts.radar.server import online_sources

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "online-sources.json"
OPML_PATH = ROOT / "feeds" / "online-sources.opml"

PUBLIC_BLOG_IDS = (
    "online_feed_openai_news",
    "online_feed_hugging_face_blog",
    "online_feed_simon_willison",
    "online_feed_google_ai_blog",
    "online_feed_google_deepmind_blog",
    "online_feed_microsoft_ai_blog",
)
YOUTUBE_IDS = (
    "online_youtube_mrbrain",
    "online_youtube_xiaodaodalang",
)
PUBLIC_BLOG_URLS = (
    "https://openai.com/news/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://simonwillison.net/atom/everything/",
    "https://blog.google/technology/ai/rss/",
    "https://deepmind.google/blog/rss.xml",
    "https://news.microsoft.com/source/topics/ai/feed/",
)
YOUTUBE_URLS = (
    "https://www.youtube.com/feeds/videos.xml?channel_id=UC26hLZoe-haxcuLYxzWAiNg",
    "https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw",
)


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def sources_by_id(config: dict) -> dict:
    return {str(item.get("id") or ""): item for item in config.get("sources") or []}


def xml_urls(text: str) -> set[str]:
    return set(re.findall(r'xmlUrl="([^"]+)"', text))


class PublicBlogFeedsDisabledTests(unittest.TestCase):
    def test_public_blogs_are_disabled(self) -> None:
        by_id = sources_by_id(load_config())
        for source_id in PUBLIC_BLOG_IDS:
            self.assertIn(source_id, by_id, source_id)
            self.assertIs(by_id[source_id].get("enabled"), False, source_id)

    def test_youtube_and_opml_container_stay_enabled(self) -> None:
        by_id = sources_by_id(load_config())
        for source_id in YOUTUBE_IDS:
            self.assertIn(source_id, by_id, source_id)
            self.assertIs(by_id[source_id].get("enabled"), True, source_id)
        self.assertIs(by_id["online_opmlrss"].get("enabled"), True)

    def test_opml_omits_public_blogs_and_keeps_youtube(self) -> None:
        text = OPML_PATH.read_text(encoding="utf-8")
        for url in PUBLIC_BLOG_URLS:
            self.assertNotIn(url, text, url)
        for url in YOUTUBE_URLS:
            self.assertIn(url, text, url)

    def test_rendered_opml_matches_disk(self) -> None:
        config = load_config()
        rendered, _feeds = online_sources.render_online_opml_bytes(config.get("sources") or [])
        disk_urls = xml_urls(OPML_PATH.read_text(encoding="utf-8"))
        rendered_urls = xml_urls(rendered.decode("utf-8"))
        self.assertEqual(rendered_urls, disk_urls)
