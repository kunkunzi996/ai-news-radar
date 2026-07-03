import unittest
from pathlib import Path

from scripts.local_server import (
    CONFIG_FILENAME,
    local_config_maintenance_issues,
    local_status_payload,
    maintenance_issues_from_status,
    refresh_command,
    validate_source_config,
)


class LocalServerTests(unittest.TestCase):
    def test_validate_source_config_accepts_dashboard_config(self):
        payload = {
            "version": "1.0",
            "sources": [
                {
                    "id": "wewe_rss_maobidao",
                    "name": "猫笔刀",
                    "type": "wewe_rss",
                    "enabled": True,
                    "locator": "MP_WXS_3198966508",
                }
            ],
        }

        self.assertIs(validate_source_config(payload), payload)

    def test_validate_source_config_requires_sources_array(self):
        with self.assertRaises(ValueError):
            validate_source_config({"version": "1.0"})

    def test_validate_source_config_requires_source_id_and_name(self):
        with self.assertRaises(ValueError):
            validate_source_config({"sources": [{"id": "", "name": "Missing id"}]})
        with self.assertRaises(ValueError):
            validate_source_config({"sources": [{"id": "missing_name", "name": ""}]})

    def test_refresh_command_uses_fixed_local_update_script(self):
        root = Path("E:/AI-news-reader/ai-news-radar-run")

        command = refresh_command(root)

        self.assertTrue(command[0].endswith("python.exe") or command[0].endswith("python"))
        self.assertEqual(command[1], str(root / "scripts" / "update_news.py"))
        self.assertIn("--source-config", command)
        self.assertIn(CONFIG_FILENAME, command)
        self.assertIn("--all-time", command)

    def test_maintenance_issues_warns_when_bilibili_cookie_is_missing(self):
        issues = maintenance_issues_from_status(
            {
                "sites": [
                    {
                        "site_id": "bilibili_dynamic",
                        "site_name": "Bilibili Dynamic",
                        "ok": True,
                        "item_count": 12,
                        "cookie_present": False,
                    }
                ]
            }
        )

        self.assertEqual(issues[0]["id"], "bilibili_cookie_missing")
        self.assertEqual(issues[0]["severity"], "warn")
        self.assertIn("cookie", issues[0]["title"].lower())

    def test_maintenance_issues_explains_missing_mediacrawler_jsonl(self):
        issues = maintenance_issues_from_status(
            {
                "sites": [
                    {
                        "site_id": "mediacrawler_xhs",
                        "site_name": "MediaCrawler Xiaohongshu",
                        "ok": False,
                        "item_count": 0,
                        "error": "mediacrawler_xhs_jsonl_not_found",
                    }
                ]
            }
        )

        self.assertEqual(issues[0]["severity"], "bad")
        self.assertIn("JSONL", issues[0]["action"])

    def test_wewe_feed_failure_is_not_reported_twice(self):
        issues = maintenance_issues_from_status(
            {
                "sites": [
                    {
                        "site_id": "wewe_rss",
                        "site_name": "WeWe RSS",
                        "ok": False,
                        "item_count": 0,
                        "error": "failed_wewe_rss_feeds:1",
                        "feeds": [
                            {
                                "id": "MP_TEST",
                                "name": "测试公众号",
                                "ok": False,
                                "error": "connection refused",
                            }
                        ],
                    }
                ]
            }
        )

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["id"], "wewe_feed_MP_TEST_failed")

    def test_local_status_payload_handles_missing_status_file(self):
        root = Path(self.create_temp_dir())
        (root / CONFIG_FILENAME).write_text(
            '{"version":"1.0","sources":[{"id":"rss_one","name":"RSS One","enabled":true}]}',
            encoding="utf-8",
        )

        payload = local_status_payload(root)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source_config"]["enabled_source_count"], 1)
        self.assertTrue(payload["source_status"]["needs_attention"])
        self.assertEqual(payload["source_status"]["maintenance_issues"][0]["id"], "source_status_missing")

    def test_local_config_issues_flag_missing_mediacrawler_jsonl(self):
        root = Path(self.create_temp_dir())
        config = {
            "sources": [
                {
                    "id": "mediacrawler_xhs_chenbaoyi",
                    "name": "陈抱一",
                    "type": "mediacrawler_jsonl",
                    "channel": "小红书",
                    "locator": "missing.jsonl",
                    "enabled": True,
                }
            ]
        }

        issues = local_config_maintenance_issues(root, config, probe_network=False)

        self.assertEqual(issues[0]["id"], "mediacrawler_xhs_jsonl_not_found")
        self.assertEqual(issues[0]["severity"], "bad")
        self.assertIn("JSONL", issues[0]["title"])

    def test_local_config_issues_warn_stale_mediacrawler_jsonl(self):
        from datetime import datetime, timedelta, timezone
        import os

        root = Path(self.create_temp_dir())
        jsonl = root / "creator_contents_2026-07-01.jsonl"
        jsonl.write_text('{"title":"hello"}\n', encoding="utf-8")
        now = datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc)
        old_timestamp = (now - timedelta(hours=40)).timestamp()
        os.utime(jsonl, (old_timestamp, old_timestamp))
        config = {
            "sources": [
                {
                    "id": "mediacrawler_douyin_simon",
                    "name": "Simon林",
                    "type": "mediacrawler_jsonl",
                    "channel": "抖音",
                    "locator": str(jsonl),
                    "enabled": True,
                }
            ]
        }

        issues = local_config_maintenance_issues(root, config, probe_network=False, now=now)

        self.assertEqual(issues[0]["id"], "mediacrawler_douyin_jsonl_stale")
        self.assertEqual(issues[0]["severity"], "warn")
        self.assertIn("40", issues[0]["detail"])

    def test_local_config_issues_flag_missing_wewe_feed_id_without_network(self):
        root = Path(self.create_temp_dir())
        config = {
            "sources": [
                {
                    "id": "wewe_rss_maobidao",
                    "name": "猫笔刀",
                    "type": "wewe_rss",
                    "locator": "",
                    "enabled": True,
                }
            ]
        }

        issues = local_config_maintenance_issues(root, config, probe_network=False)

        self.assertEqual(issues[0]["id"], "wewe_rss_feed_id_missing")
        self.assertEqual(issues[0]["source_id"], "wewe_rss")

    def create_temp_dir(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory(prefix="ai-news-radar-local-server-test-")
        self.addCleanup(tmp.cleanup)
        return tmp.name


if __name__ == "__main__":
    unittest.main()
