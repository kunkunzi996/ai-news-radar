import unittest

from scripts.radar.config_runtime import source_config_enabled_subscription_names
from scripts.radar.pipeline import filter_archive_by_subscriptions


class OrphanSubscriptionCleanupTests(unittest.TestCase):
    def test_removes_only_unsubscribed_bilibili_and_douyin_authors(self):
        archive = {
            "b-kept": {"site_id": "bilibili_dynamic", "source": "保留UP"},
            "b-removed": {"site_id": "bilibili_dynamic", "source": "已取消UP"},
            "d-kept": {"site_id": "mediacrawler_douyin", "source": "保留抖音号"},
            "d-removed": {"site_id": "mediacrawler_douyin", "source": "已取消抖音号"},
        }
        kept, removed = filter_archive_by_subscriptions(
            archive,
            {
                "bilibili_dynamic": frozenset({"保留UP"}),
                "mediacrawler_douyin": frozenset({"保留抖音号"}),
            },
        )
        self.assertEqual(set(kept), {"b-kept", "d-kept"})
        self.assertEqual(
            removed,
            {
                ("bilibili_dynamic", "已取消UP"): 1,
                ("mediacrawler_douyin", "已取消抖音号"): 1,
            },
        )

    def test_container_and_legacy_channels_are_always_preserved(self):
        archive = {
            "opml": {"site_id": "opmlrss", "source": "Wired AI"},
            "wechat": {"site_id": "we_mp_rss_jsonl", "source": "数字生命卡兹克"},
            "github": {"site_id": "github_foundation_sunshine_releases", "source": "杂鱼串流项目"},
        }
        kept, removed = filter_archive_by_subscriptions(
            archive,
            {"bilibili_dynamic": frozenset({"某UP"})},
        )
        self.assertEqual(kept, archive)
        self.assertEqual(removed, {})

    def test_missing_or_empty_allowed_map_preserves_archive(self):
        archive = {"item": {"site_id": "bilibili_dynamic", "source": "某UP"}}
        for allowed in (None, {}):
            with self.subTest(allowed=allowed):
                kept, removed = filter_archive_by_subscriptions(archive, allowed)
                self.assertIs(kept, archive)
                self.assertEqual(removed, {})

    def test_empty_site_allowlist_preserves_that_channel(self):
        archive = {"item": {"site_id": "bilibili_dynamic", "source": "某UP"}}
        kept, removed = filter_archive_by_subscriptions(
            archive,
            {"bilibili_dynamic": frozenset()},
        )
        self.assertEqual(kept, archive)
        self.assertEqual(removed, {})

    def test_enabled_subscription_names_excludes_disabled_and_container_sources(self):
        config = {
            "sources": [
                {"type": "bilibili_dynamic", "target": "启用UP", "enabled": True},
                {"type": "bilibili_dynamic", "target": "禁用UP", "enabled": False},
                {
                    "type": "mediacrawler_jsonl",
                    "channel": "抖音订阅",
                    "name": "启用抖音号",
                    "enabled": True,
                },
                {"type": "opmlrss", "name": "OPML包", "enabled": True},
                {"type": "we_mp_rss_jsonl", "name": "微信目录", "enabled": True},
            ]
        }
        self.assertEqual(
            source_config_enabled_subscription_names(config),
            {
                "bilibili_dynamic": frozenset({"启用UP"}),
                "mediacrawler_douyin": frozenset({"启用抖音号"}),
            },
        )


if __name__ == "__main__":
    unittest.main()
