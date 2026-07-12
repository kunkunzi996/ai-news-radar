import unittest

from scripts.audit_orphan_items import parse_args as parse_audit_args
from scripts.radar.config_runtime import (
    SubscriptionAllowlist,
    is_online_panel_config,
    source_config_enabled_subscription_names,
)
from scripts.radar.pipeline import filter_archive_by_subscriptions


def allowlist(*names: str, sec_uids: tuple[str, ...] = ()) -> SubscriptionAllowlist:
    return SubscriptionAllowlist(frozenset(names), frozenset(sec_uids))


class OrphanSubscriptionCleanupTests(unittest.TestCase):
    def test_identifies_online_panel_config_by_mode(self):
        self.assertTrue(is_online_panel_config({"mode": "online-public-source-config"}))
        self.assertFalse(is_online_panel_config({"sources": []}))
        self.assertFalse(is_online_panel_config(None))

    def test_container_config_cannot_delete_bilibili_archive(self):
        config = {
            "sources": [
                {"type": "bilibili_dynamic", "target": "作者A,作者B", "enabled": True}
            ]
        }
        allowed = source_config_enabled_subscription_names(config)
        archive = {
            "a": {"site_id": "bilibili_dynamic", "source": "作者A"},
            "b": {"site_id": "bilibili_dynamic", "source": "作者B"},
        }
        kept, removed, fused = filter_archive_by_subscriptions(archive, allowed)
        self.assertEqual(allowed, {})
        self.assertIs(kept, archive)
        self.assertEqual((removed, fused), ({}, []))

    def test_bilibili_removes_only_unsubscribed_author(self):
        archive = {
            "kept": {"site_id": "bilibili_dynamic", "source": "保留UP"},
            "removed": {"site_id": "bilibili_dynamic", "source": "已取消UP"},
            "other": {"site_id": "opmlrss", "source": "Wired AI"},
        }
        kept, removed, fused = filter_archive_by_subscriptions(
            archive, {"bilibili_dynamic": allowlist("保留UP", "另一UP")}
        )
        self.assertEqual(set(kept), {"kept", "other"})
        self.assertEqual(removed, {("bilibili_dynamic", "已取消UP"): 1})
        self.assertEqual(fused, [])

    def test_douyin_matches_sec_uid_and_preserves_legacy_item_without_id(self):
        archive = {
            "kept": {
                "site_id": "mediacrawler_douyin",
                "source": "真实昵称",
                "douyin_sec_user_id": "uid-kept",
            },
            "removed": {
                "site_id": "mediacrawler_douyin",
                "source": "另一个昵称",
                "douyin_sec_user_id": "uid-removed",
            },
            "legacy": {"site_id": "mediacrawler_douyin", "source": "历史真实昵称"},
        }
        kept, removed, fused = filter_archive_by_subscriptions(
            archive,
            {"mediacrawler_douyin": allowlist("面板备注名", sec_uids=("uid-kept",))},
        )
        self.assertEqual(set(kept), {"kept", "legacy"})
        self.assertEqual(removed, {("mediacrawler_douyin", "另一个昵称"): 1})
        self.assertEqual(fused, [])

    def test_empty_allowlist_preserves_channel(self):
        archive = {"item": {"site_id": "bilibili_dynamic", "source": "某UP"}}
        for allowed in (None, {}, {"bilibili_dynamic": allowlist()}):
            with self.subTest(allowed=allowed):
                kept, removed, fused = filter_archive_by_subscriptions(archive, allowed)
                self.assertEqual(kept, archive)
                self.assertEqual((removed, fused), ({}, []))

    def test_large_normal_removal_is_not_fused_when_some_items_match(self):
        archive = {
            str(index): {"site_id": "bilibili_dynamic", "source": "保留UP" if index < 2 else f"取消{index}"}
            for index in range(10)
        }
        kept, removed, fused = filter_archive_by_subscriptions(
            archive, {"bilibili_dynamic": allowlist("保留UP")}
        )
        self.assertEqual(len(kept), 2)
        self.assertEqual(sum(removed.values()), 8)
        self.assertEqual(fused, [])

    def test_zero_match_fuses_mismatched_channel(self):
        archive = {
            str(index): {"site_id": "bilibili_dynamic", "source": "作者A" if index < 5 else "作者B"}
            for index in range(10)
        }
        kept, removed, fused = filter_archive_by_subscriptions(
            archive, {"bilibili_dynamic": allowlist("作者A,作者B")}
        )
        self.assertIs(kept, archive)
        self.assertEqual(removed, {})
        self.assertEqual(fused, ["bilibili_dynamic"])

    def test_force_bypasses_zero_match_fuse(self):
        archive = {
            str(index): {"site_id": "bilibili_dynamic", "source": "作者A" if index < 5 else "作者B"}
            for index in range(10)
        }
        kept, removed, fused = filter_archive_by_subscriptions(
            archive, {"bilibili_dynamic": allowlist("作者A,作者B")}, force=True
        )
        self.assertEqual(kept, {})
        self.assertEqual(sum(removed.values()), 10)
        self.assertEqual(fused, [])

    def test_douyin_legacy_items_do_not_count_as_matches(self):
        archive = {
            **{
                f"legacy-{index}": {"site_id": "mediacrawler_douyin", "source": f"旧昵称{index}"}
                for index in range(4)
            },
            "doomed": {
                "site_id": "mediacrawler_douyin",
                "source": "新昵称",
                "douyin_sec_user_id": "uid-not-allowed",
            },
        }
        kept, removed, fused = filter_archive_by_subscriptions(
            archive,
            {"mediacrawler_douyin": allowlist("面板备注", sec_uids=("uid-allowed",))},
        )
        self.assertIs(kept, archive)
        self.assertEqual(removed, {})
        self.assertEqual(fused, ["mediacrawler_douyin"])

    def test_audit_defaults_to_online_panel_config(self):
        args = parse_audit_args([])
        self.assertEqual(args.source_config, "config/online-sources.json")
        self.assertFalse(args.force)

    def test_panel_config_builds_names_and_douyin_ids(self):
        config = {
            "mode": "online-public-source-config",
            "sources": [
                {"type": "bilibili_dynamic", "target": "启用UP", "enabled": True},
                {"type": "bilibili_dynamic", "target": "禁用UP", "enabled": False},
                {
                    "type": "mediacrawler_jsonl",
                    "channel": "抖音订阅",
                    "name": "备注名",
                    "locator": "https://www.douyin.com/user/sec-123",
                    "enabled": True,
                },
                {"type": "opmlrss", "name": "OPML包", "enabled": True},
            ],
        }
        self.assertEqual(
            source_config_enabled_subscription_names(config),
            {
                "bilibili_dynamic": allowlist("启用UP"),
                "mediacrawler_douyin": allowlist("备注名", sec_uids=("sec-123",)),
            },
        )


if __name__ == "__main__":
    unittest.main()
