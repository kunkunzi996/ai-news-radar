import json
import tempfile
import unittest
from pathlib import Path

from scripts.radar.server import online_sources

REQUIRED_MEMBER_FIELDS = ("name", "type", "locator", "target", "channel")


def sample_sources():
    return [
        {
            "id": "online_bilibili_316183842",
            "name": "技术爬爬虾",
            "type": "bilibili_dynamic",
            "enabled": True,
            "channel": "B站动态",
            "target": "技术爬爬虾",
            "locator": "316183842",
            "env": "",
            "notes": "公开 UID",
        },
        {
            "id": "online_youtube_xiaodaodalang",
            "name": "小岛大浪吹-非正经政经频道",
            "type": "rss",
            "enabled": True,
            "channel": "RSS/YouTube",
            "target": "小岛大浪吹-非正经政经频道",
            "locator": "https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw",
            "env": "SHOULD_NOT_LEAK",
            "notes": "YouTube 公开频道 feed",
        },
        {
            "id": "online_feed_openai_news",
            "name": "OpenAI News",
            "type": "rss",
            "enabled": False,
            "channel": "RSS/YouTube",
            "target": "OpenAI News",
            "locator": "https://openai.com/news/rss.xml",
            "env": "",
            "notes": "公开 feed",
        },
        {
            "id": "online_opmlrss",
            "name": "线上 RSS/YouTube 订阅包",
            "type": "opmlrss",
            "enabled": True,
            "channel": "RSS/OPML",
            "target": "feeds/online-sources.opml",
            "locator": "feeds/online-sources.opml",
            "env": "",
            "notes": "公开 feed 列表",
        },
    ]


class PublicSubscriptionMembersTests(unittest.TestCase):
    def test_write_online_source_config_writes_enabled_members_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            (root / "feeds").mkdir()
            (root / "data").mkdir()

            online_sources.write_online_source_config(root, {"sources": sample_sources()})

            public_path = root / "data" / "subscription-members.json"
            self.assertTrue(
                public_path.is_file(),
                "TEST-061：尚未写出 data/subscription-members.json",
            )
            payload = json.loads(public_path.read_text(encoding="utf-8"))
            self.assertIsInstance(payload, dict, "TEST-061：公开名单必须是对象")
            self.assertIsInstance(payload.get("generated_at"), str, "TEST-061：必须有 generated_at")
            self.assertTrue(payload["generated_at"].strip(), "TEST-061：generated_at 不能为空")
            members = payload.get("members")
            self.assertIsInstance(members, list, "TEST-061：必须有 members 数组")
            names = [str(item.get("name") or "") for item in members]
            self.assertIn("技术爬爬虾", names, "TEST-061：启用的 B站必须在公开名单里")
            self.assertIn("小岛大浪吹-非正经政经频道", names, "TEST-061：启用的油管必须在公开名单里")
            self.assertNotIn("OpenAI News", names, "TEST-061：停用的公开博客不得出现")
            self.assertNotIn("线上 RSS/YouTube 订阅包", names, "TEST-061：opmlrss 容器不得出现")
            for item in members:
                self.assertIsInstance(item, dict, "TEST-061：成员必须是对象")
                self.assertNotIn("env", item, "TEST-061：成员对象不得含 env")
                for field in REQUIRED_MEMBER_FIELDS:
                    self.assertIn(field, item, f"TEST-061：成员缺少字段 {field}")
                    self.assertIsInstance(item[field], str, f"TEST-061：{field} 必须是字符串")
                self.assertTrue(str(item["name"]).strip(), "TEST-061：name 不能为空")
