from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.update_news import (
    BROWSER_UA,
    backfill_bilibili_archive_publish_times,
    bilibili_dynamic_accounts_from_env,
    bilibili_dynamic_status_base,
    bilibili_dynamic_item_title,
    bilibili_cookie_header_from_file_text,
    fetch_bilibili_dynamic,
    fetch_bilibili_opus_published_at,
    fetch_bilibili_full_dynamic,
    bilibili_wbi_keys,
    sign_bilibili_wbi_params,
    parse_bilibili_detail_published_at,
    parse_bilibili_full_dynamic_items,
    parse_bilibili_dynamic_items,
    parse_mediacrawler_douyin_jsonl,
    maybe_fetch_mediacrawler_douyin,
    parse_mediacrawler_xhs_jsonl,
    maybe_fetch_mediacrawler_xhs,
    parse_jike_public_items,
    parse_telegram_public_items,
    fetch_opml_rss,
    resolve_opml_bridge_source,
)


class PrivateBridgeSourceTests(unittest.TestCase):
    def test_bilibili_default_collects_latest_five_per_account(self):
        with patch.dict(os.environ, {"BILIBILI_DYNAMIC_ENABLED": "1"}, clear=True):
            status = bilibili_dynamic_status_base()

        self.assertEqual(status["max_items"], 5)
        self.assertEqual(status["max_items_per_account"], 5)

    def test_opml_rss_keeps_latest_five_items_per_feed(self):
        class Response:
            def __init__(self, text: str):
                self.text = text
                self.content = text.encode("utf-8")

            def raise_for_status(self) -> None:
                return None

        now = datetime(2026, 7, 6, tzinfo=timezone.utc)
        entries = "\n".join(
            f"""
            <item>
              <title>Video {index}</title>
              <link>https://www.youtube.com/watch?v={index}</link>
              <pubDate>Mon, {index:02d} Jun 2026 00:00:00 GMT</pubDate>
            </item>
            """
            for index in range(1, 9)
        )
        rss = f"<rss><channel><title>Test YouTube</title>{entries}</channel></rss>"
        with tempfile.TemporaryDirectory() as tmp:
            opml = Path(tmp) / "follow.opml"
            opml.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
                <opml version="1.0"><body>
                  <outline text="Test YouTube" title="Test YouTube" type="rss"
                    xmlUrl="https://www.youtube.com/feeds/videos.xml?channel_id=test" />
                </body></opml>
                """,
                encoding="utf-8",
            )
            with patch("scripts.radar.fetchers.subscriptions.requests.get", return_value=Response(rss)):
                items, summary, feed_statuses = fetch_opml_rss(now, opml)

        self.assertEqual(len(items), 5)
        self.assertEqual([item.title for item in items], ["Video 8", "Video 7", "Video 6", "Video 5", "Video 4"])
        self.assertEqual(summary["item_count"], 5)
        self.assertEqual(summary["max_items_per_feed"], 5)
        self.assertEqual(feed_statuses[0]["item_count"], 5)

    def test_resolves_rsshub_telegram_to_public_preview(self):
        bridge = resolve_opml_bridge_source("https://rsshub.app/telegram/channel/AI_News_CN")
        self.assertEqual(bridge["bridge_type"], "telegram")
        self.assertEqual(bridge["bridge_slug"], "AI_News_CN")
        self.assertEqual(bridge["url"], "https://t.me/s/AI_News_CN")

    def test_resolves_rsshub_jike_topic_to_mobile_page(self):
        bridge = resolve_opml_bridge_source("https://rsshub.app/jike/topic/63579abb6724cc583b9bba9a")
        self.assertEqual(bridge["bridge_type"], "jike")
        self.assertEqual(bridge["bridge_kind"], "topic")
        self.assertEqual(bridge["url"], "https://m.okjike.com/topics/63579abb6724cc583b9bba9a")

    def test_parse_telegram_public_items(self):
        html = """
        <div class="tgme_widget_message" data-post="AI_News_CN/123">
          <div class="tgme_widget_message_text">Claude Code 发布了新的 Agent 能力</div>
          <time datetime="2026-05-12T01:02:03+00:00"></time>
        </div>
        """
        items = parse_telegram_public_items(
            html,
            now=datetime(2026, 5, 12, tzinfo=timezone.utc),
            source_name="ChatGPT / AI新闻聚合",
            slug="AI_News_CN",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://t.me/AI_News_CN/123")
        self.assertEqual(items[0].meta["bridge_type"], "telegram")

    def test_parse_jike_public_items(self):
        payload = {
            "props": {
                "pageProps": {
                    "posts": [
                        {
                            "id": "post123",
                            "content": "Andrej Karpathy 讨论了 Agentic Engineering 与 Vibe Coding",
                            "createdAt": "2026-05-01T03:12:09.999Z",
                        }
                    ]
                }
            }
        }
        html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        items = parse_jike_public_items(
            html,
            now=datetime(2026, 5, 12, tzinfo=timezone.utc),
            source_name="AI探索站 - 即刻圈子",
            source_url="https://m.okjike.com/topics/63579abb6724cc583b9bba9a",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://m.okjike.com/originalPosts/post123")
        self.assertEqual(items[0].meta["bridge_type"], "jike")

    def test_parse_bilibili_dynamic_items(self):
        payload = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "content": "今晚 20:00，我在 B 站直播。\n聊 Agent 和模型生态。",
                        "jump_url": "//www.bilibili.com/opus/1192170157065109508",
                        "opus_id": "1192170157065109508",
                        "stat": {"like": "4"},
                        "cover": {"url": "http://i0.hdslb.com/example.jpg"},
                    }
                ]
            },
        }
        items = parse_bilibili_dynamic_items(
            payload,
            now=datetime(2026, 6, 30, tzinfo=timezone.utc),
            uid="505301413",
            source_name="Koji杨远骋at十字路口",
            max_items=20,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].site_id, "bilibili_dynamic")
        self.assertEqual(items[0].source, "Koji杨远骋at十字路口")
        self.assertEqual(items[0].url, "https://www.bilibili.com/opus/1192170157065109508")
        self.assertIsNone(items[0].published_at)
        self.assertEqual(items[0].meta["creator_metrics"]["like_count"], "4")
        self.assertEqual(items[0].meta["timestamp_source"], "first_seen_at")

    def test_parse_bilibili_dynamic_items_uses_detail_publish_time(self):
        payload = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "content": "2024新年快乐！",
                        "jump_url": "//www.bilibili.com/opus/880862393292292098",
                        "opus_id": "880862393292292098",
                        "stat": {"like": "1896"},
                    }
                ]
            },
        }
        published_at = datetime(2023, 12, 30, 9, 55, 58, tzinfo=timezone.utc)
        items = parse_bilibili_dynamic_items(
            payload,
            now=datetime(2026, 7, 4, tzinfo=timezone.utc),
            uid="4401694",
            source_name="林亦LY",
            max_items=20,
            published_at_by_opus={"880862393292292098": published_at},
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].published_at, published_at)
        self.assertEqual(items[0].meta["timestamp_source"], "bilibili_opus_detail_pub_ts")

    def test_bilibili_dynamic_item_title_truncates_long_content(self):
        title = bilibili_dynamic_item_title("A" * 120, "123")
        self.assertLessEqual(len(title), 90)
        self.assertTrue(title.endswith("..."))

    def test_bilibili_dynamic_default_accounts_include_tech_shrimp(self):
        with patch.dict(os.environ, {}, clear=True):
            accounts = bilibili_dynamic_accounts_from_env()
        self.assertEqual(
            accounts,
            [
                {"uid": "505301413", "source_name": "Koji杨远骋at十字路口"},
                {"uid": "316183842", "source_name": "技术爬爬虾"},
            ],
        )

    def test_bilibili_dynamic_accounts_from_uid_lists(self):
        with patch.dict(
            os.environ,
            {
                "BILIBILI_DYNAMIC_UIDS": "1,2",
                "BILIBILI_DYNAMIC_SOURCE_NAMES": "账号一,账号二",
            },
            clear=True,
        ):
            accounts = bilibili_dynamic_accounts_from_env()
        self.assertEqual(
            accounts,
            [
                {"uid": "1", "source_name": "账号一"},
                {"uid": "2", "source_name": "账号二"},
            ],
        )

    def test_bilibili_dynamic_accounts_keep_single_uid_compatibility(self):
        with patch.dict(
            os.environ,
            {
                "BILIBILI_DYNAMIC_UID": "9",
                "BILIBILI_DYNAMIC_SOURCE_NAME": "旧配置账号",
            },
            clear=True,
        ):
            accounts = bilibili_dynamic_accounts_from_env()
        self.assertEqual(accounts, [{"uid": "9", "source_name": "旧配置账号"}])

    def test_parse_mediacrawler_douyin_jsonl(self):
        payload = {
            "aweme_id": "7656358189943786803",
            "desc": "分享一个 Claude Code 工作流",
            "aweme_url": "https://www.douyin.com/video/7656358189943786803",
            "create_time": 1782634811,
            "nickname": "Simon林",
            "liked_count": "120",
            "collected_count": "8",
            "comment_count": "3",
            "share_count": "2",
            "sec_user_id": "MS4wLjABAAAACsVv",
        }
        items = parse_mediacrawler_douyin_jsonl(
            json.dumps(payload, ensure_ascii=False),
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].site_id, "mediacrawler_douyin")
        self.assertEqual(items[0].source, "Simon林")
        self.assertEqual(items[0].url, "https://www.douyin.com/video/7656358189943786803")
        self.assertEqual(items[0].meta["creator_metrics"]["likes"], 120)
        self.assertEqual(items[0].meta["creator_metrics"]["collects"], 8)
        self.assertEqual(items[0].meta["creator_metrics"]["comments"], 3)
        self.assertEqual(items[0].meta["creator_metrics"]["shares"], 2)

    def test_mediacrawler_douyin_defaults_to_local_output_dir_when_enabled(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "MEDIACRAWLER_DOUYIN_ENABLED": "1",
                    "MEDIACRAWLER_LOCAL_DIR": tmp,
                },
                clear=True,
            ):
                items, status = maybe_fetch_mediacrawler_douyin(datetime(2026, 7, 1, tzinfo=timezone.utc))

        self.assertEqual(items, [])
        self.assertFalse(status["ok"])
        self.assertEqual(status["error"], "mediacrawler_douyin_jsonl_not_found")
        self.assertEqual(status["locator_kind"], "jsonl_path")
        self.assertEqual(status["jsonl_file"], "jsonl")

    def test_mediacrawler_douyin_homepage_url_reads_default_jsonl_dir(self):
        import tempfile

        payload = {
            "aweme_id": "new",
            "desc": "主页链接配置后的抖音作品",
            "aweme_url": "https://www.douyin.com/video/new",
            "nickname": "Simon林",
        }
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_dir = Path(tmp) / "output" / "douyin" / "jsonl"
            jsonl_dir.mkdir(parents=True)
            (jsonl_dir / "creator_contents_2026-07-04.jsonl").write_text(
                json.dumps(payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "MEDIACRAWLER_DOUYIN_ENABLED": "1",
                    "MEDIACRAWLER_DOUYIN_JSONL": "https://www.douyin.com/user/MS4wLjABAAAA_TEST",
                    "MEDIACRAWLER_LOCAL_DIR": tmp,
                },
                clear=True,
            ):
                items, status = maybe_fetch_mediacrawler_douyin(datetime(2026, 7, 4, tzinfo=timezone.utc))

        self.assertTrue(status["ok"])
        self.assertEqual(status["locator_kind"], "homepage_url")
        self.assertEqual(status["jsonl_file"], "creator_contents_2026-07-04.jsonl")
        self.assertEqual(items[0].meta["douyin_aweme_id"], "new")

    def test_mediacrawler_douyin_homepage_subscription_reads_default_jsonl_dir(self):
        import tempfile
        from scripts.update_news import fetch_mediacrawler_douyin_subscriptions

        payload = {
            "aweme_id": "sub",
            "desc": "订阅 GUI 写入主页链接",
            "aweme_url": "https://www.douyin.com/video/sub",
            "nickname": "JSONL昵称",
            "sec_user_id": "MS4wLjABAAAA_TEST",
        }
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_dir = Path(tmp) / "output" / "douyin" / "jsonl"
            jsonl_dir.mkdir(parents=True)
            (jsonl_dir / "creator_contents_2026-07-04.jsonl").write_text(
                json.dumps(payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"MEDIACRAWLER_LOCAL_DIR": tmp}, clear=True):
                items, status = fetch_mediacrawler_douyin_subscriptions(
                    [
                        {
                            "name": "Simon林",
                            "target": "Simon林",
                            "locator": "https://www.douyin.com/user/MS4wLjABAAAA_TEST",
                        }
                    ],
                    datetime(2026, 7, 4, tzinfo=timezone.utc),
                )

        self.assertTrue(status["ok"])
        self.assertEqual(status["subscription_count"], 1)
        self.assertEqual(status["subscriptions"][0]["locator_kind"], "homepage_url")
        self.assertEqual(items[0].source, "JSONL昵称")

    def test_mediacrawler_douyin_homepage_subscription_filters_by_sec_uid(self):
        import tempfile
        from scripts.update_news import fetch_mediacrawler_douyin_subscriptions

        payload = {
            "aweme_id": "jennie",
            "desc": "珍妮丁丁说AI 的新作品",
            "aweme_url": "https://www.douyin.com/video/jennie",
            "nickname": "珍妮丁丁说AI",
            "sec_user_id": "MS4wLjABAAAA_JENNIE",
        }
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_dir = Path(tmp) / "output" / "douyin" / "jsonl"
            jsonl_dir.mkdir(parents=True)
            old_simon_path = jsonl_dir / "creator_contents_2026-07-01.jsonl"
            latest_path = jsonl_dir / "creator_contents_2026-07-04.jsonl"
            old_simon_path.write_text(
                json.dumps(
                    {
                        "aweme_id": "simon-old",
                        "desc": "Simon 旧作品",
                        "aweme_url": "https://www.douyin.com/video/simon-old",
                        "nickname": "Simon林",
                        "sec_user_id": "MS4wLjABAAAA_SIMON",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            latest_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
            os.utime(old_simon_path, (100, 100))
            os.utime(latest_path, (200, 200))
            with patch.dict(os.environ, {"MEDIACRAWLER_LOCAL_DIR": tmp}, clear=True):
                items, status = fetch_mediacrawler_douyin_subscriptions(
                    [
                        {
                            "name": "Simon林",
                            "target": "Simon林",
                            "locator": str(old_simon_path),
                        },
                        {
                            "name": "珍妮丁丁说AI",
                            "target": "珍妮丁丁说AI",
                            "locator": "https://www.douyin.com/user/MS4wLjABAAAA_JENNIE",
                        },
                    ],
                    datetime(2026, 7, 4, tzinfo=timezone.utc),
                )

        self.assertTrue(status["ok"])
        self.assertEqual(status["subscription_count"], 2)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "珍妮丁丁说AI")
        self.assertEqual(items[0].meta["douyin_sec_user_id"], "MS4wLjABAAAA_JENNIE")
        self.assertEqual(status["subscriptions"][0]["item_count"], 0)
        self.assertEqual(status["subscriptions"][1]["item_count"], 1)

    def test_creator_hot_dedupe_prefers_latest_confirmed_douyin_source(self):
        from scripts.update_news import build_creator_hot_items, make_item_id

        url = "https://www.douyin.com/video/7657434518546091305"
        title = "看看普通人到底都在vibe coding啥"
        archive = {}
        old_id = make_item_id("mediacrawler_douyin", "Simon林", title, url)
        new_id = make_item_id("mediacrawler_douyin", "珍妮丁丁说AI", title, url)
        archive[old_id] = {
            "id": old_id,
            "site_id": "mediacrawler_douyin",
            "site_name": "MediaCrawler Douyin",
            "source": "Simon林",
            "title": title,
            "url": url,
            "published_at": "2026-07-01T12:30:00Z",
            "first_seen_at": "2026-07-03T10:00:00Z",
            "last_seen_at": "2026-07-03T10:00:00Z",
        }
        archive[new_id] = {
            "id": new_id,
            "site_id": "mediacrawler_douyin",
            "site_name": "MediaCrawler Douyin",
            "source": "珍妮丁丁说AI",
            "title": title,
            "url": url,
            "published_at": "2026-07-01T12:30:00Z",
            "first_seen_at": "2026-07-03T10:00:00Z",
            "last_seen_at": "2026-07-04T06:30:00Z",
        }

        items = build_creator_hot_items(archive, datetime(2026, 7, 4, tzinfo=timezone.utc), ai_only=False)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "珍妮丁丁说AI")

    def test_mediacrawler_douyin_missing_explicit_path_still_reports_missing_file(self):
        with patch.dict(os.environ, {"MEDIACRAWLER_DOUYIN_ENABLED": "1", "MEDIACRAWLER_DOUYIN_JSONL": "missing.jsonl"}, clear=True):
            items, status = maybe_fetch_mediacrawler_douyin(datetime(2026, 7, 1, tzinfo=timezone.utc))
        self.assertEqual(items, [])
        self.assertFalse(status["ok"])
        self.assertEqual(status["error"], "mediacrawler_douyin_jsonl_not_found")

    def test_mediacrawler_douyin_reads_newer_jsonl_sibling(self):
        import tempfile

        old_payload = {
            "aweme_id": "old",
            "desc": "旧作品",
            "aweme_url": "https://www.douyin.com/video/old",
            "nickname": "Simon林",
        }
        new_payload = {
            "aweme_id": "new",
            "desc": "新作品",
            "aweme_url": "https://www.douyin.com/video/new",
            "nickname": "Simon林",
        }
        with tempfile.TemporaryDirectory() as tmp:
            old_path = Path(tmp) / "creator_contents_2026-07-01.jsonl"
            new_path = Path(tmp) / "creator_contents_2026-07-03.jsonl"
            old_path.write_text(json.dumps(old_payload, ensure_ascii=False) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(new_payload, ensure_ascii=False) + "\n", encoding="utf-8")
            os.utime(old_path, (100, 100))
            os.utime(new_path, (200, 200))
            with patch.dict(
                os.environ,
                {
                    "MEDIACRAWLER_DOUYIN_ENABLED": "1",
                    "MEDIACRAWLER_DOUYIN_JSONL": str(old_path),
                },
                clear=True,
            ):
                items, status = maybe_fetch_mediacrawler_douyin(datetime(2026, 7, 3, tzinfo=timezone.utc))

        self.assertTrue(status["ok"])
        self.assertEqual(status["jsonl_file"], "creator_contents_2026-07-03.jsonl")
        self.assertEqual(status["jsonl_file_resolved_from"], "creator_contents_2026-07-01.jsonl")
        self.assertEqual(items[0].meta["douyin_aweme_id"], "new")

    def test_parse_mediacrawler_xhs_jsonl(self):
        payload = {
            "note_id": "6a441088000000000702c7df",
            "type": "video",
            "title": "【开箱】小米NAS终于来了...",
            "desc": "#开箱[话题]# #小米NAS[话题]#",
            "note_url": "https://www.xiaohongshu.com/explore/6a441088000000000702c7df",
            "time": 1782871245000,
            "nickname": "陈抱一",
            "user_id": "5e4027000000000001005eb8",
            "liked_count": "1393",
            "collected_count": "484",
            "comment_count": "464",
            "share_count": "2446",
        }
        items = parse_mediacrawler_xhs_jsonl(
            json.dumps(payload, ensure_ascii=False),
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].site_id, "mediacrawler_xhs")
        self.assertEqual(items[0].source, "陈抱一")
        self.assertEqual(items[0].url, "https://www.xiaohongshu.com/explore/6a441088000000000702c7df")
        self.assertEqual(items[0].meta["creator_metrics"]["likes"], 1393)
        self.assertEqual(items[0].meta["creator_metrics"]["collects"], 484)
        self.assertEqual(items[0].meta["creator_metrics"]["comments"], 464)
        self.assertEqual(items[0].meta["creator_metrics"]["shares"], 2446)
        self.assertEqual(items[0].meta["xiaohongshu_note_id"], "6a441088000000000702c7df")

    def test_mediacrawler_xhs_defaults_to_local_output_dir_when_enabled(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "MEDIACRAWLER_XHS_ENABLED": "1",
                    "MEDIACRAWLER_LOCAL_DIR": tmp,
                },
                clear=True,
            ):
                items, status = maybe_fetch_mediacrawler_xhs(datetime(2026, 7, 1, tzinfo=timezone.utc))

        self.assertEqual(items, [])
        self.assertFalse(status["ok"])
        self.assertEqual(status["error"], "mediacrawler_xhs_jsonl_not_found")
        self.assertEqual(status["locator_kind"], "jsonl_path")
        self.assertEqual(status["jsonl_file"], "jsonl")

    def test_mediacrawler_xhs_homepage_url_reads_default_jsonl_dir(self):
        import tempfile

        payload = {
            "note_id": "6a441088000000000702c7df",
            "title": "小红书主页链接配置后的笔记",
            "note_url": "https://www.xiaohongshu.com/explore/6a441088000000000702c7df",
            "nickname": "陈抱一",
            "user_id": "5e4027000000000001005eb8",
        }
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_dir = Path(tmp) / "output" / "xhs" / "jsonl"
            jsonl_dir.mkdir(parents=True)
            (jsonl_dir / "creator_contents_2026-07-04.jsonl").write_text(
                json.dumps(payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "MEDIACRAWLER_XHS_ENABLED": "1",
                    "MEDIACRAWLER_XHS_JSONL": "https://www.xiaohongshu.com/user/profile/5e4027000000000001005eb8",
                    "MEDIACRAWLER_LOCAL_DIR": tmp,
                },
                clear=True,
            ):
                items, status = maybe_fetch_mediacrawler_xhs(datetime(2026, 7, 4, tzinfo=timezone.utc))

        self.assertTrue(status["ok"])
        self.assertEqual(status["locator_kind"], "homepage_url")
        self.assertEqual(status["jsonl_file"], "creator_contents_2026-07-04.jsonl")
        self.assertEqual(items[0].source, "陈抱一")

    def test_mediacrawler_xhs_homepage_subscription_reads_default_jsonl_dir(self):
        import tempfile
        from scripts.update_news import fetch_mediacrawler_xhs_subscriptions

        payload = {
            "note_id": "6a441088000000000702c7df",
            "title": "订阅 GUI 写入主页链接",
            "note_url": "https://www.xiaohongshu.com/explore/6a441088000000000702c7df",
            "nickname": "JSONL昵称",
            "user_id": "5e4027000000000001005eb8",
        }
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_dir = Path(tmp) / "output" / "xhs" / "jsonl"
            jsonl_dir.mkdir(parents=True)
            (jsonl_dir / "creator_contents_2026-07-04.jsonl").write_text(
                json.dumps(payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"MEDIACRAWLER_LOCAL_DIR": tmp}, clear=True):
                items, status = fetch_mediacrawler_xhs_subscriptions(
                    [
                        {
                            "name": "陈抱一",
                            "target": "陈抱一",
                            "locator": "https://www.xiaohongshu.com/user/profile/5e4027000000000001005eb8",
                        }
                    ],
                    datetime(2026, 7, 4, tzinfo=timezone.utc),
                )

        self.assertTrue(status["ok"])
        self.assertEqual(status["subscription_count"], 1)
        self.assertEqual(status["subscriptions"][0]["locator_kind"], "homepage_url")
        self.assertEqual(items[0].source, "JSONL昵称")

    def test_mediacrawler_xhs_homepage_subscription_filters_by_user_id(self):
        import tempfile
        from scripts.update_news import fetch_mediacrawler_xhs_subscriptions

        payload = {
            "note_id": "new-note",
            "title": "新小红书博主的笔记",
            "note_url": "https://www.xiaohongshu.com/explore/new-note",
            "nickname": "新小红书博主",
            "user_id": "new_user_id",
        }
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_dir = Path(tmp) / "output" / "xhs" / "jsonl"
            jsonl_dir.mkdir(parents=True)
            old_path = jsonl_dir / "creator_contents_2026-07-01.jsonl"
            latest_path = jsonl_dir / "creator_contents_2026-07-04.jsonl"
            old_path.write_text(
                json.dumps(
                    {
                        "note_id": "old-note",
                        "title": "陈抱一旧笔记",
                        "note_url": "https://www.xiaohongshu.com/explore/old-note",
                        "nickname": "陈抱一",
                        "user_id": "old_user_id",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            latest_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
            os.utime(old_path, (100, 100))
            os.utime(latest_path, (200, 200))
            with patch.dict(os.environ, {"MEDIACRAWLER_LOCAL_DIR": tmp}, clear=True):
                items, status = fetch_mediacrawler_xhs_subscriptions(
                    [
                        {
                            "name": "陈抱一",
                            "target": "陈抱一",
                            "locator": "https://www.xiaohongshu.com/user/profile/old_user_id",
                        },
                        {
                            "name": "新小红书博主",
                            "target": "新小红书博主",
                            "locator": "https://www.xiaohongshu.com/user/profile/new_user_id",
                        },
                    ],
                    datetime(2026, 7, 4, tzinfo=timezone.utc),
                )

        self.assertTrue(status["ok"])
        self.assertEqual(status["subscription_count"], 2)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "新小红书博主")
        self.assertEqual(items[0].meta["xiaohongshu_user_id"], "new_user_id")
        self.assertEqual(status["subscriptions"][0]["item_count"], 0)
        self.assertEqual(status["subscriptions"][1]["item_count"], 1)

    def test_mediacrawler_xhs_missing_explicit_path_still_reports_missing_file(self):
        with patch.dict(os.environ, {"MEDIACRAWLER_XHS_ENABLED": "1", "MEDIACRAWLER_XHS_JSONL": "missing.jsonl"}, clear=True):
            items, status = maybe_fetch_mediacrawler_xhs(datetime(2026, 7, 1, tzinfo=timezone.utc))
        self.assertEqual(items, [])
        self.assertFalse(status["ok"])
        self.assertEqual(status["error"], "mediacrawler_xhs_jsonl_not_found")

    def test_bilibili_cookie_header_from_netscape_text(self):
        cookie_text = "\n".join(
            [
                "# Netscape HTTP Cookie File",
                ".example.com\tTRUE\t/\tFALSE\t1782817200\tignored\t1",
                "#HttpOnly_.bilibili.com\tTRUE\t/\tTRUE\t1782817200\tSESSDATA\tabc",
                ".bilibili.com\tTRUE\t/\tFALSE\t1782817200\tDedeUserID\t123",
                ".bilibili.com\tTRUE\t/\tFALSE\t1\texpired\told",
            ]
        )
        header = bilibili_cookie_header_from_file_text(cookie_text, now_ts=1780000000)
        self.assertIn("SESSDATA=abc", header)
        self.assertIn("DedeUserID=123", header)
        self.assertNotIn("ignored=1", header)
        self.assertNotIn("expired=old", header)

    def test_bilibili_cookie_header_from_json_export(self):
        cookie_text = json.dumps(
            [
                {
                    "domain": ".bilibili.com",
                    "name": "bili_jct",
                    "value": "csrf",
                    "expirationDate": 1782817200,
                },
                {
                    "domain": ".example.com",
                    "name": "ignored",
                    "value": "1",
                    "expirationDate": 1782817200,
                },
            ]
        )
        header = bilibili_cookie_header_from_file_text(cookie_text, now_ts=1780000000)
        self.assertEqual(header, "bili_jct=csrf")

    def test_parse_bilibili_full_dynamic_items(self):
        payload = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "id_str": "987654321",
                        "type": "DYNAMIC_TYPE_WORD",
                        "modules": {
                            "module_author": {"pub_ts": 1782817200},
                            "module_dynamic": {
                                "desc": {"text": "完整动态里的一条 Agent 更新"},
                                "major": {"opus": {"jump_url": "//www.bilibili.com/opus/987654321"}},
                            },
                        },
                    }
                ]
            },
        }
        items = parse_bilibili_full_dynamic_items(
            payload,
            now=datetime(2026, 6, 30, tzinfo=timezone.utc),
            uid="505301413",
            source_name="Koji杨远骋at十字路口",
            max_items=20,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://www.bilibili.com/opus/987654321")
        self.assertEqual(items[0].meta["bilibili_dynamic_type"], "DYNAMIC_TYPE_WORD")
        self.assertEqual(items[0].meta["timestamp_source"], "bilibili_pub_ts")

    def test_parse_bilibili_detail_published_at_accepts_module_author_dict(self):
        payload = {
            "code": 0,
            "data": {
                "item": {
                    "modules": {
                        "module_author": {
                            "pub_time": "2023年12月30日 17:55",
                            "pub_ts": 1703930158,
                        }
                    }
                }
            },
        }
        self.assertEqual(
            parse_bilibili_detail_published_at(payload),
            datetime.fromtimestamp(1703930158, tz=timezone.utc),
        )

    def test_parse_bilibili_detail_published_at_accepts_module_author_list(self):
        payload = {
            "code": 0,
            "data": {
                "item": {
                    "modules": [
                        {"module_title": {"text": "2024新年快乐！"}},
                        {
                            "module_author": {
                                "pub_time": "2023年12月30日 17:55",
                                "pub_ts": "1703930158",
                            }
                        },
                    ]
                }
            },
        }
        self.assertEqual(
            parse_bilibili_detail_published_at(payload),
            datetime.fromtimestamp(1703930158, tz=timezone.utc),
        )

    def test_fetch_bilibili_dynamic_fills_missing_public_opus_time_from_detail(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, params=None, headers=None, timeout=None):
                self.calls.append((url, params or {}, headers or {}))
                if "opus/feed/space" in url:
                    return FakeResponse(
                        {
                            "code": 0,
                            "data": {
                                "items": [
                                    {
                                        "content": "2024新年快乐！",
                                        "jump_url": "//www.bilibili.com/opus/880862393292292098",
                                        "opus_id": "880862393292292098",
                                        "stat": {"like": "1896"},
                                    }
                                ]
                            },
                        }
                    )
                return FakeResponse(
                    {
                        "code": 0,
                        "data": {
                            "item": {
                                "modules": {
                                    "module_author": {
                                        "pub_time": "2023年12月30日 17:55",
                                        "pub_ts": 1703930158,
                                    }
                                }
                            }
                        },
                    }
                )

        session = FakeSession()
        items = fetch_bilibili_dynamic(
            session,
            now=datetime(2026, 7, 4, tzinfo=timezone.utc),
            uid="4401694",
            source_name="林亦LY",
            max_items=20,
            api_url="https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/feed/space",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].published_at, datetime.fromtimestamp(1703930158, tz=timezone.utc))
        self.assertEqual(items[0].meta["timestamp_source"], "bilibili_opus_detail_pub_ts")
        self.assertTrue(any(call[1].get("id") == "880862393292292098" for call in session.calls))

    def test_fetch_bilibili_opus_published_at_uses_real_detail_shape(self):
        class FakeResponse:
            def json(self):
                return {
                    "code": 0,
                    "data": {
                        "item": {
                            "modules": {
                                "module_author": {
                                    "pub_time": "2023年12月30日 17:55",
                                    "pub_ts": 1703930158,
                                }
                            }
                        }
                    },
                }

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.params = None
                self.headers = None

            def get(self, url, params=None, headers=None, timeout=None):
                self.params = params
                self.headers = headers
                return FakeResponse()

        session = FakeSession()
        published = fetch_bilibili_opus_published_at(session, "880862393292292098")
        self.assertEqual(published, datetime.fromtimestamp(1703930158, tz=timezone.utc))
        self.assertEqual(session.params["id"], "880862393292292098")
        self.assertIn("/opus/880862393292292098", session.headers["Referer"])

    def test_backfill_bilibili_archive_publish_times_updates_legacy_null_time(self):
        class FakeResponse:
            def json(self):
                return {
                    "code": 0,
                    "data": {
                        "item": {
                            "modules": {
                                "module_author": {
                                    "pub_time": "2023年12月30日 17:55",
                                    "pub_ts": 1703930158,
                                }
                            }
                        }
                    },
                }

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.params = []

            def get(self, url, params=None, headers=None, timeout=None):
                self.params.append(params or {})
                return FakeResponse()

        archive = {
            "old": {
                "site_id": "bilibili_dynamic",
                "title": "2024新年快乐！",
                "url": "https://www.bilibili.com/opus/880862393292292098",
                "published_at": None,
                "first_seen_at": "2026-07-03T22:27:15Z",
            }
        }
        session = FakeSession()
        filled = backfill_bilibili_archive_publish_times(session, archive)
        self.assertEqual(filled, 1)
        self.assertEqual(archive["old"]["published_at"], "2023-12-30T09:55:58Z")
        self.assertEqual(archive["old"]["timestamp_source"], "bilibili_opus_detail_pub_ts")
        self.assertEqual(session.params[0]["id"], "880862393292292098")

    def test_sign_bilibili_wbi_params_adds_signature_without_mutating_input(self):
        params = {"host_mid": "505301413", "web_location": "333.1387"}
        signed = sign_bilibili_wbi_params(params, "a" * 32, "b" * 32, now_ts=1782817200)
        self.assertEqual(params, {"host_mid": "505301413", "web_location": "333.1387"})
        self.assertEqual(signed["wts"], "1782817200")
        self.assertRegex(signed["w_rid"], r"^[0-9a-f]{32}$")

    def test_bilibili_wbi_keys_uses_browser_headers(self):
        class FakeResponse:
            def json(self):
                return {
                    "code": 0,
                    "data": {
                        "wbi_img": {
                            "img_url": "https://i0.hdslb.com/bfs/wbi/image_key.png",
                            "sub_url": "https://i0.hdslb.com/bfs/wbi/sub_key.png",
                        }
                    },
                }

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.headers = None

            def get(self, url, headers=None, timeout=None):
                self.headers = headers
                return FakeResponse()

        session = FakeSession()
        img_key, sub_key = bilibili_wbi_keys(session)
        self.assertEqual((img_key, sub_key), ("image_key", "sub_key"))
        self.assertEqual(session.headers["User-Agent"], BROWSER_UA)
        self.assertEqual(session.headers["Referer"], "https://www.bilibili.com/")

    def test_fetch_bilibili_full_dynamic_follows_offset_pages(self):
        def dynamic_payload(dynamic_id, text, pub_ts, *, has_more=False, offset=""):
            return {
                "code": 0,
                "data": {
                    "has_more": has_more,
                    "offset": offset,
                    "items": [
                        {
                            "id_str": dynamic_id,
                            "type": "DYNAMIC_TYPE_WORD",
                            "modules": {
                                "module_author": {"pub_ts": pub_ts},
                                "module_dynamic": {
                                    "desc": {"text": text},
                                    "major": {"opus": {"jump_url": f"//www.bilibili.com/opus/{dynamic_id}"}},
                                },
                            },
                        }
                    ],
                },
            }

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.dynamic_params = []

            def get(self, url, params=None, headers=None, timeout=None):
                if "x/web-interface/nav" in url:
                    return FakeResponse(
                        {
                            "code": 0,
                            "data": {
                                "wbi_img": {
                                    "img_url": "https://i0.hdslb.com/bfs/wbi/" + "a" * 32 + ".png",
                                    "sub_url": "https://i0.hdslb.com/bfs/wbi/" + "b" * 32 + ".png",
                                }
                            },
                        }
                    )
                self.dynamic_params.append(params or {})
                if len(self.dynamic_params) == 1:
                    return FakeResponse(dynamic_payload("1", "第一页", 1782817200, has_more=True, offset="next-page"))
                return FakeResponse(dynamic_payload("2", "第二页", 1782730800))

        session = FakeSession()
        items = fetch_bilibili_full_dynamic(
            session,
            now=datetime(2026, 6, 30, tzinfo=timezone.utc),
            uid="505301413",
            source_name="Koji杨远骋at十字路口",
            max_items=10,
            max_pages=2,
            api_url="https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space",
        )
        self.assertEqual([item.title for item in items], ["第一页", "第二页"])
        self.assertNotIn("offset", session.dynamic_params[0])
        self.assertEqual(session.dynamic_params[1]["offset"], "next-page")


if __name__ == "__main__":
    unittest.main()
