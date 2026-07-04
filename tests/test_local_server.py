import json
import unittest
from pathlib import Path

from scripts.local_server import (
    CONFIG_FILENAME,
    BILIBILI_DEFAULT_COOKIE_FILE,
    BILIBILI_PROFILE_DIR,
    bilibili_cookie_status,
    launch_bilibili_dedicated_browser,
    local_config_maintenance_issues,
    local_status_payload,
    maintenance_issues_from_status,
    mediacrawler_douyin_collector_status,
    mediacrawler_xhs_collector_status,
    normalize_collection_scope,
    perform_maintenance_action,
    read_wewe_rss_feeds,
    refresh_command,
    refresh_env,
    read_youtube_subscriptions,
    sync_bilibili_cookie,
    start_mediacrawler_douyin,
    start_mediacrawler_xhs,
    start_wewe_rss_sidecar,
    validate_source_config,
    write_youtube_subscriptions,
)


class LocalServerTests(unittest.TestCase):
    def test_read_wewe_rss_feeds_returns_sanitized_local_feed_list(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    [
                        {
                            "id": "MP_WXS_3198966508",
                            "name": "猫笔刀",
                            "intro": "记录与分享！",
                            "cover": "https://example.com/cover.jpg",
                            "updateTime": 1782915848,
                            "syncTime": 1783096795,
                        },
                        {"id": "MP_WXS_3198966508", "name": "重复项"},
                        {"name": "缺少 id"},
                    ],
                    ensure_ascii=False,
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            self.assertEqual(request.full_url, "http://127.0.0.1:4000/feeds")
            self.assertGreater(timeout, 0)
            return FakeResponse()

        original_urlopen = __import__("urllib.request").request.urlopen
        __import__("urllib.request").request.urlopen = fake_urlopen
        try:
            payload = read_wewe_rss_feeds("http://127.0.0.1:4000")
        finally:
            __import__("urllib.request").request.urlopen = original_urlopen

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["feed_count"], 1)
        self.assertEqual(
            payload["feeds"],
            [
                {
                    "id": "MP_WXS_3198966508",
                    "name": "猫笔刀",
                    "intro": "记录与分享！",
                    "updateTime": 1782915848,
                    "syncTime": 1783096795,
                }
            ],
        )

    def test_read_wewe_rss_feeds_rejects_non_local_base_url(self):
        payload = read_wewe_rss_feeds("https://example.com")

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "wewe_rss_base_url_not_local")
        self.assertEqual(payload["feeds"], [])

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

    def test_write_youtube_subscriptions_roundtrips_follow_opml(self):
        root = Path(self.create_temp_dir())

        saved = write_youtube_subscriptions(
            root,
            [
                {
                    "title": "AI Channel",
                    "channel_id": "UC_TEST",
                    "html_url": "https://www.youtube.com/@ai",
                }
            ],
        )
        loaded = read_youtube_subscriptions(root)

        self.assertEqual(saved[0]["xml_url"], "https://www.youtube.com/feeds/videos.xml?channel_id=UC_TEST")
        self.assertEqual(loaded, saved)
        self.assertTrue((root / "feeds" / "follow.opml").exists())

    def test_write_youtube_subscriptions_rejects_non_youtube_feed(self):
        root = Path(self.create_temp_dir())

        with self.assertRaises(ValueError):
            write_youtube_subscriptions(
                root,
                [
                    {
                        "title": "Bad Feed",
                        "xml_url": "https://example.com/feed.xml",
                    }
                ],
            )

    def test_refresh_command_uses_fixed_local_update_script(self):
        root = Path("E:/AI-news-reader/ai-news-radar-run")

        command = refresh_command(root)

        self.assertTrue(command[0].endswith("python.exe") or command[0].endswith("python"))
        self.assertEqual(command[1], str(root / "scripts" / "update_news.py"))
        self.assertIn("--source-config", command)
        self.assertIn(CONFIG_FILENAME, command)
        self.assertIn("--all-time", command)
        self.assertIn("--collect-window-hours", command)
        self.assertEqual(command[command.index("--collect-window-hours") + 1], "24")

    def test_refresh_command_can_request_all_time_collection(self):
        root = Path("E:/AI-news-reader/ai-news-radar-run")

        command = refresh_command(root, "all")

        self.assertIn("--all-time", command)
        self.assertNotIn("--collect-window-hours", command)

    def test_collection_scope_is_whitelisted(self):
        self.assertEqual(normalize_collection_scope("24h"), "24h")
        self.assertEqual(normalize_collection_scope("all_time"), "all")
        with self.assertRaises(ValueError):
            normalize_collection_scope("--source-scope all_sources")

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
        action_ids = [action["id"] for action in issues[0]["fix_actions"]]
        self.assertIn("open_bilibili_login", action_ids)
        self.assertIn("sync_bilibili_cookie", action_ids)
        self.assertIn("open_bilibili_cookie_folder", action_ids)

    def test_bilibili_cookie_status_uses_default_local_file(self):
        root = Path(self.create_temp_dir())
        cookie_file = root / BILIBILI_DEFAULT_COOKIE_FILE
        cookie_file.parent.mkdir(parents=True)
        cookie_file.write_text("SESSDATA=fake\n", encoding="utf-8")

        status = bilibili_cookie_status(root)

        self.assertTrue(status["configured"])
        self.assertTrue(status["cookie_file_exists"])
        self.assertEqual(Path(status["recommended_cookie_file"]), cookie_file)

    def test_refresh_env_uses_default_bilibili_cookie_file_when_present(self):
        import os

        root = Path(self.create_temp_dir())
        cookie_file = root / BILIBILI_DEFAULT_COOKIE_FILE
        cookie_file.parent.mkdir(parents=True)
        cookie_file.write_text("SESSDATA=fake\n", encoding="utf-8")
        old_cookie_file = os.environ.pop("BILIBILI_COOKIE_FILE", None)
        old_dynamic_cookie_file = os.environ.pop("BILIBILI_DYNAMIC_COOKIE_FILE", None)
        old_cookie = os.environ.pop("BILIBILI_COOKIE", None)
        old_dynamic_cookie = os.environ.pop("BILIBILI_DYNAMIC_COOKIE", None)
        try:
            env = refresh_env(root)
        finally:
            if old_cookie_file is not None:
                os.environ["BILIBILI_COOKIE_FILE"] = old_cookie_file
            if old_dynamic_cookie_file is not None:
                os.environ["BILIBILI_DYNAMIC_COOKIE_FILE"] = old_dynamic_cookie_file
            if old_cookie is not None:
                os.environ["BILIBILI_COOKIE"] = old_cookie
            if old_dynamic_cookie is not None:
                os.environ["BILIBILI_DYNAMIC_COOKIE"] = old_dynamic_cookie

        self.assertEqual(Path(env["BILIBILI_COOKIE_FILE"]), cookie_file)

    def test_launch_bilibili_dedicated_browser_dry_run_uses_isolated_profile(self):
        root = Path(self.create_temp_dir())

        result = launch_bilibili_dedicated_browser(root, execute=False)

        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertEqual(result["action_id"], "open_bilibili_login")
        self.assertIn("--remote-debugging-address=127.0.0.1", result["command"])
        self.assertIn(f"--user-data-dir={root / BILIBILI_PROFILE_DIR}", result["command"])
        self.assertIn("https://passport.bilibili.com/login", result["command"])

    def test_sync_bilibili_cookie_reports_missing_login_window(self):
        from unittest.mock import patch

        root = Path(self.create_temp_dir())

        with patch("scripts.local_server.active_bilibili_cdp_port", return_value=None):
            result = sync_bilibili_cookie(root, execute=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "bilibili_login_window_not_running")

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
        action_ids = {action["id"] for action in issues[0]["fix_actions"]}
        self.assertIn("start_wewe_rss_sidecar", action_ids)
        self.assertIn("open_wewe_rss_dashboard", action_ids)

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
        action_ids = {action["id"] for action in issues[0]["fix_actions"]}
        self.assertIn("open_mediacrawler_xhs_platform", action_ids)
        self.assertIn("start_mediacrawler_xhs", action_ids)

    def test_local_config_issues_homepage_url_checks_default_mediacrawler_dir(self):
        import os

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        crawler_root = root.parent / "MediaCrawler-local-test"
        old_dir = os.environ.get("MEDIACRAWLER_LOCAL_DIR")
        os.environ["MEDIACRAWLER_LOCAL_DIR"] = str(crawler_root)
        config = {
            "sources": [
                {
                    "id": "mediacrawler_xhs_chenbaoyi",
                    "name": "陈抱一",
                    "type": "mediacrawler_jsonl",
                    "channel": "小红书",
                    "locator": "https://www.xiaohongshu.com/user/profile/5e4027000000000001005eb8",
                    "enabled": True,
                }
            ]
        }
        try:
            issues = local_config_maintenance_issues(root, config, probe_network=False)
        finally:
            if old_dir is None:
                os.environ.pop("MEDIACRAWLER_LOCAL_DIR", None)
            else:
                os.environ["MEDIACRAWLER_LOCAL_DIR"] = old_dir

        self.assertEqual(issues[0]["id"], "mediacrawler_xhs_jsonl_not_found")
        self.assertIn("主页链接已保存", issues[0]["detail"])
        action_ids = {action["id"] for action in issues[0]["fix_actions"]}
        self.assertIn("start_mediacrawler_xhs", action_ids)
        self.assertIn("open_mediacrawler_xhs_platform", action_ids)

    def test_local_config_issues_homepage_url_passes_when_default_jsonl_exists(self):
        import os
        from datetime import datetime, timezone

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        crawler_root = root.parent / "MediaCrawler-local-test"
        jsonl_dir = crawler_root / "output" / "xhs" / "jsonl"
        jsonl_dir.mkdir(parents=True)
        (jsonl_dir / "creator_contents_2026-07-04.jsonl").write_text('{"title":"one"}\n', encoding="utf-8")
        old_dir = os.environ.get("MEDIACRAWLER_LOCAL_DIR")
        os.environ["MEDIACRAWLER_LOCAL_DIR"] = str(crawler_root)
        config = {
            "sources": [
                {
                    "id": "mediacrawler_xhs_chenbaoyi",
                    "name": "陈抱一",
                    "type": "mediacrawler_jsonl",
                    "channel": "小红书",
                    "locator": "https://www.xiaohongshu.com/user/profile/5e4027000000000001005eb8",
                    "enabled": True,
                }
            ]
        }
        try:
            issues = local_config_maintenance_issues(
                root,
                config,
                probe_network=False,
                now=datetime(2026, 7, 4, 9, 0, tzinfo=timezone.utc),
            )
        finally:
            if old_dir is None:
                os.environ.pop("MEDIACRAWLER_LOCAL_DIR", None)
            else:
                os.environ["MEDIACRAWLER_LOCAL_DIR"] = old_dir

        self.assertEqual(issues, [])

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
        action_ids = {action["id"] for action in issues[0]["fix_actions"]}
        self.assertIn("open_mediacrawler_douyin_jsonl_folder", action_ids)
        self.assertIn("open_mediacrawler_douyin_platform", action_ids)
        self.assertIn("start_mediacrawler_douyin", action_ids)

    def test_local_config_uses_newer_mediacrawler_jsonl_sibling(self):
        from datetime import datetime, timedelta, timezone
        import os

        root = Path(self.create_temp_dir())
        old_jsonl = root / "creator_contents_2026-07-01.jsonl"
        old_jsonl.write_text('{"title":"old"}\n', encoding="utf-8")
        new_jsonl = root / "creator_contents_2026-07-03.jsonl"
        new_jsonl.write_text('{"title":"new"}\n', encoding="utf-8")
        now = datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc)
        os.utime(old_jsonl, ((now - timedelta(hours=40)).timestamp(),) * 2)
        os.utime(new_jsonl, ((now - timedelta(hours=1)).timestamp(),) * 2)
        config = {
            "sources": [
                {
                    "id": "mediacrawler_douyin_simon",
                    "name": "Simon林",
                    "type": "mediacrawler_jsonl",
                    "channel": "抖音",
                    "locator": str(old_jsonl),
                    "enabled": True,
                }
            ]
        }

        issues = local_config_maintenance_issues(root, config, probe_network=False, now=now)

        self.assertEqual(issues, [])

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
        self.assertEqual(issues[0]["fix_actions"][0]["id"], "open_wewe_rss_dashboard")

    def test_local_config_issues_does_not_treat_wechat_backup_as_wewe_feed(self):
        root = Path(self.create_temp_dir())
        config = {
            "sources": [
                {
                    "id": "maobidao_wudaolu_backup",
                    "name": "猫笔刀备份源",
                    "type": "api",
                    "channel": "微信公众号备用",
                    "locator": "https://wudaolu.com/c/dav/7.json",
                    "enabled": True,
                }
            ]
        }

        issues = local_config_maintenance_issues(root, config, probe_network=False)

        self.assertEqual(issues, [])

    def test_start_wewe_rss_sidecar_dry_run_uses_fixed_local_dist(self):
        import os

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        sidecar_server = root.parent / "wewe-rss-sidecar" / "apps" / "server"
        sidecar_dist = sidecar_server / "dist"
        sidecar_dist.mkdir(parents=True)
        (sidecar_dist / "main.js").write_text("console.log('fake')\n", encoding="utf-8")

        old_base_url = os.environ.get("WEWE_RSS_BASE_URL")
        os.environ["WEWE_RSS_BASE_URL"] = "http://127.0.0.1:49999"
        try:
            result = start_wewe_rss_sidecar(root, execute=False)
        finally:
            if old_base_url is None:
                os.environ.pop("WEWE_RSS_BASE_URL", None)
            else:
                os.environ["WEWE_RSS_BASE_URL"] = old_base_url

        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertEqual(Path(result["cwd"]), sidecar_server)
        self.assertEqual(Path(result["command"][1]), sidecar_dist / "main.js")

    def test_start_mediacrawler_douyin_dry_run_uses_fixed_local_command(self):
        import os

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        script_dir = root / "scripts"
        script_dir.mkdir(parents=True)
        runner = script_dir / "run_mediacrawler_douyin.py"
        runner.write_text("print('runner')\n", encoding="utf-8")
        crawler_root = root.parent / "MediaCrawler-local-test"
        crawler_root.mkdir(parents=True)
        (crawler_root / "main.py").write_text("print('fake')\n", encoding="utf-8")
        python_dir = crawler_root / "venv" / "Scripts"
        python_dir.mkdir(parents=True)
        python_exe = python_dir / "python.exe"
        python_exe.write_text("", encoding="utf-8")

        old_dir = os.environ.get("MEDIACRAWLER_LOCAL_DIR")
        os.environ["MEDIACRAWLER_LOCAL_DIR"] = str(crawler_root)
        try:
            result = start_mediacrawler_douyin(root, execute=False)
        finally:
            if old_dir is None:
                os.environ.pop("MEDIACRAWLER_LOCAL_DIR", None)
            else:
                os.environ["MEDIACRAWLER_LOCAL_DIR"] = old_dir

        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertEqual(Path(result["cwd"]), crawler_root)
        self.assertEqual(Path(result["command"][0]), python_exe)
        self.assertEqual(Path(result["command"][1]), runner)
        self.assertIn("--crawler-root", result["command"])
        self.assertIn(str(crawler_root), result["command"])
        self.assertNotIn("url", result)

    def test_start_mediacrawler_douyin_dry_run_uses_homepage_url_from_source_config(self):
        import os

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        script_dir = root / "scripts"
        script_dir.mkdir(parents=True)
        runner = script_dir / "run_mediacrawler_douyin.py"
        runner.write_text("print('runner')\n", encoding="utf-8")
        crawler_root = root.parent / "MediaCrawler-local-test"
        crawler_root.mkdir(parents=True)
        (crawler_root / "main.py").write_text("print('fake')\n", encoding="utf-8")
        python_dir = crawler_root / "venv" / "Scripts"
        python_dir.mkdir(parents=True)
        python_exe = python_dir / "python.exe"
        python_exe.write_text("", encoding="utf-8")
        homepage_url = "https://www.douyin.com/user/MS4wLjABAAAAOzTvIhQXaHWi6jT_P5rG5xEWpWPjufiK"
        (root / CONFIG_FILENAME).write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "sources": [
                        {
                            "id": "mediacrawler_douyin_jennie",
                            "name": "珍妮丁丁说AI",
                            "type": "mediacrawler_jsonl",
                            "channel": "抖音",
                            "locator": homepage_url,
                            "enabled": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        old_dir = os.environ.get("MEDIACRAWLER_LOCAL_DIR")
        os.environ["MEDIACRAWLER_LOCAL_DIR"] = str(crawler_root)
        try:
            result = start_mediacrawler_douyin(root, execute=False)
        finally:
            if old_dir is None:
                os.environ.pop("MEDIACRAWLER_LOCAL_DIR", None)
            else:
                os.environ["MEDIACRAWLER_LOCAL_DIR"] = old_dir

        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertEqual(Path(result["command"][0]), python_exe)
        self.assertIn("--creator-id", result["command"])
        self.assertIn(homepage_url, result["command"])

    def test_start_mediacrawler_xhs_dry_run_uses_fixed_local_command_and_creator_from_jsonl(self):
        import os

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        script_dir = root / "scripts"
        script_dir.mkdir(parents=True)
        runner = script_dir / "run_mediacrawler_douyin.py"
        runner.write_text("print('runner')\n", encoding="utf-8")
        crawler_root = root.parent / "MediaCrawler-local-test"
        crawler_root.mkdir(parents=True)
        (crawler_root / "main.py").write_text("print('fake')\n", encoding="utf-8")
        jsonl_dir = crawler_root / "output" / "xhs" / "jsonl"
        jsonl_dir.mkdir(parents=True)
        jsonl = jsonl_dir / "creator_contents_2026-07-03.jsonl"
        jsonl.write_text('{"user_id":"5e4027000000000001005eb8","title":"one"}\n', encoding="utf-8")
        python_dir = crawler_root / "venv" / "Scripts"
        python_dir.mkdir(parents=True)
        python_exe = python_dir / "python.exe"
        python_exe.write_text("", encoding="utf-8")

        old_dir = os.environ.get("MEDIACRAWLER_LOCAL_DIR")
        os.environ["MEDIACRAWLER_LOCAL_DIR"] = str(crawler_root)
        try:
            result = start_mediacrawler_xhs(root, execute=False)
        finally:
            if old_dir is None:
                os.environ.pop("MEDIACRAWLER_LOCAL_DIR", None)
            else:
                os.environ["MEDIACRAWLER_LOCAL_DIR"] = old_dir

        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertEqual(Path(result["cwd"]), crawler_root)
        self.assertEqual(Path(result["command"][0]), python_exe)
        self.assertEqual(Path(result["command"][1]), runner)
        self.assertIn("--platform", result["command"])
        self.assertIn("xhs", result["command"])
        self.assertIn("--creator-id", result["command"])
        self.assertIn("https://www.xiaohongshu.com/user/profile/5e4027000000000001005eb8", result["command"])

    def test_start_mediacrawler_xhs_dry_run_uses_homepage_url_from_source_config(self):
        import os

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        script_dir = root / "scripts"
        script_dir.mkdir(parents=True)
        runner = script_dir / "run_mediacrawler_douyin.py"
        runner.write_text("print('runner')\n", encoding="utf-8")
        crawler_root = root.parent / "MediaCrawler-local-test"
        crawler_root.mkdir(parents=True)
        (crawler_root / "main.py").write_text("print('fake')\n", encoding="utf-8")
        python_dir = crawler_root / "venv" / "Scripts"
        python_dir.mkdir(parents=True)
        python_exe = python_dir / "python.exe"
        python_exe.write_text("", encoding="utf-8")
        homepage_url = "https://www.xiaohongshu.com/user/profile/5e4027000000000001005eb8"
        (root / CONFIG_FILENAME).write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "sources": [
                        {
                            "id": "mediacrawler_xhs_chenbaoyi",
                            "name": "陈抱一",
                            "type": "mediacrawler_jsonl",
                            "channel": "小红书",
                            "locator": homepage_url,
                            "enabled": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        old_dir = os.environ.get("MEDIACRAWLER_LOCAL_DIR")
        os.environ["MEDIACRAWLER_LOCAL_DIR"] = str(crawler_root)
        try:
            result = start_mediacrawler_xhs(root, execute=False)
        finally:
            if old_dir is None:
                os.environ.pop("MEDIACRAWLER_LOCAL_DIR", None)
            else:
                os.environ["MEDIACRAWLER_LOCAL_DIR"] = old_dir

        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertEqual(Path(result["command"][0]), python_exe)
        self.assertIn("--creator-id", result["command"])
        self.assertIn(homepage_url, result["command"])

    def test_mediacrawler_douyin_collector_status_explains_finished_run(self):
        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        crawler_root = root.parent / "MediaCrawler-local-test"
        output_dir = crawler_root / "output" / "douyin" / "jsonl"
        output_dir.mkdir(parents=True)
        jsonl = output_dir / "creator_contents_2026-07-03.jsonl"
        jsonl.write_text('{"title":"one"}\n{"title":"two"}\n', encoding="utf-8")
        (crawler_root / "mediacrawler-douyin.err.log").write_text(
            "2026-07-03 16:11:34 MediaCrawler INFO (core.py:125) - [DouYinCrawler.start] Douyin Crawler finished ...\n",
            encoding="utf-8",
        )

        status = mediacrawler_douyin_collector_status(root)

        self.assertEqual(status["phase"], "completed")
        self.assertTrue(status["can_close_browser"])
        self.assertEqual(status["item_count"], 2)
        self.assertEqual(status["last_log"], "采集完成")
        self.assertIn("读取结果", status["next_action"])

    def test_mediacrawler_xhs_collector_status_explains_finished_run(self):
        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        crawler_root = root.parent / "MediaCrawler-local-test"
        output_dir = crawler_root / "output" / "xhs" / "jsonl"
        output_dir.mkdir(parents=True)
        jsonl = output_dir / "creator_contents_2026-07-03.jsonl"
        jsonl.write_text('{"title":"one"}\n{"title":"two"}\n{"title":"three"}\n', encoding="utf-8")
        (crawler_root / "mediacrawler-xhs.err.log").write_text(
            "2026-07-03 16:11:34 MediaCrawler INFO (core.py:127) - [XiaoHongShuCrawler.start] Xhs Crawler finished ...\n",
            encoding="utf-8",
        )

        status = mediacrawler_xhs_collector_status(root)

        self.assertEqual(status["phase"], "completed")
        self.assertEqual(status["platform_name"], "小红书")
        self.assertTrue(status["can_close_browser"])
        self.assertEqual(status["item_count"], 3)
        self.assertEqual(status["last_log"], "采集完成")
        self.assertIn("读取结果", status["next_action"])

    def test_mediacrawler_xhs_collector_status_marks_finished_when_output_is_newer_than_pid(self):
        import os
        import time

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        crawler_root = root.parent / "MediaCrawler-local-test"
        output_dir = crawler_root / "output" / "xhs" / "jsonl"
        output_dir.mkdir(parents=True)
        pid_file = crawler_root / "mediacrawler-xhs.pid"
        pid_file.write_text("999999", encoding="utf-8")
        jsonl = output_dir / "creator_contents_2026-07-03.jsonl"
        jsonl.write_text('{"title":"one"}\n{"title":"two"}\n', encoding="utf-8")
        (crawler_root / "mediacrawler-xhs.err.log").write_text(
            "2026-07-03 21:54:52 MediaCrawler INFO (__init__.py:131) - [store.xhs.update_xhs_note] xhs note: {'title': '正在写入'}\n",
            encoding="utf-8",
        )
        now = time.time()
        os.utime(pid_file, (now - 30, now - 30))
        os.utime(jsonl, (now, now))

        status = mediacrawler_xhs_collector_status(root)

        self.assertEqual(status["phase"], "completed")
        self.assertTrue(status["completed"])
        self.assertEqual(status["item_count"], 2)
        self.assertIn("读取结果", status["next_action"])

    def test_perform_maintenance_action_dry_run_opens_configured_jsonl_folder(self):
        import os
        import time

        root = Path(self.create_temp_dir())
        jsonl = root / "creator_contents_2026-07-01.jsonl"
        jsonl.write_text('{"title":"hello"}\n', encoding="utf-8")
        old_timestamp = time.time() - 40 * 3600
        os.utime(jsonl, (old_timestamp, old_timestamp))
        (root / CONFIG_FILENAME).write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "sources": [
                        {
                            "id": "mediacrawler_xhs_chenbaoyi",
                            "name": "陈抱一",
                            "type": "mediacrawler_jsonl",
                            "channel": "小红书",
                            "locator": str(jsonl),
                            "enabled": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = perform_maintenance_action(root, "open_mediacrawler_xhs_jsonl_folder", execute=False)

        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "open_path")
        self.assertEqual(Path(result["opened_path"]), root)

    def test_perform_maintenance_action_dry_run_creates_bilibili_cookie_folder(self):
        root = Path(self.create_temp_dir())
        (root / CONFIG_FILENAME).write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "sources": [
                        {
                            "id": "bilibili_dynamic_sources",
                            "name": "B站动态",
                            "type": "bilibili_dynamic",
                            "enabled": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        data_dir = root / "data"
        data_dir.mkdir()
        (data_dir / "source-status.json").write_text(
            json.dumps(
                {
                    "sites": [
                        {
                            "site_id": "bilibili_dynamic",
                            "site_name": "Bilibili Dynamic",
                            "ok": True,
                            "item_count": 2,
                            "cookie_present": False,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = perform_maintenance_action(root, "open_bilibili_cookie_folder", execute=False)

        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "open_path")
        self.assertEqual(Path(result["opened_path"]), root / BILIBILI_DEFAULT_COOKIE_FILE.parent)
        self.assertEqual(Path(result["recommended_cookie_file"]), root / BILIBILI_DEFAULT_COOKIE_FILE)

    def test_perform_maintenance_action_can_start_mediacrawler_without_current_issue(self):
        import os

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        script_dir = root / "scripts"
        script_dir.mkdir(parents=True)
        runner = script_dir / "run_mediacrawler_douyin.py"
        runner.write_text("print('runner')\n", encoding="utf-8")
        crawler_root = root.parent / "MediaCrawler-local-test"
        crawler_root.mkdir(parents=True)
        (crawler_root / "main.py").write_text("print('fake')\n", encoding="utf-8")
        python_dir = crawler_root / "venv" / "Scripts"
        python_dir.mkdir(parents=True)
        python_exe = python_dir / "python.exe"
        python_exe.write_text("", encoding="utf-8")
        homepage_url = "https://www.douyin.com/user/MS4wLjABAAAAOzTvIhQXaHWi6jT_P5rG5xEWpWPjufiK"
        (root / CONFIG_FILENAME).write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "sources": [
                        {
                            "id": "mediacrawler_douyin_jennie",
                            "name": "珍妮丁丁说AI",
                            "type": "mediacrawler_jsonl",
                            "channel": "抖音",
                            "locator": homepage_url,
                            "enabled": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        old_dir = os.environ.get("MEDIACRAWLER_LOCAL_DIR")
        os.environ["MEDIACRAWLER_LOCAL_DIR"] = str(crawler_root)
        try:
            result = perform_maintenance_action(root, "start_mediacrawler_douyin", execute=False)
        finally:
            if old_dir is None:
                os.environ.pop("MEDIACRAWLER_LOCAL_DIR", None)
            else:
                os.environ["MEDIACRAWLER_LOCAL_DIR"] = old_dir

        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertEqual(result["action_id"], "start_mediacrawler_douyin")
        self.assertEqual(Path(result["command"][0]), python_exe)
        self.assertIn("--creator-id", result["command"])
        self.assertIn(homepage_url, result["command"])

    def create_temp_dir(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory(prefix="ai-news-radar-local-server-test-")
        self.addCleanup(tmp.cleanup)
        return tmp.name


if __name__ == "__main__":
    unittest.main()
