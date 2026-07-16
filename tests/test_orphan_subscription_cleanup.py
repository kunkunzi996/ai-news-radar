import unittest

import importlib.util
import json
from pathlib import Path
from copy import deepcopy
import subprocess
import sys

from scripts.audit_orphan_items import parse_args as parse_audit_args
from scripts.radar.config_runtime import (
    SubscriptionAllowlist,
    is_online_panel_config,
    source_config_enabled_subscription_names,
)
from scripts.radar.pipeline import filter_archive_by_subscriptions
import scripts.radar.pipeline as pipeline_module
from scripts.radar.cli import apply_we_mp_subscription_cleanup, ensure_we_mp_cleanup_audit_status


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

    def test_wechat_hard_delete_is_id_only_and_status_zero_is_retained(self):
        filter_wechat = getattr(pipeline_module, "filter_we_mp_archive_by_known_feed_ids")
        archive = {
            "active": {
                "id": "active",
                "site_id": "we_mp_rss_jsonl",
                "source": "启用号",
                "we_mp_feed_id": "active-id",
            },
            "paused": {
                "id": "paused",
                "site_id": "we_mp_rss_jsonl",
                "source": "停用号",
                "we_mp_feed_id": "paused-id",
            },
            "deleted": {
                "id": "deleted",
                "site_id": "we_mp_rss_jsonl",
                "source": "已删除号",
                "we_mp_feed_id": "deleted-id",
            },
            "other": {"id": "other", "site_id": "opmlrss", "source": "其它"},
        }

        kept, candidates, reasons = filter_wechat(
            archive,
            known_feed_ids={"active-id", "paused-id"},
        )

        self.assertEqual(set(kept), {"active", "paused", "other"})
        self.assertEqual([record["id"] for record in candidates], ["deleted"])
        self.assertEqual(reasons, [])

    def test_wechat_archive_without_id_fuses_entire_cleanup(self):
        filter_wechat = getattr(pipeline_module, "filter_we_mp_archive_by_known_feed_ids")
        archive = {
            "legacy": {"id": "legacy", "site_id": "we_mp_rss_jsonl", "source": "旧号"},
            "deleted": {
                "id": "deleted",
                "site_id": "we_mp_rss_jsonl",
                "source": "已删除号",
                "we_mp_feed_id": "deleted-id",
            },
        }

        kept, candidates, reasons = filter_wechat(archive, known_feed_ids=set())

        self.assertIs(kept, archive)
        self.assertEqual(candidates, [])
        self.assertIn("archive_missing_we_mp_feed_id", reasons)

    def test_wechat_cleanup_uses_archive_key_when_record_id_is_missing_or_wrong(self):
        archive = {
            "authoritative-a": {"site_id": "we_mp_rss_jsonl", "source": "A", "we_mp_feed_id": "deleted-a"},
            "authoritative-b": {"id": "wrong-id", "site_id": "we_mp_rss_jsonl", "source": "B", "we_mp_feed_id": "deleted-b"},
            "keep": {"id": "keep", "site_id": "we_mp_rss_jsonl", "source": "K", "we_mp_feed_id": "known"},
        }
        kept, candidates, reasons = pipeline_module.filter_we_mp_archive_by_known_feed_ids(archive, {"known"})
        self.assertEqual(set(kept), {"keep"})
        self.assertEqual([item["id"] for item in candidates], ["authoritative-a", "authoritative-b"])
        self.assertEqual(reasons, [])

    def test_precise_restore_keeps_data_added_after_cleanup(self):
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "restore_we_mp_cleanup.py"
        spec = importlib.util.spec_from_file_location("restore_we_mp_cleanup", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        before = {
            "deleted": {"id": "deleted", "site_id": "we_mp_rss_jsonl", "title": "旧微信"},
            "kept": {"id": "kept", "site_id": "opmlrss", "title": "旧其它"},
        }
        current = {
            "kept": {"id": "kept", "site_id": "opmlrss", "title": "旧其它"},
            "new": {"id": "new", "site_id": "github", "title": "清理后新增"},
        }

        restored, report = module.restore_items_by_id(current, before, ["deleted"])

        self.assertEqual(set(restored), {"deleted", "kept", "new"})
        self.assertEqual(restored["new"]["title"], "清理后新增")
        self.assertEqual(report["restored_item_ids"], ["deleted"])

    def test_wechat_cleanup_modes_and_status_zero_retention(self):
        archive = {
            "paused": {"id": "paused", "site_id": "we_mp_rss_jsonl", "source": "停用", "we_mp_feed_id": "paused"},
            "deleted": {"id": "deleted", "site_id": "we_mp_rss_jsonl", "source": "删除", "we_mp_feed_id": "deleted"},
        }
        base_status = {
            "ok": True,
            "cleanup_capable": True,
            "manifest_schema": 2,
            "snapshot_schema": 1,
            "bridge_commit": "abc",
            "known_feed_ids": ["paused"],
            "empty_confirmations": 0,
        }
        for mode, expected_keys, applied in (
            ("off", set(archive), False),
            ("audit", set(archive), False),
            ("on", {"paused"}, True),
        ):
            status = deepcopy(base_status)
            result = apply_we_mp_subscription_cleanup(
                archive, status, channel_enabled=True, mode=mode, expected_bridge_commit="abc"
            )
            self.assertEqual(set(result), expected_keys)
            self.assertEqual(status["subscription_cleanup"]["applied"], applied)
            if mode != "off":
                self.assertEqual(status["subscription_cleanup"]["candidate_feed_ids"], ["deleted"])

    def test_wechat_cleanup_fails_closed_on_bad_contract_and_unconfirmed_empty(self):
        archive = {
            "item": {"id": "item", "site_id": "we_mp_rss_jsonl", "source": "号", "we_mp_feed_id": "feed"}
        }
        for change, reason in (
            ({"ok": False}, "channel_failed"),
            ({"manifest_schema": 1}, "invalid_authoritative_contract"),
            ({"bridge_commit": "stale"}, "bridge_commit_not_bound"),
            ({"known_feed_ids": [], "empty_confirmations": 1}, "empty_snapshot_not_confirmed"),
        ):
            status = {
                "ok": True,
                "cleanup_capable": True,
                "manifest_schema": 2,
                "snapshot_schema": 1,
                "bridge_commit": "abc",
                "known_feed_ids": ["other"],
                "empty_confirmations": 2,
                **change,
            }
            result = apply_we_mp_subscription_cleanup(
                archive, status, channel_enabled=True, mode="on", expected_bridge_commit="abc"
            )
            self.assertIs(result, archive)
            self.assertIn(reason, status["subscription_cleanup"]["skip_reasons"])

    def test_missing_wechat_status_is_synthesized_for_audit_and_on(self):
        for mode, enabled, reason in (("audit", False, "channel_not_enabled"), ("on", True, "channel_not_executed")):
            statuses = []
            status, executed = ensure_we_mp_cleanup_audit_status(statuses, mode)
            self.assertFalse(executed)
            result = apply_we_mp_subscription_cleanup(
                {"other": {"id": "other", "site_id": "github"}},
                status,
                channel_enabled=enabled,
                channel_executed=executed,
                mode=mode,
                expected_bridge_commit="expected",
            )
            self.assertEqual(set(result), {"other"})
            self.assertIn(reason, status["subscription_cleanup"]["skip_reasons"])
            self.assertIs(statuses[0], status)
        statuses = []
        status, executed = ensure_we_mp_cleanup_audit_status(statuses, "off")
        self.assertIsNone(status)
        self.assertFalse(executed)
        self.assertEqual(statuses, [])

    def test_migration_only_adds_feed_id_and_never_deletes(self):
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "migrate_we_mp_archive_feed_ids.py"
        spec = importlib.util.spec_from_file_location("migrate_we_mp_archive_feed_ids", script_path)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        payload = {
            "generated_at": "unchanged",
            "total_items": 2,
            "items": [
                {"id": "w", "site_id": "we_mp_rss_jsonl", "source": "公众号", "title": "原题"},
                {"id": "o", "site_id": "github", "source": "repo", "extra": {"x": 1}},
            ],
        }
        migrated, report = module.plan_migration(payload, {"公众号": {"stable-id"}})
        self.assertEqual(migrated["items"][0]["we_mp_feed_id"], "stable-id")
        without_added = deepcopy(migrated)
        del without_added["items"][0]["we_mp_feed_id"]
        self.assertEqual(without_added, payload)
        self.assertEqual(report["deleted_records"], 0)
        self.assertEqual(report["coverage_after"], 1.0)

    def test_restore_cli_envelope_is_exact_and_mixed_failure_writes_nothing(self):
        script = Path(__file__).resolve().parent.parent / "scripts" / "restore_we_mp_cleanup.py"
        with self.subTest("successful apply"):
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                current_path = root / "current.json"
                before_path = root / "before.json"
                current = {"generated_at": "new", "total_items": 2, "items": [
                    {"id": "keep", "site_id": "opmlrss"}, {"id": "new", "site_id": "github"}
                ]}
                before = {"generated_at": "old", "total_items": 2, "items": [
                    {"id": "keep", "site_id": "opmlrss"}, {"id": "deleted", "site_id": "we_mp_rss_jsonl"}
                ]}
                current_path.write_text(json.dumps(current), encoding="utf-8")
                before_path.write_text(json.dumps(before), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(script), "--current", str(current_path), "--before", str(before_path), "--item-id", "deleted", "--apply"],
                    capture_output=True, text=True, encoding="utf-8", check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                after = json.loads(current_path.read_text(encoding="utf-8"))
                self.assertEqual(after["generated_at"], "new")
                self.assertEqual({item["id"] for item in after["items"]}, {"keep", "new", "deleted"})
                self.assertEqual(after["total_items"], 3)
        with self.subTest("mixed failure"):
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                current_path = root / "current.json"
                before_path = root / "before.json"
                current = {"generated_at": "new", "items": [{"id": "conflict", "site_id": "we_mp_rss_jsonl", "title": "current"}]}
                before = {"items": [{"id": "conflict", "site_id": "we_mp_rss_jsonl", "title": "old"}, {"id": "restorable", "site_id": "we_mp_rss_jsonl"}]}
                original = json.dumps(current)
                current_path.write_text(original, encoding="utf-8")
                before_path.write_text(json.dumps(before), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(script), "--current", str(current_path), "--before", str(before_path), "--item-id", "conflict", "--item-id", "restorable", "--apply"],
                    capture_output=True, text=True, encoding="utf-8", check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(current_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
