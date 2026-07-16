import http.client
import json
import subprocess
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from scripts.local_server import (
    CONFIG_FILENAME,
    BILIBILI_DEFAULT_COOKIE_FILE,
    BILIBILI_PROFILE_DIR,
    LocalRadarHandler,
    PURGE_TRACKED_SITE_IDS,
    alive_source_names_by_site,
    bilibili_cookie_status,
    collect_window_hours_for_scope,
    flush_pending_purge,
    is_item_orphaned,
    launch_bilibili_dedicated_browser,
    last_collection_time,
    local_config_maintenance_issues,
    local_status_payload,
    maintenance_issues_from_status,
    mediacrawler_douyin_collector_status,
    mediacrawler_xhs_collector_status,
    normalize_collection_scope,
    perform_maintenance_action,
    purge_deleted_source_data,
    queue_pending_purge,
    read_online_source_config,
    read_wewe_rss_feeds,
    refresh_command,
    refresh_env,
    restart_command,
    run_refresh_background,
    save_online_source_config,
    save_and_sync_online_source_config,
    read_youtube_subscriptions,
    resolve_collect_window_hours,
    sync_bilibili_cookie,
    start_mediacrawler_douyin,
    start_mediacrawler_xhs,
    start_wewe_rss_sidecar,
    start_we_mp_rss_sidecar,
    sync_online_source_config,
    refresh_step_plan,
    validate_source_config,
    write_online_source_config,
    write_youtube_subscriptions,
)
from scripts.radar.server.subscriptions_store import deleted_source_names_by_site
from scripts.radar.server import github_stars, online_sources


class LocalServerTests(unittest.TestCase):
    def test_restart_command_reuses_current_python_and_args(self):
        import sys

        command = restart_command()

        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1:], sys.argv)

    def test_mediacrawler_runner_protects_local_cdp_from_socks_proxy(self):
        import os

        from scripts.run_mediacrawler_douyin import protect_local_cdp_from_proxy

        old_values = {
            key: os.environ.get(key)
            for key in ("ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy")
        }
        os.environ["ALL_PROXY"] = "socks5://127.0.0.1:4780"
        os.environ.pop("all_proxy", None)
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"
        os.environ.pop("no_proxy", None)
        try:
            protect_local_cdp_from_proxy()
            self.assertNotIn("ALL_PROXY", os.environ)
            self.assertIn("localhost", os.environ["NO_PROXY"])
            self.assertIn("127.0.0.1", os.environ["NO_PROXY"])
            self.assertIn("::1", os.environ["NO_PROXY"])
            self.assertIn("::1", os.environ["no_proxy"])
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

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

    def test_alive_source_names_by_site_splits_bilibili_members(self):
        config = {
            "sources": [
                {
                    "id": "bilibili_dynamic_sources",
                    "name": "B站动态",
                    "type": "bilibili_dynamic",
                    "target": "张三,李四,",
                }
            ]
        }

        alive = alive_source_names_by_site(config)

        self.assertEqual(set(alive.keys()), set(PURGE_TRACKED_SITE_IDS))
        self.assertEqual(alive["bilibili_dynamic"], {"张三", "李四"})

    def test_alive_source_names_by_site_protects_renamed_source(self):
        old_config = {
            "sources": [
                {"id": "wewe_rss_maobidao", "type": "wewe_rss", "name": "猫笔刀", "target": "猫笔刀"}
            ]
        }
        new_config = {
            "sources": [
                {"id": "wewe_rss_maobidao", "type": "wewe_rss", "name": "猫笔刀公众号", "target": "猫笔刀公众号"}
            ]
        }

        alive = alive_source_names_by_site(new_config, old_config)

        self.assertEqual(alive["wewe_rss"], {"猫笔刀公众号", "猫笔刀"})

    def test_alive_source_names_by_site_does_not_protect_deleted_source(self):
        old_config = {
            "sources": [
                {"id": "wewe_rss_maobidao", "type": "wewe_rss", "name": "猫笔刀", "target": "猫笔刀"}
            ]
        }
        new_config = {"sources": []}

        alive = alive_source_names_by_site(new_config, old_config)

        self.assertNotIn("猫笔刀", alive["wewe_rss"])

    def test_disabled_source_on_both_sides_is_not_treated_as_deleted(self):
        disabled = {
            "id": "douyin_simon",
            "type": "mediacrawler_douyin",
            "name": "Simon林",
            "target": "Simon林",
            "enabled": False,
        }

        deleted = deleted_source_names_by_site(
            {"sources": [disabled.copy()]},
            {"sources": [disabled.copy()]},
        )

        self.assertEqual(deleted, {})

    def test_disabling_enabled_source_is_treated_as_deleted(self):
        enabled = {
            "id": "bilibili_zhangsan",
            "type": "bilibili_dynamic",
            "name": "张三",
            "target": "张三",
            "locator": "111",
            "enabled": True,
        }
        disabled = {**enabled, "enabled": False}

        deleted = deleted_source_names_by_site(
            {"sources": [disabled]},
            {"sources": [enabled]},
        )

        self.assertEqual(deleted, {"bilibili_dynamic": {"张三"}})

    def test_rss_source_uses_name_as_opmlrss_identity(self):
        config = {
            "sources": [
                {
                    "id": "rss_google_ai",
                    "type": "rss",
                    "name": "Google AI Blog",
                    "target": "https://blog.google/technology/ai/rss/",
                    "enabled": True,
                },
                {
                    "id": "online_rss_bundle",
                    "type": "opmlrss",
                    "name": "线上 RSS/YouTube 订阅包",
                    "enabled": True,
                },
            ]
        }

        alive = alive_source_names_by_site(config)

        self.assertEqual(alive["opmlrss"], {"Google AI Blog"})

    def test_deleted_rss_source_is_purged_but_renamed_source_is_kept(self):
        old_config = {
            "sources": [
                {"id": "rss_keep", "type": "rss", "name": "旧名字", "enabled": True},
                {"id": "rss_remove", "type": "rss", "name": "Wired AI", "enabled": True},
            ]
        }
        new_config = {
            "sources": [
                {"id": "rss_keep", "type": "rss", "name": "新名字", "enabled": True},
            ]
        }

        alive = alive_source_names_by_site(new_config, old_config)
        deleted = deleted_source_names_by_site(new_config, old_config)

        self.assertEqual(alive["opmlrss"], {"旧名字", "新名字"})
        self.assertEqual(deleted, {"opmlrss": {"Wired AI"}})

    def test_alive_source_names_by_site_protects_renamed_bilibili_member(self):
        old_config = {
            "sources": [
                {
                    "id": "bilibili_dynamic_sources",
                    "type": "bilibili_dynamic",
                    "target": "张三,李四",
                    "locator": "111,222",
                }
            ]
        }
        new_config = {
            "sources": [
                {
                    "id": "bilibili_dynamic_sources",
                    "type": "bilibili_dynamic",
                    "target": "张三,李四改名",
                    "locator": "111,222",
                }
            ]
        }

        alive = alive_source_names_by_site(new_config, old_config)

        self.assertEqual(alive["bilibili_dynamic"], {"张三", "李四", "李四改名"})

    def test_alive_source_names_by_site_does_not_protect_removed_bilibili_member(self):
        old_config = {
            "sources": [
                {
                    "id": "bilibili_dynamic_sources",
                    "type": "bilibili_dynamic",
                    "target": "张三,李四",
                    "locator": "111,222",
                }
            ]
        }
        new_config = {
            "sources": [
                {
                    "id": "bilibili_dynamic_sources",
                    "type": "bilibili_dynamic",
                    "target": "张三",
                    "locator": "111",
                }
            ]
        }

        alive = alive_source_names_by_site(new_config, old_config)

        self.assertEqual(alive["bilibili_dynamic"], {"张三"})

    def test_is_item_orphaned_only_applies_to_tracked_site_ids(self):
        alive = {"bilibili_dynamic": {"张三"}}

        self.assertTrue(is_item_orphaned({"site_id": "bilibili_dynamic", "source": "李四"}, alive))
        self.assertFalse(is_item_orphaned({"site_id": "bilibili_dynamic", "source": "张三"}, alive))
        self.assertFalse(is_item_orphaned({"site_id": "hackernews", "source": "李四"}, alive))
        self.assertFalse(is_item_orphaned({"site_id": "opmlrss", "source": "李四"}, alive))

    def test_purge_deleted_source_data_rewrites_display_payloads(self):
        root = Path(self.create_temp_dir())
        data_dir = root / "data"
        data_dir.mkdir()
        kept = {"site_id": "bilibili_dynamic", "source": "张三", "title": "保留"}
        deleted = {"site_id": "bilibili_dynamic", "source": "李四", "title": "删除"}
        unrelated = {"site_id": "hackernews", "source": "李四", "title": "无关"}
        config = {
            "sources": [
                {
                    "id": "bilibili_dynamic_sources",
                    "name": "B站动态",
                    "type": "bilibili_dynamic",
                    "target": "张三",
                }
            ]
        }
        (data_dir / "archive.json").write_text(
            json.dumps({"items": [kept, deleted, unrelated], "total_items": 3}, ensure_ascii=False),
            encoding="utf-8",
        )
        (data_dir / "latest-24h.json").write_text(
            json.dumps(
                {
                    "items": [kept, deleted, unrelated],
                    "items_ai": [deleted],
                    "creator_items_ai": [kept, deleted],
                    "creator_items_all": [unrelated],
                    "site_stats": {"bilibili_dynamic": 2},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (data_dir / "stories-merged.json").write_text(
            json.dumps(
                {
                    "stories": [
                        {"title": "保留故事", "items": [kept]},
                        {"title": "删除故事", "items": [deleted]},
                        {"title": "无关故事", "items": [unrelated]},
                    ],
                    "total_stories": 3,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        summary = purge_deleted_source_data(root, config)

        archive = json.loads((data_dir / "archive.json").read_text(encoding="utf-8"))
        latest = json.loads((data_dir / "latest-24h.json").read_text(encoding="utf-8"))
        stories = json.loads((data_dir / "stories-merged.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["archive.json"], 1)
        self.assertEqual(summary["latest-24h.json"], 3)
        self.assertEqual(summary["stories-merged.json"], 1)
        self.assertEqual(archive["total_items"], 2)
        self.assertEqual([item["title"] for item in archive["items"]], ["保留", "无关"])
        self.assertEqual([item["title"] for item in latest["items"]], ["保留", "无关"])
        self.assertEqual([story["title"] for story in stories["stories"]], ["保留故事", "无关故事"])
        self.assertEqual(stories["total_stories"], 2)

    def test_purge_deleted_source_data_keeps_renamed_source_history(self):
        root = Path(self.create_temp_dir())
        data_dir = root / "data"
        data_dir.mkdir()
        path = data_dir / "archive.json"
        path.write_text(
            json.dumps(
                {
                    "items": [{"site_id": "wewe_rss", "source": "猫笔刀", "title": "旧名历史"}],
                    "total_items": 1,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        old_config = {
            "sources": [
                {"id": "wewe_rss_maobidao", "type": "wewe_rss", "name": "猫笔刀", "target": "猫笔刀"}
            ]
        }
        new_config = {
            "sources": [
                {"id": "wewe_rss_maobidao", "type": "wewe_rss", "name": "猫笔刀公众号", "target": "猫笔刀公众号"}
            ]
        }

        summary = purge_deleted_source_data(root, new_config, previous_config=old_config)

        archive = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(summary["archive.json"], 0)
        self.assertEqual(archive["items"][0]["title"], "旧名历史")
        self.assertEqual(archive["total_items"], 1)

    def test_purge_deleted_source_data_removes_only_deleted_rss_source(self):
        root = Path(self.create_temp_dir())
        data_dir = root / "data"
        data_dir.mkdir()
        path = data_dir / "archive.json"
        path.write_text(
            json.dumps(
                {
                    "items": [
                        {"site_id": "opmlrss", "source": "Wired AI", "title": "删除"},
                        {"site_id": "opmlrss", "source": "OpenAI News", "title": "保留 RSS"},
                        {"site_id": "we_mp_rss_jsonl", "source": "数字生命卡兹克", "title": "保留公众号"},
                    ],
                    "total_items": 3,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        old_config = {
            "sources": [
                {"id": "rss_wired", "type": "rss", "name": "Wired AI", "enabled": True},
                {"id": "rss_openai", "type": "rss", "name": "OpenAI News", "enabled": True},
            ]
        }
        new_config = {
            "sources": [
                {"id": "rss_openai", "type": "rss", "name": "OpenAI News", "enabled": True},
            ]
        }

        summary = purge_deleted_source_data(root, new_config, previous_config=old_config)

        archive = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(summary["archive.json"], 1)
        self.assertEqual([item["title"] for item in archive["items"]], ["保留 RSS", "保留公众号"])
        self.assertEqual(archive["total_items"], 2)

    def test_purge_deleted_source_data_skips_missing_data_dir(self):
        root = Path(self.create_temp_dir())

        summary = purge_deleted_source_data(root, {"sources": []})

        self.assertEqual(summary, {})

    def test_purge_deleted_source_data_does_not_rewrite_when_nothing_removed(self):
        root = Path(self.create_temp_dir())
        data_dir = root / "data"
        data_dir.mkdir()
        path = data_dir / "archive.json"
        original = json.dumps(
            {"items": [{"site_id": "bilibili_dynamic", "source": "张三"}], "total_items": 1},
            ensure_ascii=False,
        )
        path.write_text(original, encoding="utf-8")

        summary = purge_deleted_source_data(
            root,
            {
                "sources": [
                    {
                        "id": "bilibili_dynamic_sources",
                        "name": "B站动态",
                        "type": "bilibili_dynamic",
                        "target": "张三",
                    }
                ]
            },
        )

        self.assertEqual(summary["archive.json"], 0)
        self.assertEqual(path.read_text(encoding="utf-8"), original)

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

    def test_write_online_source_config_roundtrips_public_config_and_opml(self):
        root = Path(self.create_temp_dir())

        result = write_online_source_config(
            root,
            {
                "sources": [
                    {
                        "name": "技术爬爬虾",
                        "type": "bilibili_dynamic",
                        "locator": "316183842",
                    },
                    {
                        "name": "Foundation",
                        "type": "github_release",
                        "locator": "https://github.com/AlkaidLab/foundation-sunshine",
                    },
                    {
                        "name": "A & B <AI>",
                        "type": "rss",
                        "locator": "https://example.com/feed.xml?tag=ai",
                    },
                ]
            },
        )
        loaded = read_online_source_config(root)
        config_path = root / "config" / "online-sources.json"
        opml_path = root / "feeds" / "online-sources.opml"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        opml_text = opml_path.read_text(encoding="utf-8")

        self.assertEqual(result["source_count"], 3)
        self.assertEqual(loaded["source_count"], 3)
        self.assertTrue(config_path.exists())
        self.assertTrue(opml_path.exists())
        self.assertIn("online_opmlrss", [source["id"] for source in config["sources"]])
        self.assertIn("AlkaidLab/foundation-sunshine", [source["locator"] for source in config["sources"]])
        self.assertIn("A &amp; B &lt;AI&gt;", opml_text)

    def test_read_online_source_config_accepts_we_mp_rss_jsonl_with_empty_locator(self):
        root = Path(self.create_temp_dir())
        config_path = root / "config" / "online-sources.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "id": "online_we_mp_rss_maobidao",
                            "name": "猫笔刀",
                            "type": "we_mp_rss_jsonl",
                            "locator": "",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = read_online_source_config(root)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(result["sources"][0]["type"], "we_mp_rss_jsonl")
        self.assertEqual(result["sources"][0]["locator"], "")
        self.assertEqual(result["sources"][0]["channel"], "微信公众号")

    def test_read_real_online_source_config_accepts_every_source_type(self):
        """真实配置里的每种类型都必须能被线上同步白名单接受，否则整份配置读取会失败。"""
        root = Path(__file__).resolve().parents[1]

        result = read_online_source_config(root)

        self.assertTrue(result["ok"], result.get("error"))
        self.assertIsNone(result.get("error"))
        # source_count 是用户可编辑源，不含内部 OPML wrapper
        self.assertEqual(result["source_count"], len(result["sources"]))
        self.assertIn("we_mp_rss_jsonl", {source["type"] for source in result["sources"]})

    def test_write_online_source_config_rejects_private_or_sensitive_values(self):
        root = Path(self.create_temp_dir())

        with self.assertRaises(ValueError):
            write_online_source_config(
                root,
                {
                    "sources": [
                        {
                            "name": "Bad",
                            "type": "rss",
                            "locator": "https://example.com/feed.xml",
                            "notes": "cookie should not be public",
                        }
                    ]
                },
            )

        with self.assertRaises(ValueError):
            write_online_source_config(
                root,
                {
                    "sources": [
                        {
                            "name": "Private OPML",
                            "type": "rss",
                            "locator": "feeds/follow.opml",
                        }
                    ]
                },
            )

    def test_write_online_source_config_blocks_bulk_delete(self):
        root = Path(self.create_temp_dir())
        existing_sources = [
            {
                "id": f"source_{index}",
                "name": f"Source {index}",
                "type": "rss",
                "locator": f"https://example.com/{index}.xml",
            }
            for index in range(20)
        ]
        config_path = root / "config" / "online-sources.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps({"sources": existing_sources}), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "^online_sources_bulk_delete_blocked:"):
            write_online_source_config(root, {"sources": existing_sources[:1]})

        saved = json.loads((root / "config" / "online-sources.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved["sources"]), 20)

    def test_write_online_source_config_allows_confirmed_bulk_delete(self):
        root = Path(self.create_temp_dir())
        existing_sources = [
            {
                "id": f"source_{index}",
                "name": f"Source {index}",
                "type": "rss",
                "locator": f"https://example.com/{index}.xml",
            }
            for index in range(20)
        ]
        config_path = root / "config" / "online-sources.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps({"sources": existing_sources}), encoding="utf-8")

        result = write_online_source_config(
            root,
            {"sources": existing_sources[:1], "confirm_bulk_delete": True},
        )

        self.assertEqual(result["source_count"], 1)

    def test_write_online_source_config_allows_single_delete(self):
        root = Path(self.create_temp_dir())
        existing_sources = [
            {
                "id": f"source_{index}",
                "name": f"Source {index}",
                "type": "rss",
                "locator": f"https://example.com/{index}.xml",
            }
            for index in range(20)
        ]
        config_path = root / "config" / "online-sources.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps({"sources": existing_sources}), encoding="utf-8")

        result = write_online_source_config(root, {"sources": existing_sources[:19]})

        self.assertEqual(result["source_count"], 19)

    def test_save_online_source_config_purges_only_deleted_member(self):
        root = Path(self.create_temp_dir())
        sources = [
            {"name": "张三", "type": "bilibili_dynamic", "locator": "111"},
            {"name": "李四", "type": "bilibili_dynamic", "locator": "222"},
        ]
        write_online_source_config(root, {"sources": sources})
        data_dir = root / "data"
        data_dir.mkdir()
        archive_path = data_dir / "archive.json"
        archive_path.write_text(
            json.dumps(
                {
                    "items": [
                        {"site_id": "bilibili_dynamic", "source": "张三", "title": "保留"},
                        {"site_id": "bilibili_dynamic", "source": "李四", "title": "删除"},
                        {"site_id": "mediacrawler_xhs", "source": "未在线上配置管理", "title": "不误伤"},
                    ],
                    "total_items": 3,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = save_online_source_config(root, {"sources": sources[:1]})

        archive = json.loads(archive_path.read_text(encoding="utf-8"))
        self.assertEqual(result["purged_items"]["archive.json"], 1)
        self.assertEqual([item["title"] for item in archive["items"]], ["保留", "不误伤"])
        self.assertEqual(archive["total_items"], 2)

    def test_save_online_source_config_defers_purge_while_refresh_is_running(self):
        from scripts.local_server import REFRESH_LOCK

        root = Path(self.create_temp_dir())
        sources = [
            {"name": "张三", "type": "bilibili_dynamic", "locator": "111"},
            {"name": "李四", "type": "bilibili_dynamic", "locator": "222"},
        ]
        write_online_source_config(root, {"sources": sources})

        REFRESH_LOCK.acquire()
        try:
            result = save_online_source_config(root, {"sources": sources[:1]})
        finally:
            REFRESH_LOCK.release()

        pending = json.loads((root / "data" / "pending-purge.json").read_text(encoding="utf-8"))
        self.assertEqual(result["purged_items"]["deferred"], {"bilibili_dynamic": ["李四"]})
        self.assertEqual(pending["sources"], {"bilibili_dynamic": ["李四"]})

    def test_transactional_save_queues_purge_before_write_and_cancels_it_on_failure(self):
        sources = [
            {"name": "张三", "type": "bilibili_dynamic", "locator": "111"},
            {"name": "李四", "type": "bilibili_dynamic", "locator": "222"},
        ]
        root, _origin, _peer = self.create_sync_git_repositories({"sources": sources})
        archive_path = root / "data" / "archive.json"
        archive_path.write_text(
            json.dumps(
                {
                    "items": [
                        {"site_id": "bilibili_dynamic", "source": "李四", "title": "必须保留"}
                    ],
                    "total_items": 1,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        archive_before = archive_path.read_bytes()
        current = read_online_source_config(root)
        events = []
        original_queue = queue_pending_purge
        original_replace = online_sources.atomic_replace_bytes
        config_path = root / "config" / "online-sources.json"
        failed = False

        def record_queue(*args, **kwargs):
            events.append("queue")
            return original_queue(*args, **kwargs)

        def fail_config_once(path, content):
            nonlocal failed
            if path == config_path and not failed:
                failed = True
                events.append("config_replace")
                raise OSError("injected config failure")
            return original_replace(path, content)

        with patch("scripts.local_server.queue_pending_purge", side_effect=record_queue), patch.object(
            online_sources,
            "atomic_replace_bytes",
            side_effect=fail_config_once,
        ):
            with self.assertRaises(online_sources.OnlineSourcesError) as raised:
                save_online_source_config(
                    root,
                    {"sources": [sources[0]]},
                    if_match=current["etag"],
                )

        self.assertEqual(raised.exception.code, "online_sources_write_failed")
        self.assertEqual(events[:2], ["queue", "config_replace"])
        self.assertEqual(archive_path.read_bytes(), archive_before)
        pending = json.loads((root / "data" / "pending-purge.json").read_text(encoding="utf-8"))
        self.assertEqual(pending["sources"], {})

    def test_managed_source_tampering_is_rejected_before_purge(self):
        root = Path(self.create_temp_dir())
        config_path = root / "config" / "online-sources.json"
        config_path.parent.mkdir(parents=True)
        managed_source = {
            "id": "online_github_repo_987654321",
            "name": "owner/repo",
            "type": "github_release",
            "enabled": True,
            "channel": "GitHub Release",
            "target": "owner/repo",
            "locator": "owner/repo",
            "env": "",
            "notes": "只追踪 release",
            "managed_by": "github_stars",
            "managed_account_id": 12345678,
            "managed_repo_id": 987654321,
            "managed_state": "active",
        }
        config_path.write_text(
            json.dumps(
                {
                    "github_star_sync": {
                        "version": 1,
                        "account_id": 12345678,
                        "account_login": "example-user",
                    },
                    "sources": [managed_source],
                }
            ),
            encoding="utf-8",
        )
        before = config_path.read_bytes()
        tampered = {**managed_source, "enabled": False}

        with patch("scripts.local_server.purge_or_defer_source_config") as purge_mock:
            with self.assertRaisesRegex(ValueError, "^github_star_managed_fields_readonly:"):
                save_online_source_config(root, {"sources": [tampered]})

        purge_mock.assert_not_called()
        self.assertEqual(config_path.read_bytes(), before)
        self.assertFalse((root / "data" / "pending-purge.json").exists())

    def test_pending_purge_merges_multiple_saves(self):
        root = Path(self.create_temp_dir())
        config_a = {
            "sources": [{"id": "a", "type": "bilibili_dynamic", "target": "甲", "locator": "1"}]
        }
        config_b = {
            "sources": [{"id": "b", "type": "bilibili_dynamic", "target": "乙", "locator": "2"}]
        }

        queue_pending_purge(root, {"bilibili_dynamic": {"甲"}}, config_b)
        queue_pending_purge(root, {"bilibili_dynamic": {"乙"}}, {"sources": []})

        pending = json.loads((root / "data" / "pending-purge.json").read_text(encoding="utf-8"))
        self.assertEqual(pending["sources"], {"bilibili_dynamic": ["乙", "甲"]})

    def test_flush_pending_purge_removes_history_and_clears_ledger(self):
        root = Path(self.create_temp_dir())
        data_dir = root / "data"
        data_dir.mkdir()
        (root / "config").mkdir()
        (root / "config" / "online-sources.json").write_text(
            json.dumps({"sources": []}), encoding="utf-8"
        )
        (data_dir / "archive.json").write_text(
            json.dumps(
                {
                    "items": [{"site_id": "bilibili_dynamic", "source": "甲", "title": "待清理"}],
                    "total_items": 1,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        queue_pending_purge(root, {"bilibili_dynamic": {"甲"}}, {"sources": []})

        summary = flush_pending_purge(root)

        archive = json.loads((data_dir / "archive.json").read_text(encoding="utf-8"))
        pending = json.loads((data_dir / "pending-purge.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["archive.json"], 1)
        self.assertEqual(archive["items"], [])
        self.assertEqual(pending["sources"], {})

    def test_flush_pending_purge_keeps_source_that_was_added_back(self):
        root = Path(self.create_temp_dir())
        data_dir = root / "data"
        data_dir.mkdir()
        (root / "config").mkdir()
        current_config = {
            "sources": [
                {"id": "a", "type": "bilibili_dynamic", "target": "甲", "locator": "1"}
            ]
        }
        (root / "config" / "online-sources.json").write_text(
            json.dumps(current_config, ensure_ascii=False), encoding="utf-8"
        )
        (data_dir / "archive.json").write_text(
            json.dumps(
                {
                    "items": [{"site_id": "bilibili_dynamic", "source": "甲", "title": "必须保留"}],
                    "total_items": 1,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        queue_pending_purge(root, {"bilibili_dynamic": {"甲"}}, {"sources": []})

        summary = flush_pending_purge(root)

        archive = json.loads((data_dir / "archive.json").read_text(encoding="utf-8"))
        pending = json.loads((data_dir / "pending-purge.json").read_text(encoding="utf-8"))
        self.assertEqual(summary, {})
        self.assertEqual(archive["items"][0]["title"], "必须保留")
        self.assertEqual(pending["sources"], {})

    @patch("scripts.radar.server.refresh.time.sleep", return_value=None)
    @patch("scripts.radar.server.refresh.subprocess.Popen")
    def test_refresh_flushes_pending_purge_before_releasing_lock(self, popen_mock, _sleep_mock):
        events = []
        process = popen_mock.return_value
        process.poll.return_value = 0
        process.communicate.return_value = ("", "")
        process.returncode = 0

        class RecordingLock:
            def release(self):
                events.append("release")

        with patch("scripts.radar.server.refresh.flush_pending_purge", side_effect=lambda root: events.append("flush")):
            with patch("scripts.radar.server.refresh.REFRESH_LOCK", RecordingLock()):
                run_refresh_background(Path(self.create_temp_dir()), "24h", ["fake"], ["刷新"])

        self.assertEqual(events, ["flush", "release"])

    @patch("scripts.local_server.sync_online_source_config")
    @patch("scripts.local_server.save_online_source_config")
    def test_save_and_sync_online_source_config_preserves_purge_summary(self, save_mock, sync_mock):
        save_mock.return_value = {"ok": True, "purged_items": {"archive.json": 2}}
        sync_mock.return_value = {"ok": True, "synced": True}
        root = Path(self.create_temp_dir())
        payload = {"sources": []}

        result = save_and_sync_online_source_config(root, payload)

        save_mock.assert_called_once_with(root, payload)
        sync_mock.assert_called_once_with(root, None)
        self.assertEqual(result["purged_items"], {"archive.json": 2})

    def test_fresh_preflight_allows_remote_data_only_commits_without_mutating_local_state(self):
        root, origin, peer = self.create_sync_git_repositories(self.online_source_payload("initial"))
        peer_data = peer / "data" / "latest-24h.json"
        peer_data.write_text('{"version":"remote-data"}\n', encoding="utf-8")
        self.git(peer, "add", "data/latest-24h.json")
        self.git(peer, "commit", "-m", "remote data snapshot")
        self.git(peer, "push")
        head_before = self.git(root, "rev-parse", "HEAD").stdout.strip()
        status_before = self.git(root, "status", "--porcelain=v1").stdout
        stash_before = self.git(root, "stash", "list", "--format=%H %s").stdout

        target = online_sources.fresh_git_preflight(root)

        self.assertEqual(target["pre_head"], head_before)
        self.assertEqual(target["branch"], "master")
        self.assertEqual(target["remote_name"], "origin")
        self.assertEqual(target["remote_ref"], "refs/heads/master")
        self.assertEqual(target["fetched_oid"], self.git(origin, "rev-parse", "master").stdout.strip())
        self.assertRegex(target["fetch_url_digest"], "^[0-9a-f]{64}$")
        self.assertEqual(target["fetch_url_digest"], target["push_url_digest"])
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), head_before)
        self.assertEqual(self.git(root, "status", "--porcelain=v1").stdout, status_before)
        self.assertEqual(self.git(root, "stash", "list", "--format=%H %s").stdout, stash_before)

    def test_github_star_apply_no_change_and_unbind_use_real_safe_git_transaction(self):
        root, origin, _peer = self.create_sync_git_repositories(
            self.online_source_payload("initial")
        )
        archive_path = root / "data" / "archive.json"
        archive_path.write_text('{"items":[{"id":"keep-history"}]}\n', encoding="utf-8")
        archive_before = archive_path.read_bytes()
        snapshot = {
            "account": {"id": 12345678, "login": "example-user"},
            "repositories": [{"id": 987654321, "full_name": "owner/starred-repo"}],
            "starred_count": 1,
            "private_skipped_count": 0,
        }

        with patch.object(github_stars, "fetch_github_star_snapshot", return_value=snapshot):
            preview = github_stars.preview_github_star_sync(root, {"username": "example-user"})
            applied = github_stars.apply_github_star_sync(
                root,
                {
                    "account_id": 12345678,
                    "preview_hash": preview["preview_hash"],
                },
            )

        self.assertEqual(applied["outcome"], "pushed", applied)
        self.assertEqual(
            self.git(root, "rev-parse", "HEAD").stdout.strip(),
            self.git(origin, "rev-parse", "master").stdout.strip(),
        )
        managed = next(
            source
            for source in applied["sources"]
            if source.get("managed_repo_id") == 987654321
        )
        self.assertEqual(managed["id"], "online_github_repo_987654321")
        before_repeat = {
            "head": self.git(root, "rev-parse", "HEAD").stdout.strip(),
            "config": (root / "config" / "online-sources.json").read_bytes(),
            "opml": (root / "feeds" / "online-sources.opml").read_bytes(),
            "updated_at": applied["config"]["updated_at"],
        }

        with patch.object(github_stars, "fetch_github_star_snapshot", return_value=snapshot):
            second_preview = github_stars.preview_github_star_sync(root, {})
            repeated = github_stars.apply_github_star_sync(
                root,
                {
                    "account_id": 12345678,
                    "preview_hash": second_preview["preview_hash"],
                },
            )

        self.assertEqual(repeated["outcome"], "no_change")
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), before_repeat["head"])
        self.assertEqual((root / "config" / "online-sources.json").read_bytes(), before_repeat["config"])
        self.assertEqual((root / "feeds" / "online-sources.opml").read_bytes(), before_repeat["opml"])
        self.assertEqual(repeated["config"]["updated_at"], before_repeat["updated_at"])

        unbound = github_stars.unbind_github_star_sync(
            root,
            {"account_id": 12345678, "confirmed": True},
            if_match=repeated["etag"],
        )
        restored_source = next(source for source in unbound["sources"] if source["id"] == managed["id"])
        self.assertEqual(unbound["outcome"], "pushed")
        self.assertNotIn("github_star_sync", unbound["config"])
        self.assertEqual(restored_source["enabled"], managed["enabled"])
        self.assertEqual(restored_source["notes"], managed["notes"])
        for field in online_sources.GITHUB_MANAGED_FIELDS:
            self.assertNotIn(field, restored_source)
        self.assertEqual(archive_path.read_bytes(), archive_before)
        self.assertFalse((root / "data" / "pending-purge.json").exists())

    def test_fresh_preflight_rejects_non_master_and_existing_index(self):
        for label in ("branch", "index"):
            with self.subTest(label=label):
                root, _origin, _peer = self.create_sync_git_repositories(
                    self.online_source_payload("initial")
                )
                if label == "branch":
                    self.git(root, "switch", "-c", "feature/not-master")
                else:
                    readme = root / "README.md"
                    readme.write_text("staged user change\n", encoding="utf-8")
                    self.git(root, "add", "README.md")
                head_before = self.git(root, "rev-parse", "HEAD").stdout.strip()
                index_before = self.git(root, "write-tree").stdout.strip()

                with self.assertRaises(online_sources.OnlineSourcesError) as raised:
                    online_sources.fresh_git_preflight(root)

                self.assertEqual(raised.exception.code, "online_sources_preflight_failed")
                self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), head_before)
                self.assertEqual(self.git(root, "write-tree").stdout.strip(), index_before)

    def test_fresh_preflight_rejects_dirty_config_before_fetch_or_write(self):
        root, _origin, _peer = self.create_sync_git_repositories(self.online_source_payload("initial"))
        config_path = root / "config" / "online-sources.json"
        config_path.write_text(config_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        before = config_path.read_bytes()
        fetch_head_path = Path(self.git(root, "rev-parse", "--git-path", "FETCH_HEAD").stdout.strip())
        if not fetch_head_path.is_absolute():
            fetch_head_path = root / fetch_head_path
        fetch_head_before = fetch_head_path.read_bytes() if fetch_head_path.exists() else None

        with self.assertRaises(online_sources.OnlineSourcesError) as raised:
            online_sources.fresh_git_preflight(root)

        self.assertEqual(raised.exception.code, "online_sources_preflight_failed")
        self.assertEqual(config_path.read_bytes(), before)
        fetch_head_after = fetch_head_path.read_bytes() if fetch_head_path.exists() else None
        self.assertEqual(fetch_head_after, fetch_head_before)

    def test_fresh_preflight_rejects_remote_config_change_and_unknown_ahead_commit(self):
        for label in ("remote_config", "local_ahead"):
            with self.subTest(label=label):
                root, origin, peer = self.create_sync_git_repositories(
                    self.online_source_payload("initial")
                )
                if label == "remote_config":
                    sync_online_source_config(peer, self.online_source_payload("remote"), push=False)
                    self.git(peer, "push")
                else:
                    readme = root / "README.md"
                    readme.write_text("local user commit\n", encoding="utf-8")
                    self.git(root, "add", "README.md")
                    self.git(root, "commit", "-m", "user ahead commit")
                local_head = self.git(root, "rev-parse", "HEAD").stdout.strip()
                remote_head = self.git(origin, "rev-parse", "master").stdout.strip()
                config_before = (root / "config" / "online-sources.json").read_bytes()

                with self.assertRaises(online_sources.OnlineSourcesError) as raised:
                    online_sources.fresh_git_preflight(root)

                self.assertEqual(raised.exception.code, "online_sources_preflight_failed")
                self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), local_head)
                self.assertEqual(self.git(origin, "rev-parse", "master").stdout.strip(), remote_head)
                self.assertEqual((root / "config" / "online-sources.json").read_bytes(), config_before)

    def test_fresh_preflight_rejects_fetch_and_push_remote_mismatch(self):
        root, _origin, _peer = self.create_sync_git_repositories(self.online_source_payload("initial"))
        second_origin = root.parent / "second-origin.git"
        self.git(root.parent, "init", "--bare", str(second_origin))
        self.git(root, "remote", "set-url", "--push", "origin", str(second_origin))
        head_before = self.git(root, "rev-parse", "HEAD").stdout.strip()

        with self.assertRaises(online_sources.OnlineSourcesError) as raised:
            online_sources.fresh_git_preflight(root)

        self.assertEqual(raised.exception.code, "online_sources_preflight_failed")
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), head_before)

    def test_sync_online_source_config_commits_only_public_config_files(self):
        root = Path(self.create_temp_dir())

        subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
        (root / "README.md").write_text("init\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        data_dir = root / "data"
        data_dir.mkdir()
        (data_dir / "latest-24h.json").write_text("{}", encoding="utf-8")

        result = sync_online_source_config(
            root,
            {
                "sources": [
                    {
                        "name": "技术爬爬虾",
                        "type": "bilibili_dynamic",
                        "locator": "316183842",
                    },
                    {
                        "name": "OpenAI News",
                        "type": "rss",
                        "locator": "https://openai.com/news/rss.xml",
                    },
                ]
            },
            push=False,
        )
        show = subprocess.run(
            ["git", "show", "--name-only", "--oneline", "-1"],
            cwd=root,
            check=True,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
        ).stdout

        self.assertTrue(result["synced"], result)
        self.assertFalse(result["pushed"])
        self.assertIn("config/online-sources.json", show)
        self.assertIn("feeds/online-sources.opml", show)
        self.assertNotIn("data/latest-24h.json", show)

    def test_sync_online_source_config_restores_tracked_data_after_rebase_and_push(self):
        root, origin, peer = self.create_sync_git_repositories()
        data_path = root / "data" / "latest-24h.json"
        data_path.write_text('{"version":"local"}\n', encoding="utf-8")
        peer_data_path = peer / "data" / "latest-24h.json"
        peer_data_path.write_text('{"version":"online"}\n', encoding="utf-8")
        self.git(peer, "add", "data/latest-24h.json")
        self.git(peer, "commit", "-m", "online data update")
        self.git(peer, "push")

        first_result = sync_online_source_config(root, self.online_source_payload("local"), push=True)

        self.assertTrue(first_result["synced"])
        self.assertTrue(first_result["pushed"])
        self.assertEqual(data_path.read_text(encoding="utf-8"), '{"version":"local"}\n')
        self.assertEqual(self.git(root, "stash", "list").stdout.strip(), "")
        self.assertIn(
            " M data/latest-24h.json",
            self.git(root, "status", "--porcelain").stdout.splitlines(),
        )
        self.assertNotIn(
            "data/latest-24h.json",
            self.git(root, "diff", "--cached", "--name-only").stdout.splitlines(),
        )

        second_result = sync_online_source_config(root, self.online_source_payload("local-second"), push=True)

        self.assertTrue(second_result["synced"])
        self.assertTrue(second_result["pushed"])
        self.assertIn(
            " M data/latest-24h.json",
            self.git(root, "status", "--porcelain").stdout.splitlines(),
        )
        remote_log = self.git(origin, "log", "--oneline", "--all").stdout
        self.assertIn("配置：同步线上信源", remote_log)

    def test_sync_online_source_config_rejects_remote_non_data_changes_without_overwrite(self):
        root, origin, peer = self.create_sync_git_repositories()
        data_path = root / "data" / "latest-24h.json"
        data_path.write_text('{"version":"local"}\n', encoding="utf-8")
        head_before = self.git(root, "rev-parse", "HEAD").stdout.strip()
        readme_before = (root / "README.md").read_bytes()
        stash_before = self.git(root, "stash", "list", "--format=%H%x09%gs").stdout
        peer_readme_path = peer / "README.md"
        peer_readme_path.write_text("remote update\n", encoding="utf-8")
        self.git(peer, "add", "README.md")
        self.git(peer, "commit", "-m", "remote clean path update")
        self.git(peer, "push")
        remote_head = self.git(peer, "rev-parse", "HEAD").stdout.strip()

        with self.assertRaises(online_sources.OnlineSourcesError) as raised:
            sync_online_source_config(root, self.online_source_payload("local"), push=True)

        self.assertEqual(raised.exception.code, "online_sources_preflight_failed")
        self.assertEqual(raised.exception.details.get("reason"), "remote_non_data_changes")
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), head_before)
        self.assertEqual(data_path.read_text(encoding="utf-8"), '{"version":"local"}\n')
        self.assertEqual((root / "README.md").read_bytes(), readme_before)
        self.assertEqual(self.git(origin, "rev-parse", "master").stdout.strip(), remote_head)
        self.assertEqual(
            self.git(origin, "show", "master:README.md").stdout,
            "remote update\n",
        )
        self.assertEqual(
            self.git(root, "stash", "list", "--format=%H%x09%gs").stdout,
            stash_before,
        )
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_sync_online_source_config_restores_named_paths_by_stash_oid(self):
        import scripts.radar.server.online_sources as online_sources

        root, _origin, peer = self.create_sync_git_repositories()
        special_relative_path = "data/中文 路径.json"
        special_path = root / special_relative_path
        special_path.write_text('{"version":"initial-special"}\n', encoding="utf-8")
        self.git(root, "add", "--", special_relative_path)
        self.git(root, "commit", "-m", "add unicode data path")
        self.git(root, "push")
        self.git(peer, "pull", "--ff-only")

        readme_path = root / "README.md"
        readme_path.write_text("legacy local draft\n", encoding="utf-8")
        self.git(root, "stash", "push", "-m", "legacy-user-stash", "--", "README.md")
        legacy_stash_oid = self.git(root, "rev-parse", "refs/stash").stdout.strip()

        special_path.write_text('{"version":"local-special"}\n', encoding="utf-8")
        peer_data_path = peer / "data" / "latest-24h.json"
        peer_data_path.write_text('{"version":"remote"}\n', encoding="utf-8")
        self.git(peer, "add", "data/latest-24h.json")
        self.git(peer, "commit", "-m", "remote data update")
        self.git(peer, "push")

        original_git_checked = online_sources.git_checked
        injected_stash_oid = {"value": ""}

        def git_checked_with_interleaved_stash(root_dir, args, timeout=60):
            completed = original_git_checked(root_dir, args, timeout=timeout)
            if args and args[0] == "rebase" and not injected_stash_oid["value"]:
                injected_readme_path = Path(root_dir) / "README.md"
                injected_readme_path.write_text("interleaved local draft\n", encoding="utf-8")
                self.git(root_dir, "stash", "push", "-m", "interleaved-user-stash", "--", "README.md")
                injected_stash_oid["value"] = self.git(root_dir, "rev-parse", "refs/stash").stdout.strip()
            return completed

        with patch.object(online_sources, "git_checked", side_effect=git_checked_with_interleaved_stash):
            result = sync_online_source_config(root, self.online_source_payload("local"), push=True)

        self.assertTrue(result["synced"])
        self.assertTrue(result["pushed"])
        self.assertEqual(special_path.read_text(encoding="utf-8"), '{"version":"local-special"}\n')
        unstaged_paths = {
            path for path in self.git(root, "diff", "--name-only", "-z").stdout.split("\0") if path
        }
        staged_paths = {
            path
            for path in self.git(root, "diff", "--cached", "--name-only", "-z").stdout.split("\0")
            if path
        }
        self.assertIn(special_relative_path, unstaged_paths)
        self.assertNotIn(special_relative_path, staged_paths)
        remaining_stash_oids = {
            line.split(" ", 1)[0]
            for line in self.git(root, "stash", "list", "--format=%H %s").stdout.splitlines()
            if line
        }
        self.assertEqual(
            remaining_stash_oids,
            {legacy_stash_oid, injected_stash_oid["value"]},
        )

    def test_sync_online_source_config_rejects_existing_index_without_mutating_it(self):
        initial_payload = self.online_source_payload("initial")
        root, _origin, _peer = self.create_sync_git_repositories(initial_payload)
        data_path = root / "data" / "latest-24h.json"
        data_path.write_text('{"version":"staged"}\n', encoding="utf-8")
        self.git(root, "add", "data/latest-24h.json")
        index_tree_before = self.git(root, "write-tree").stdout.strip()
        head_before = self.git(root, "rev-parse", "HEAD").stdout.strip()
        stash_before = self.git(root, "stash", "list", "--format=%H %s").stdout

        with self.assertRaises(online_sources.OnlineSourcesError) as raised:
            sync_online_source_config(root, None, push=True)

        self.assertEqual(raised.exception.code, "online_sources_preflight_failed")
        self.assertEqual(raised.exception.details.get("reason"), "index_not_clean")
        self.assertEqual(self.git(root, "write-tree").stdout.strip(), index_tree_before)
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), head_before)
        self.assertEqual(self.git(root, "stash", "list", "--format=%H %s").stdout, stash_before)

    def test_sync_online_source_config_without_tracked_changes_does_not_create_stash(self):
        root, _origin, _peer = self.create_sync_git_repositories()
        untracked_path = root / "output" / "local.txt"
        untracked_path.parent.mkdir()
        untracked_path.write_text("keep\n", encoding="utf-8")

        result = sync_online_source_config(root, self.online_source_payload("clean"), push=True)

        self.assertTrue(result["synced"], result)
        self.assertTrue(result["pushed"])
        self.assertTrue(untracked_path.exists())
        self.assertEqual(self.git(root, "stash", "list").stdout.strip(), "")

    def test_sync_online_source_config_restores_data_after_rebase_conflict(self):
        initial_payload = self.online_source_payload("initial")
        root, _origin, peer = self.create_sync_git_repositories(initial_payload)
        data_path = root / "data" / "latest-24h.json"
        data_path.write_text('{"version":"local"}\n', encoding="utf-8")
        peer_data_path = peer / "data" / "latest-24h.json"
        peer_data_path.write_text('{"version":"remote"}\n', encoding="utf-8")
        self.git(peer, "add", "data/latest-24h.json")
        self.git(peer, "commit", "-m", "remote data update")
        self.git(peer, "push")

        original_git_checked = online_sources.git_checked

        def fail_rebase(root_dir, args, timeout=60):
            if args and args[0] == "rebase":
                raise RuntimeError("injected rebase conflict")
            return original_git_checked(root_dir, args, timeout=timeout)

        with patch.object(online_sources, "git_checked", side_effect=fail_rebase):
            result = sync_online_source_config(root, self.online_source_payload("local"), push=True)

        self.assertEqual(result["outcome"], "committed_not_pushed")
        self.assertTrue(result["partial"])
        self.assertEqual(data_path.read_text(encoding="utf-8"), '{"version":"local"}\n')
        self.assertEqual(self.git(root, "stash", "list").stdout.strip(), "")
        status = self.git(root, "status", "--porcelain").stdout.splitlines()
        self.assertFalse(any(line.startswith(("UU ", "AA ", "DD ")) for line in status))
        self.assertNotIn(
            "data/latest-24h.json",
            self.git(root, "diff", "--cached", "--name-only").stdout.splitlines(),
        )
        rebase_merge_path = Path(self.git(root, "rev-parse", "--git-path", "rebase-merge").stdout.strip())
        rebase_apply_path = Path(self.git(root, "rev-parse", "--git-path", "rebase-apply").stdout.strip())
        self.assertFalse((root / rebase_merge_path).exists())
        self.assertFalse((root / rebase_apply_path).exists())

    def test_refresh_command_uses_fixed_local_update_script(self):
        root = Path("E:/AI-news-reader/ai-news-radar-run")

        command = refresh_command(root)

        self.assertTrue(command[0].endswith("python.exe") or command[0].endswith("python"))
        self.assertEqual(command[1], str(root / "scripts" / "update_news.py"))
        self.assertIn("--source-config", command)
        self.assertIn("config/online-sources.json", command)
        self.assertIn("--all-time", command)
        self.assertIn("--collect-window-hours", command)
        window_hours = command[command.index("--collect-window-hours") + 1]
        self.assertGreater(int(window_hours), 0)

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

    def test_resolve_collect_window_hours_all_scope_returns_zero(self):
        now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)

        result = resolve_collect_window_hours("all", now - timedelta(hours=3), now)

        self.assertEqual(result, 0)

    def test_resolve_collect_window_hours_counts_hours_since_last(self):
        now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)

        result = resolve_collect_window_hours("24h", now - timedelta(hours=3), now)

        self.assertEqual(result, 3)

    def test_resolve_collect_window_hours_rounds_up(self):
        now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)

        result = resolve_collect_window_hours("24h", now - timedelta(hours=2, minutes=30), now)

        self.assertEqual(result, 3)

    def test_resolve_collect_window_hours_minimum_one_hour(self):
        now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)

        result = resolve_collect_window_hours("24h", now - timedelta(minutes=10), now)

        self.assertEqual(result, 1)

    def test_resolve_collect_window_hours_falls_back_when_missing(self):
        now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)

        result = resolve_collect_window_hours("24h", None, now)

        self.assertEqual(result, 24)

    def test_resolve_collect_window_hours_falls_back_on_future_timestamp(self):
        now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)

        result = resolve_collect_window_hours("24h", now + timedelta(minutes=1), now)

        self.assertEqual(result, 24)

    def test_last_collection_time_reads_generated_at(self):
        root = Path(self.create_temp_dir())
        data_dir = root / "data"
        data_dir.mkdir()
        (data_dir / "source-status.json").write_text(
            json.dumps({"generated_at": "2026-07-05T09:00:00Z"}),
            encoding="utf-8",
        )

        result = last_collection_time(root)

        self.assertEqual(result, datetime(2026, 7, 5, 9, 0, tzinfo=timezone.utc))

    def test_collect_window_hours_for_scope_falls_back_on_invalid_status_time(self):
        root = Path(self.create_temp_dir())
        data_dir = root / "data"
        data_dir.mkdir()
        (data_dir / "source-status.json").write_text(
            json.dumps({"generated_at": "not-a-date"}),
            encoding="utf-8",
        )
        now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)

        result = collect_window_hours_for_scope(root, "24h", now=now)

        self.assertEqual(result, 24)

    def test_refresh_command_window_counts_hours_since_last_collection(self):
        root = Path(self.create_temp_dir())
        data_dir = root / "data"
        data_dir.mkdir()
        now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
        (data_dir / "source-status.json").write_text(
            json.dumps({"generated_at": (now - timedelta(hours=5)).isoformat().replace("+00:00", "Z")}),
            encoding="utf-8",
        )

        command = refresh_command(root, "24h", now=now)

        self.assertEqual(command[command.index("--collect-window-hours") + 1], "5")

    def test_refresh_command_window_falls_back_without_previous_status(self):
        root = Path(self.create_temp_dir())
        now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)

        command = refresh_command(root, "24h", now=now)

        self.assertEqual(command[command.index("--collect-window-hours") + 1], "24")

    def test_refresh_step_plan_names_enabled_subscription_sources(self):
        config = {
            "sources": [
                {
                    "id": "youtube_one",
                    "name": "YouTube One",
                    "type": "rss",
                    "locator": "https://www.youtube.com/feeds/videos.xml?channel_id=UC123",
                    "enabled": True,
                },
                {
                    "id": "bilibili_dynamic_sources",
                    "name": "B站动态",
                    "type": "bilibili_dynamic",
                    "enabled": True,
                },
                {
                    "id": "wewe_rss_maobidao",
                    "name": "猫笔刀",
                    "type": "wewe_rss",
                    "enabled": True,
                },
                {
                    "id": "github_release_foundation_sunshine",
                    "name": "Foundation Sunshine",
                    "type": "github_release",
                    "locator": "https://api.github.com/repos/AlkaidLab/foundation-sunshine/releases",
                    "enabled": True,
                },
                {
                    "id": "disabled_xhs",
                    "name": "Disabled XHS",
                    "type": "mediacrawler_jsonl",
                    "channel": "小红书",
                    "enabled": False,
                },
            ]
        }

        steps = refresh_step_plan(config)

        self.assertIn("YouTube 订阅", steps)
        self.assertIn("B站动态订阅", steps)
        self.assertIn("微信公众号订阅", steps)
        self.assertIn("GitHub Release", steps)
        self.assertNotIn("读取小红书采集结果", steps)
        self.assertEqual(steps[-1], "合并并生成看板数据")

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

        with patch("scripts.radar.server.cdp.active_bilibili_cdp_port", return_value=None):
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

    def test_maintenance_issues_skips_successful_collection_window_zero(self):
        issues = maintenance_issues_from_status(
            {
                "sites": [
                    {
                        "site_id": "mediacrawler_xhs",
                        "site_name": "MediaCrawler Xiaohongshu",
                        "ok": True,
                        "item_count": 0,
                        "raw_item_count": 5,
                        "window_item_count": 0,
                        "collection_window_hours": 2,
                    }
                ]
            }
        )

        self.assertEqual(issues, [])

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

    def test_local_status_payload_preserves_collection_window_counts(self):
        root = Path(self.create_temp_dir())
        data_dir = root / "data"
        data_dir.mkdir()
        (data_dir / "source-status.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-07-06T00:00:00+08:00",
                    "source_scope": "since_last",
                    "fetched_raw_items": 5,
                    "collection_window_hours": 2,
                    "raw_items_before_collection_window": 5,
                    "skipped_collection_window_items": 3,
                    "successful_sites": 1,
                    "sites": [
                        {
                            "site_id": "opmlrss",
                            "site_name": "RSS/OPML",
                            "ok": True,
                            "item_count": 5,
                            "raw_item_count": 5,
                            "window_item_count": 2,
                            "collection_window_hours": 2,
                            "max_items_per_feed": 5,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        payload = local_status_payload(root)
        source_status = payload["source_status"]
        site_status = source_status["sites"][0]

        self.assertEqual(source_status["collection_window_hours"], 2)
        self.assertEqual(source_status["raw_items_before_collection_window"], 5)
        self.assertEqual(source_status["skipped_collection_window_items"], 3)
        self.assertEqual(site_status["raw_item_count"], 5)
        self.assertEqual(site_status["window_item_count"], 2)
        self.assertEqual(site_status["collection_window_hours"], 2)
        self.assertEqual(site_status["max_items_per_feed"], 5)

    def test_local_status_payload_treats_collector_window_zero_as_no_new(self):
        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        crawler_root = root.parent / "MediaCrawler-local-test"
        output_dir = crawler_root / "output" / "xhs" / "jsonl"
        output_dir.mkdir(parents=True)
        data_dir = root / "data"
        data_dir.mkdir(parents=True)
        data_dir.joinpath("source-status.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-07-07T09:21:23Z",
                    "sites": [
                        {
                            "site_id": "mediacrawler_xhs",
                            "site_name": "MediaCrawler Xiaohongshu",
                            "ok": False,
                            "item_count": 0,
                            "error": "mediacrawler_xhs_no_items",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        root.joinpath(CONFIG_FILENAME).write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "sources": [
                        {
                            "id": "mediacrawler_xhs_test",
                            "name": "小红书测试",
                            "type": "mediacrawler_jsonl",
                            "channel": "小红书",
                            "locator": str(output_dir),
                            "enabled": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        jsonl = output_dir / "creator_contents_2026-07-07.jsonl"
        jsonl.write_text('{"title":"old one"}\n{"title":"old two"}\n', encoding="utf-8")
        (crawler_root / "mediacrawler-xhs-collection-window.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "path": str(jsonl),
                    "file": jsonl.name,
                    "window_hours": 24,
                    "total": 2,
                    "kept": 0,
                    "skipped": 2,
                }
            ),
            encoding="utf-8",
        )
        (crawler_root / "mediacrawler-xhs.err.log").write_text(
            "2026-07-07 16:11:34 MediaCrawler INFO (core.py:127) - [XiaoHongShuCrawler.start] Xhs Crawler finished ...\n",
            encoding="utf-8",
        )

        payload = local_status_payload(root)

        self.assertEqual(payload["collectors"]["mediacrawler_xhs"]["item_count"], 0)
        self.assertEqual(payload["collectors"]["mediacrawler_xhs"]["raw_item_count"], 2)
        self.assertEqual(payload["source_status"]["maintenance_issues"], [])
        self.assertFalse(payload["source_status"]["needs_attention"])

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
        self.assertEqual(result["collection_scope"], "24h")
        self.assertIn("--collect-window-hours", result["command"])
        self.assertEqual(result["command"][result["command"].index("--collect-window-hours") + 1], "24")
        self.assertIn("--max-notes", result["command"])
        self.assertEqual(result["command"][result["command"].index("--max-notes") + 1], "5")
        self.assertNotIn("url", result)

    def test_start_mediacrawler_douyin_dry_run_uses_creator_id_from_homepage_url(self):
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
        self.assertIn("MS4wLjABAAAAOzTvIhQXaHWi6jT_P5rG5xEWpWPjufiK", result["command"])
        self.assertNotIn(homepage_url, result["command"])
        self.assertIn("--collect-window-hours", result["command"])

    def test_start_mediacrawler_douyin_dry_run_uses_all_enabled_homepage_urls(self):
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
        first_url = "https://www.douyin.com/user/MS4wLjABAAAA_FIRST"
        second_url = "https://www.douyin.com/user/MS4wLjABAAAA_SECOND"
        (root / CONFIG_FILENAME).write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "sources": [
                        {
                            "id": "mediacrawler_douyin_first",
                            "name": "第一个抖音号",
                            "type": "mediacrawler_jsonl",
                            "channel": "抖音",
                            "locator": first_url,
                            "enabled": True,
                        },
                        {
                            "id": "mediacrawler_douyin_second",
                            "name": "第二个抖音号",
                            "type": "mediacrawler_jsonl",
                            "channel": "抖音",
                            "locator": second_url,
                            "enabled": True,
                        },
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
        creator_id = result["command"][result["command"].index("--creator-id") + 1]
        self.assertEqual(creator_id, "MS4wLjABAAAA_FIRST,MS4wLjABAAAA_SECOND")
        self.assertIn("--collect-window-hours", result["command"])

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
        self.assertEqual(result["collection_scope"], "24h")
        self.assertIn("--collect-window-hours", result["command"])
        self.assertEqual(result["command"][result["command"].index("--collect-window-hours") + 1], "24")
        self.assertIn("--max-notes", result["command"])
        self.assertEqual(result["command"][result["command"].index("--max-notes") + 1], "5")

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
        self.assertIn("--collect-window-hours", result["command"])

    def test_start_mediacrawler_xhs_all_scope_keeps_full_history_command(self):
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
            result = start_mediacrawler_xhs(root, execute=False, collection_scope="all")
        finally:
            if old_dir is None:
                os.environ.pop("MEDIACRAWLER_LOCAL_DIR", None)
            else:
                os.environ["MEDIACRAWLER_LOCAL_DIR"] = old_dir

        self.assertTrue(result["ok"])
        self.assertEqual(result["collection_scope"], "all")
        self.assertNotIn("--collect-window-hours", result["command"])
        self.assertIn("--max-notes", result["command"])
        self.assertEqual(result["command"][result["command"].index("--max-notes") + 1], "500")

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

    def test_mediacrawler_collector_status_skips_latest_empty_jsonl(self):
        import os
        import time

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        crawler_root = root.parent / "MediaCrawler-local-test"
        output_dir = crawler_root / "output" / "douyin" / "jsonl"
        output_dir.mkdir(parents=True)
        older = output_dir / "creator_contents_2026-07-03.jsonl"
        older.write_text('{"title":"one"}\n{"title":"two"}\n', encoding="utf-8")
        latest_empty = output_dir / "creator_contents_2026-07-04.jsonl"
        latest_empty.write_text("", encoding="utf-8")
        now = time.time()
        os.utime(older, (now - 3600, now - 3600))
        os.utime(latest_empty, (now, now))

        status = mediacrawler_douyin_collector_status(root)

        self.assertEqual(status["latest_file"], older.name)
        self.assertEqual(status["item_count"], 2)
        self.assertEqual(status["raw_item_count"], 2)

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

    def test_mediacrawler_collector_status_reports_window_count_without_losing_raw_count(self):
        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        crawler_root = root.parent / "MediaCrawler-local-test"
        output_dir = crawler_root / "output" / "douyin" / "jsonl"
        output_dir.mkdir(parents=True)
        jsonl = output_dir / "creator_contents_2026-07-04.jsonl"
        jsonl.write_text('{"title":"old one"}\n{"title":"old two"}\n', encoding="utf-8")
        summary = crawler_root / "mediacrawler-douyin-collection-window.json"
        summary.write_text(
            json.dumps(
                {
                    "ok": True,
                    "path": str(jsonl),
                    "file": jsonl.name,
                    "window_hours": 24,
                    "total": 2,
                    "kept": 0,
                    "skipped": 2,
                }
            ),
            encoding="utf-8",
        )

        status = mediacrawler_douyin_collector_status(root)

        self.assertEqual(status["item_count"], 0)
        self.assertEqual(status["raw_item_count"], 2)
        self.assertEqual(status["collection_window_hours"], 24)
        self.assertEqual(status["skipped_collection_window_items"], 2)

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
        self.assertIn("MS4wLjABAAAAOzTvIhQXaHWi6jT_P5rG5xEWpWPjufiK", result["command"])
        self.assertNotIn(homepage_url, result["command"])
        self.assertIn("--collect-window-hours", result["command"])

    def test_perform_maintenance_action_can_start_we_mp_rss_without_current_issue(self):
        import os

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        root.mkdir(parents=True)
        sidecar_root = root.parent / "we-mp-rss-sidecar-test"
        sidecar_root.mkdir(parents=True)
        (sidecar_root / "main.py").write_text("print('fake')\n", encoding="utf-8")
        python_dir = sidecar_root / ".venv" / "Scripts"
        python_dir.mkdir(parents=True)
        python_exe = python_dir / "python.exe"
        python_exe.write_text("", encoding="utf-8")

        saved = {
            key: os.environ.get(key)
            for key in ("WE_MP_RSS_SIDECAR_DIR", "WE_MP_RSS_BASE_URL")
        }
        # 指向没人监听的本地端口，让运行探测确定性返回 False，从而走 dry-run 命令分支。
        os.environ["WE_MP_RSS_SIDECAR_DIR"] = str(sidecar_root)
        os.environ["WE_MP_RSS_BASE_URL"] = "http://127.0.0.1:8009"
        try:
            result = perform_maintenance_action(root, "start_we_mp_rss_sidecar", execute=False)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        # 关键：维护项列表为空（健康状态）下仍可派发，不再是 maintenance_action_not_found。
        self.assertTrue(result["ok"])
        self.assertFalse(result["executed"])
        self.assertEqual(Path(result["command"][0]), python_exe)
        self.assertEqual(Path(result["command"][1]), sidecar_root / "main.py")

    def test_perform_maintenance_action_start_wewe_rss_reaches_handler_without_issue(self):
        import os

        root = Path(self.create_temp_dir()) / "ai-news-radar-run"
        root.mkdir(parents=True)

        saved = os.environ.get("WEWE_RSS_BASE_URL")
        # 指向死端口，确保不会命中 already_running；此测只验证路由到达 handler。
        os.environ["WEWE_RSS_BASE_URL"] = "http://127.0.0.1:4009"
        try:
            result = perform_maintenance_action(root, "start_wewe_rss_sidecar", execute=False)
        finally:
            if saved is None:
                os.environ.pop("WEWE_RSS_BASE_URL", None)
            else:
                os.environ["WEWE_RSS_BASE_URL"] = saved

        # 无维护项时路由仍到达 handler：不应再是 maintenance_action_not_found。
        self.assertNotEqual(result.get("error"), "maintenance_action_not_found")

    def test_perform_maintenance_action_can_start_mediacrawler_all_scope(self):
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
            result = perform_maintenance_action(root, "start_mediacrawler_douyin", execute=False, collection_scope="all")
        finally:
            if old_dir is None:
                os.environ.pop("MEDIACRAWLER_LOCAL_DIR", None)
            else:
                os.environ["MEDIACRAWLER_LOCAL_DIR"] = old_dir

        self.assertTrue(result["ok"])
        self.assertEqual(result["collection_scope"], "all")
        self.assertNotIn("--collect-window-hours", result["command"])

    def create_temp_dir(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory(prefix="ai-news-radar-local-server-test-")
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def git(self, root, *args):
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def online_source_payload(self, name):
        return {
            "sources": [
                {
                    "name": name,
                    "type": "rss",
                    "locator": f"https://example.com/{name}.xml",
                }
            ]
        }

    def create_sync_git_repositories(self, initial_payload=None):
        base = Path(self.create_temp_dir())
        origin = base / "origin.git"
        root = base / "local"
        peer = base / "peer"
        self.git(base, "init", "--bare", str(origin))
        root.mkdir()
        self.git(root, "init", "-b", "master")
        self.git(root, "config", "user.name", "Test")
        self.git(root, "config", "user.email", "test@example.com")
        self.git(root, "config", "core.autocrlf", "false")
        data_path = root / "data" / "latest-24h.json"
        data_path.parent.mkdir()
        data_path.write_text('{"version":"initial"}\n', encoding="utf-8")
        (root / "README.md").write_text("init\n", encoding="utf-8")
        self.git(root, "add", "README.md", "data/latest-24h.json")
        self.git(root, "commit", "-m", "init")
        if initial_payload is not None:
            sync_online_source_config(root, initial_payload, push=False)
        self.git(root, "remote", "add", "origin", str(origin))
        self.git(root, "push", "-u", "origin", "master")
        self.git(base, "clone", str(origin), str(peer))
        self.git(peer, "config", "user.name", "Test")
        self.git(peer, "config", "user.email", "test@example.com")
        self.git(peer, "config", "core.autocrlf", "false")
        return root, origin, peer


class LocalGitHubStarsApiTests(unittest.TestCase):
    class QuietHandler(LocalRadarHandler):
        def log_message(self, _format, *args):
            return

    def setUp(self):
        self.temp_dir = self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="github-stars-api-")
        )
        self.root = Path(self.temp_dir)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.QuietHandler)
        self.server.root_dir = str(self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, path, payload=None, *, content_type="application/json", headers=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        request_headers = {"Origin": origin, "Referer": origin + "/"}
        if body is not None:
            request_headers["Content-Type"] = content_type
            request_headers["Content-Length"] = str(len(body))
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, dict(response.getheaders()), json.loads(raw.decode("utf-8"))
        finally:
            connection.close()

    @patch("scripts.local_server.preview_github_star_sync")
    def test_preview_route_uses_strict_json_gate_and_small_body(self, preview_mock):
        preview_mock.return_value = {
            "ok": True,
            "preview_hash": "1" * 64,
            "base_config_digest": "2" * 64,
        }

        status, _headers, body = self.request(
            "POST",
            "/api/github-stars/preview",
            {"username": "example-user"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        preview_mock.assert_called_once_with(self.root, {"username": "example-user"})

        preview_mock.reset_mock()
        status, _headers, body = self.request(
            "POST",
            "/api/github-stars/preview",
            {"username": "example-user"},
            content_type="application/json-evil",
        )
        self.assertEqual(status, 415)
        self.assertEqual(body["error"], "json_required")
        preview_mock.assert_not_called()

        status, _headers, body = self.request(
            "POST",
            "/api/github-stars/preview",
            {"username": "x" * 5000},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_content_length")
        preview_mock.assert_not_called()

    @patch("scripts.local_server.apply_github_star_sync")
    def test_apply_rejects_client_summary_before_service(self, apply_mock):
        status, _headers, body = self.request(
            "POST",
            "/api/github-stars/apply",
            {
                "account_id": 12345678,
                "preview_hash": "1" * 64,
                "summary": {"added": []},
            },
        )

        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_request_fields")
        apply_mock.assert_not_called()

    @patch("scripts.local_server.preview_github_star_sync")
    def test_structured_service_error_does_not_return_exception_text(self, preview_mock):
        preview_mock.side_effect = online_sources.OnlineSourcesError(
            "online_sources_busy",
            status_code=409,
        )

        status, _headers, body = self.request(
            "POST",
            "/api/github-stars/preview",
            {"username": "example-user"},
        )

        self.assertEqual(status, 409)
        self.assertEqual(body, {"ok": False, "error": "online_sources_busy"})

    def test_get_online_config_emits_matching_http_etag(self):
        source = {
            "id": "rss_one",
            "name": "Feed One",
            "type": "rss",
            "enabled": True,
            "channel": "RSS/YouTube",
            "target": "Feed One",
            "locator": "https://example.com/one.xml",
            "env": "",
            "notes": "public feed",
        }
        config = online_sources.build_online_config(
            [source],
            updated_at="2026-07-16T00:00:00Z",
        )
        online_sources.write_json_atomic(online_sources.online_config_path(self.root), config)
        online_sources.write_online_opml(self.root, [source])
        with patch.object(online_sources, "audit_online_source_operation", return_value=None):
            status, headers, body = self.request("GET", "/api/online-source-config")

        self.assertEqual(status, 200)
        self.assertEqual(headers["ETag"], body["etag"])
        self.assertEqual(body["recovery"], None)

    @patch("scripts.local_server.save_online_source_config")
    def test_save_requires_if_match_before_service(self, save_mock):
        status, _headers, body = self.request(
            "POST",
            "/api/online-source-config",
            {"sources": []},
        )

        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "online_sources_config_stale")
        save_mock.assert_not_called()

    @patch("scripts.local_server.save_online_source_config")
    def test_save_maps_managed_field_violation_without_leaking_text(self, save_mock):
        save_mock.side_effect = ValueError(
            "github_star_managed_fields_readonly: secret payload details"
        )
        status, _headers, body = self.request(
            "POST",
            "/api/online-source-config",
            {"sources": []},
            headers={"If-Match": '"' + "7" * 64 + '"'},
        )

        self.assertEqual(status, 409)
        self.assertEqual(body, {"ok": False, "error": "github_star_managed_fields_readonly"})
        self.assertNotIn("secret", json.dumps(body))

    @patch("scripts.local_server.unbind_github_star_sync")
    def test_unbind_passes_if_match_and_returns_new_etag(self, unbind_mock):
        etag = '"' + "4" * 64 + '"'
        unbind_mock.return_value = {
            "ok": True,
            "outcome": "pushed",
            "etag": etag,
        }

        status, headers, body = self.request(
            "POST",
            "/api/github-stars/unbind",
            {"account_id": 12345678, "confirmed": True},
            headers={"If-Match": '"' + "3" * 64 + '"'},
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["ETag"], etag)
        self.assertEqual(body["outcome"], "pushed")
        unbind_mock.assert_called_once_with(
            self.root,
            {"account_id": 12345678, "confirmed": True},
            if_match='"' + "3" * 64 + '"',
        )

    @patch("scripts.radar.server.online_sources.recover_online_source_operation")
    def test_recovery_route_maps_stale_manifest_to_409(self, recovery_mock):
        recovery_mock.side_effect = online_sources.OnlineSourcesError(
            "online_sources_recovery_mismatch",
            status_code=409,
        )

        status, _headers, body = self.request(
            "POST",
            "/api/online-source-config/recovery",
            {
                "action": "retry_push",
                "operation_id": "old-operation",
                "manifest_digest": "5" * 64,
            },
        )

        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "online_sources_recovery_mismatch")


if __name__ == "__main__":
    unittest.main()
