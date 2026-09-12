from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import requests

from scripts.update_news import (
    BROWSER_UA,
    backfill_bilibili_archive_publish_times,
    bilibili_dynamic_accounts_from_env,
    bilibili_dynamic_status_base,
    bilibili_dynamic_item_title,
    bilibili_cookie_header_from_file_text,
    maybe_fetch_bilibili_dynamic,
    fetch_bilibili_dynamic,
    fetch_bilibili_opus_published_at,
    fetch_bilibili_full_dynamic,
    fetch_bilibili_space_videos,
    bilibili_space_video_query_params,
    bilibili_space_video_risk_params,
    bilibili_wbi_keys,
    sign_bilibili_wbi_params,
    parse_bilibili_detail_published_at,
    parse_bilibili_full_dynamic_items,
    parse_bilibili_dynamic_items,
    parse_mediacrawler_douyin_jsonl,
    maybe_fetch_mediacrawler_douyin,
    mediacrawler_local_root,
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
        self.assertEqual(
            status["coverage_note"],
            "tries_cookie_full_dynamic_then_public_opus_then_space_video_fallback",
        )

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

    def test_opml_rss_backfills_first_collect_feed_within_two_months(self):
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
                # 归档中已有该 feed：仍按最近 5 条截断。
                known_items, _, known_statuses = fetch_opml_rss(
                    now,
                    opml,
                    existing_source_keys=frozenset({("opmlrss", "Test YouTube")}),
                    existing_member_ids=frozenset({("opmlrss", "test")}),
                )
                # 归档中从未出现过：首采回填保留 60 天内全部 8 条。
                new_items, _, new_statuses = fetch_opml_rss(
                    now,
                    opml,
                    existing_source_keys=frozenset(),
                    existing_member_ids=frozenset(),
                )

        self.assertEqual(len(known_items), 5)
        self.assertFalse(known_statuses[0]["first_collect_backfill"])
        self.assertEqual(len(new_items), 8)
        self.assertTrue(new_statuses[0]["first_collect_backfill"])
        self.assertEqual(new_items[0].meta.get("youtube_channel_id"), "test")

    def test_youtube_rename_same_channel_id_is_not_first_collect(self):
        class Response:
            def __init__(self, text: str):
                self.text = text
                self.content = text.encode("utf-8")

            def raise_for_status(self) -> None:
                return None

        now = datetime(2026, 7, 6, tzinfo=timezone.utc)
        rss = """<rss><channel><title>Renamed YouTube</title>
            <item><title>Video 1</title><link>https://www.youtube.com/watch?v=1</link>
            <pubDate>Mon, 01 Jun 2026 00:00:00 GMT</pubDate></item></channel></rss>"""
        with tempfile.TemporaryDirectory() as tmp:
            opml = Path(tmp) / "follow.opml"
            opml.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
                <opml version="1.0"><body>
                  <outline text="Renamed YouTube" title="Renamed YouTube" type="rss"
                    xmlUrl="https://www.youtube.com/feeds/videos.xml?channel_id=test" />
                </body></opml>
                """,
                encoding="utf-8",
            )
            with patch("scripts.radar.fetchers.subscriptions.requests.get", return_value=Response(rss)):
                items, _, statuses = fetch_opml_rss(
                    now,
                    opml,
                    existing_source_keys=frozenset(),
                    existing_member_ids=frozenset({("opmlrss", "test")}),
                )

        self.assertEqual(len(items), 1)
        self.assertFalse(statuses[0]["first_collect_backfill"])
        self.assertEqual(items[0].meta.get("youtube_channel_id"), "test")

    def test_youtube_rss_retries_transient_404_then_succeeds(self):
        class FakeResp:
            def __init__(self, status_code: int, content: bytes = b""):
                self.status_code = status_code
                self.content = content
                self.text = content.decode("utf-8")

            def raise_for_status(self) -> None:
                if self.status_code >= 400:
                    error = requests.HTTPError(f"{self.status_code} Client Error")
                    error.response = self
                    raise error

        now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        rss = """<rss><channel><title>小岛大浪吹-非正经政经频道</title>
            <item><title>新一期</title><link>https://www.youtube.com/watch?v=live1</link>
            <pubDate>Mon, 08 Sep 2026 00:00:00 GMT</pubDate></item></channel></rss>"""
        calls = {"n": 0}
        sleeps: list[float] = []

        def fake_get(url, timeout=None, headers=None):
            calls["n"] += 1
            if calls["n"] < 3:
                return FakeResp(404)
            return FakeResp(200, rss.encode("utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            opml = Path(tmp) / "follow.opml"
            opml.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
                <opml version="1.0"><body>
                  <outline text="小岛大浪吹-非正经政经频道" title="小岛大浪吹-非正经政经频道" type="rss"
                    xmlUrl="https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw" />
                </body></opml>
                """,
                encoding="utf-8",
            )
            with patch("scripts.radar.fetchers.subscriptions.requests.get", side_effect=fake_get):
                items, summary, feed_statuses = fetch_opml_rss(
                    now,
                    opml,
                    sleeper=sleeps.append,
                )

        self.assertEqual(calls["n"], 3)
        self.assertEqual(sleeps, [2.0, 2.0])
        self.assertEqual([item.title for item in items], ["新一期"])
        self.assertTrue(summary["ok"])
        self.assertEqual(feed_statuses[0]["ok"], True)
        self.assertEqual(feed_statuses[0]["fetch_mode"], "live_rss")
        self.assertEqual(feed_statuses[0]["keep_last_restored"], 0)
        self.assertIsNone(feed_statuses[0]["error"])

    def test_youtube_rss_keep_last_after_persistent_404(self):
        class FakeResp:
            def __init__(self, status_code: int):
                self.status_code = status_code
                self.content = b""
                self.text = ""

            def raise_for_status(self) -> None:
                error = requests.HTTPError(f"{self.status_code} Client Error")
                error.response = self
                raise error

        now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        archive = {
            "old": {
                "id": "old",
                "site_id": "opmlrss",
                "source": "小岛大浪吹-非正经政经频道",
                "title": "上一轮还在的视频",
                "url": "https://www.youtube.com/watch?v=keep1",
                "published_at": "2026-09-07T01:00:00Z",
            },
            "blog": {
                "id": "blog",
                "site_id": "opmlrss",
                "source": "小岛大浪吹-非正经政经频道",
                "title": "不该留下的博客",
                "url": "https://example.com/not-youtube",
                "published_at": "2026-09-07T02:00:00Z",
            },
        }
        calls = {"n": 0}

        def fake_get(url, timeout=None, headers=None):
            calls["n"] += 1
            return FakeResp(404)

        with tempfile.TemporaryDirectory() as tmp:
            opml = Path(tmp) / "follow.opml"
            opml.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
                <opml version="1.0"><body>
                  <outline text="小岛大浪吹-非正经政经频道" title="小岛大浪吹-非正经政经频道" type="rss"
                    xmlUrl="https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw" />
                </body></opml>
                """,
                encoding="utf-8",
            )
            with patch("scripts.radar.fetchers.subscriptions.requests.get", side_effect=fake_get):
                items, summary, feed_statuses = fetch_opml_rss(
                    now,
                    opml,
                    archive=archive,
                    sleeper=lambda _seconds: None,
                )

        self.assertEqual(calls["n"], 3)
        self.assertEqual([item.title for item in items], ["上一轮还在的视频"])
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["failed_feed_count"], 0)
        self.assertEqual(summary["keep_last_restored"], 1)
        self.assertEqual(feed_statuses[0]["ok"], True)
        self.assertEqual(feed_statuses[0]["fetch_mode"], "keep_last_rss")
        self.assertEqual(feed_statuses[0]["keep_last_restored"], 1)
        self.assertIsNone(feed_statuses[0]["error"])
        self.assertIn("404", str(feed_statuses[0]["fallback_reason"]))

    def test_youtube_rss_404_without_archive_still_fails(self):
        class FakeResp:
            def __init__(self, status_code: int):
                self.status_code = status_code
                self.content = b""
                self.text = ""

            def raise_for_status(self) -> None:
                error = requests.HTTPError(f"{self.status_code} Client Error")
                error.response = self
                raise error

        now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            opml = Path(tmp) / "follow.opml"
            opml.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
                <opml version="1.0"><body>
                  <outline text="小岛大浪吹-非正经政经频道" title="小岛大浪吹-非正经政经频道" type="rss"
                    xmlUrl="https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw" />
                </body></opml>
                """,
                encoding="utf-8",
            )
            with patch("scripts.radar.fetchers.subscriptions.requests.get", return_value=FakeResp(404)):
                items, summary, feed_statuses = fetch_opml_rss(
                    now,
                    opml,
                    sleeper=lambda _seconds: None,
                )

        self.assertEqual(items, [])
        self.assertFalse(feed_statuses[0]["ok"])
        self.assertEqual(summary["failed_feed_count"], 1)
        self.assertEqual(feed_statuses[0]["keep_last_restored"], 0)

    def test_non_youtube_rss_404_does_not_retry(self):
        class FakeResp:
            def __init__(self, status_code: int):
                self.status_code = status_code
                self.content = b""
                self.text = ""

            def raise_for_status(self) -> None:
                error = requests.HTTPError(f"{self.status_code} Client Error")
                error.response = self
                raise error

        now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        calls = {"n": 0}

        def fake_get(url, timeout=None, headers=None):
            calls["n"] += 1
            return FakeResp(404)

        with tempfile.TemporaryDirectory() as tmp:
            opml = Path(tmp) / "follow.opml"
            opml.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
                <opml version="1.0"><body>
                  <outline text="Some Blog" title="Some Blog" type="rss"
                    xmlUrl="https://example.com/feed.xml" />
                </body></opml>
                """,
                encoding="utf-8",
            )
            with patch("scripts.radar.fetchers.subscriptions.requests.get", side_effect=fake_get):
                items, summary, feed_statuses = fetch_opml_rss(
                    now,
                    opml,
                    sleeper=lambda _seconds: None,
                )

        self.assertEqual(calls["n"], 1)
        self.assertEqual(items, [])
        self.assertFalse(feed_statuses[0]["ok"])

    def test_trim_first_collect_backfill_keeps_latest_and_window_only(self):
        from datetime import timedelta

        from scripts.radar.common import RawItem, trim_first_collect_backfill_items

        now = datetime(2026, 7, 11, tzinfo=timezone.utc)

        def item(age_days: int) -> RawItem:
            return RawItem(
                "bilibili_dynamic",
                "Bilibili",
                "新UP",
                f"post {age_days}",
                f"https://example.com/{age_days}",
                now - timedelta(days=age_days),
                {},
            )

        # 高频源：60 天内 8 条全保留，120/200 天前的超窗条目被丢弃。
        active = [item(age) for age in (1, 5, 10, 20, 30, 40, 50, 59, 120, 200)]
        kept = trim_first_collect_backfill_items(active, now, keep_latest=5, backfill_days=60)
        self.assertEqual([i.title for i in kept], [f"post {age}" for age in (1, 5, 10, 20, 30, 40, 50, 59)])

        # 低频源：两个月内没内容，仍按最新 5 条兜底。
        stale = [item(age) for age in (100, 120, 140, 160, 180, 200)]
        kept = trim_first_collect_backfill_items(stale, now, keep_latest=5, backfill_days=60)
        self.assertEqual(len(kept), 5)
        self.assertEqual(kept[0].title, "post 100")

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

    def test_mediacrawler_default_root_is_workspace_sibling(self):
        expected = Path(__file__).resolve().parents[1].parent / "MediaCrawler-local-test"

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mediacrawler_local_root(), expected)

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


class DouyinBridgeManifestHealthTests(unittest.TestCase):
    """TASK-04：把 NUC 的采集健康经桥接 manifest 送到云端看板。

    云端 Actions 只看得到桥接仓库的内容，看不到 NUC 上被风控拦了几条。
    `manifest.json` 是 NUC 唯一会推送的元信息载体（与 JSONL 一起精确暂存），
    所以健康字段搭它的车上云，再由前端既有的 `site.partial` 显示成「部分完成」。
    """

    ROW = {
        "aweme_id": "row-1",
        "desc": "抖音作品",
        "aweme_url": "https://www.douyin.com/video/row-1",
        "nickname": "测试号",
        "sec_user_id": "MS4wLjABAAAA_TEST",
    }
    SUBSCRIPTION = {
        "name": "测试号",
        "target": "测试号",
        "locator": "https://www.douyin.com/user/MS4wLjABAAAA_TEST",
    }

    def fetch_with_manifest(self, manifest_text):
        from scripts.update_news import fetch_mediacrawler_douyin_subscriptions

        with tempfile.TemporaryDirectory() as tmp:
            bridge_root = Path(tmp)
            jsonl_dir = bridge_root / "output" / "douyin" / "jsonl"
            jsonl_dir.mkdir(parents=True)
            (jsonl_dir / "creator_contents_2026-08-08.jsonl").write_text(
                json.dumps(self.ROW, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            if manifest_text is not None:
                (bridge_root / "manifest.json").write_text(manifest_text, encoding="utf-8")
            with patch.dict(os.environ, {"MEDIACRAWLER_LOCAL_DIR": tmp}, clear=True):
                return fetch_mediacrawler_douyin_subscriptions(
                    [dict(self.SUBSCRIPTION)], datetime(2026, 8, 8, tzinfo=timezone.utc)
                )

    def test_schema_2_manifest_surfaces_partial_health_on_the_status(self):
        manifest = json.dumps(
            {
                "schema_version": 2,
                "generated_at": "2026-08-08T05:14:35.000Z",
                "partial": True,
                "missing_rows": 3,
                "creator_count": 6,
                "completed_creator_count": 4,
                "partial_creator_count": 1,
                "failed_creator_count": 1,
            }
        )

        items, status = self.fetch_with_manifest(manifest)

        self.assertEqual(len(items), 1, "健康字段不得影响条目产出")
        self.assertTrue(status["partial"])
        self.assertEqual(status["missing_rows"], 3)
        self.assertEqual(status["completed_creator_count"], 4)
        self.assertEqual(status["partial_creator_count"], 1)
        self.assertEqual(status["failed_creator_count"], 1)

    def test_healthy_manifest_does_not_mark_the_site_partial(self):
        manifest = json.dumps(
            {
                "schema_version": 2,
                "partial": False,
                "missing_rows": 0,
                "completed_creator_count": 6,
                "partial_creator_count": 0,
                "failed_creator_count": 0,
            }
        )

        _items, status = self.fetch_with_manifest(manifest)

        self.assertFalse(status["partial"])
        self.assertEqual(status["missing_rows"], 0)

    def test_missing_manifest_degrades_silently(self):
        items, status = self.fetch_with_manifest(None)

        self.assertEqual(len(items), 1, "manifest 缺失绝不能影响条目解析")
        self.assertTrue(status["ok"])
        self.assertFalse(status["partial"])
        self.assertFalse(status["collection_manifest_available"])

    def test_broken_manifest_degrades_silently(self):
        items, status = self.fetch_with_manifest("{ this is not json")

        self.assertEqual(len(items), 1)
        self.assertTrue(status["ok"])
        self.assertFalse(status["partial"])
        self.assertFalse(status["collection_manifest_available"])

    def fetch_default_branch_with_manifest(self, manifest_text):
        """走 `maybe_fetch_mediacrawler_douyin`——**云端 Actions 实际走的就是这条路**。

        P8 真实验收 QA-01：线上 `source-status.json` 里抖音条目
        `site_name` 是 `MediaCrawler Douyin`、且没有 `subscriptions` 字段，
        证明云端用的是环境变量驱动的默认分支，不是订阅分支。
        原实现只给订阅分支加了健康字段，于是看板上一个字段都没有。
        """
        from scripts.update_news import maybe_fetch_mediacrawler_douyin

        with tempfile.TemporaryDirectory() as tmp:
            bridge_root = Path(tmp)
            jsonl_dir = bridge_root / "output" / "douyin" / "jsonl"
            jsonl_dir.mkdir(parents=True)
            (jsonl_dir / "creator_contents_2026-08-08.jsonl").write_text(
                json.dumps(self.ROW, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            if manifest_text is not None:
                (bridge_root / "manifest.json").write_text(manifest_text, encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "MEDIACRAWLER_DOUYIN_ENABLED": "1",
                    "MEDIACRAWLER_DOUYIN_JSONL": str(jsonl_dir),
                    "MEDIACRAWLER_LOCAL_DIR": tmp,
                },
                clear=True,
            ):
                return maybe_fetch_mediacrawler_douyin(datetime(2026, 8, 8, tzinfo=timezone.utc))

    def test_default_branch_also_surfaces_partial_health(self):
        manifest = json.dumps(
            {
                "schema_version": 2,
                "partial": True,
                "missing_rows": 4,
                "completed_creator_count": 5,
                "partial_creator_count": 1,
                "failed_creator_count": 0,
            }
        )

        items, status = self.fetch_default_branch_with_manifest(manifest)

        self.assertEqual(len(items), 1)
        self.assertTrue(status["ok"])
        self.assertTrue(status["partial"], "云端实际走的默认分支必须同样带上健康字段")
        self.assertEqual(status["missing_rows"], 4)
        self.assertEqual(status["completed_creator_count"], 5)
        self.assertEqual(status["partial_creator_count"], 1)
        self.assertTrue(status["collection_manifest_available"])

    def test_default_branch_degrades_silently_without_manifest(self):
        items, status = self.fetch_default_branch_with_manifest(None)

        self.assertEqual(len(items), 1, "manifest 缺失绝不能影响条目产出")
        self.assertTrue(status["ok"])
        self.assertFalse(status["partial"])
        self.assertFalse(status["collection_manifest_available"])

    def test_source_status_entry_keeps_unknown_keys_and_does_not_invent_partial(self):
        from scripts.radar.cli import source_status_entry

        entry = source_status_entry(
            "mediacrawler_douyin",
            "Douyin",
            {"ok": True, "item_count": 3, "qa02_extra_field": "must-survive"},
        )

        self.assertEqual(entry["qa02_extra_field"], "must-survive")
        self.assertEqual(entry["site_id"], "mediacrawler_douyin")
        self.assertEqual(entry["site_name"], "Douyin")
        self.assertNotIn("partial", entry)

    def test_source_status_entry_channel_id_wins(self):
        from scripts.radar.cli import source_status_entry

        entry = source_status_entry(
            "bilibili_dynamic",
            "Bilibili Dynamic",
            {"site_id": "nope", "site_name": "wrong", "ok": True},
        )

        self.assertEqual(entry["site_id"], "bilibili_dynamic")
        self.assertEqual(entry["site_name"], "Bilibili Dynamic")

    def test_collect_stage_keeps_fetcher_status_keys(self):
        """QA-02：fetcher 多出来的键必须还在 collect_stage 写出的源状态里。"""
        from scripts.radar.cli import RunContext, collect_stage, parse_cli_args
        from scripts.radar.common import MEDIACRAWLER_DOUYIN_SITE_ID, MEDIACRAWLER_DOUYIN_SITE_NAME

        fetcher_status = {
            "enabled": True,
            "ok": True,
            "item_count": 52,
            "duration_ms": 12,
            "error": None,
            "partial": True,
            "missing_rows": 7,
            "completed_creator_count": 4,
            "partial_creator_count": 1,
            "failed_creator_count": 1,
            "collection_manifest_available": True,
            "collection_generated_at": "2026-08-08T09:20:32Z",
            "qa02_extra_field": "must-survive",
            "site_id": "wrong-channel",
        }
        now = datetime(2026, 8, 8, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            args = parse_cli_args(["--output-dir", str(tmp_path)])
            ctx = RunContext(
                args=args,
                output_dir=tmp_path,
                source_config={"sources": []},
                source_config_status={"ok": True, "enabled": True},
                source_config_runtime={"rss_opml": ""},
                source_config_active=True,
                source_scope="tested_creator_sources",
                active_source_ids=frozenset({MEDIACRAWLER_DOUYIN_SITE_ID}),
                scoped_to_tested_creators=True,
                scoped_by_config=False,
                all_time=False,
                collect_window_hours=0,
                wewe_rss_enabled=False,
                we_mp_rss_enabled=False,
                we_mp_rss_jsonl_enabled=False,
                we_mp_cleanup_mode="off",
                github_cleanup_mode="off",
                now=now,
                archive_path=tmp_path / "archive.json",
                latest_path=tmp_path / "latest-24h.json",
                latest_all_path=tmp_path / "latest-24h-all.json",
                status_path=tmp_path / "source-status.json",
                daily_brief_path=tmp_path / "daily-brief.json",
                stories_merged_path=tmp_path / "stories-merged.json",
                merge_log_path=tmp_path / "merge-log.json",
                waytoagi_path=tmp_path / "waytoagi-7d.json",
                title_cache_path=tmp_path / "title-zh-cache.json",
                email_digest_path=tmp_path / "email-digest.json",
                paid_source_state_path=tmp_path / "paid-source-state.json",
                github_autosync_status_path=tmp_path / "github-star-autosync.json",
                github_purge_state_path=tmp_path / "github-star-purge-state.json",
                github_cleanup_audit_path=tmp_path / "github-star-subscription-cleanup.json",
                archive={},
                paid_source_state={},
            )
            with patch(
                "scripts.radar.cli.fetch_mediacrawler_douyin_subscriptions",
                return_value=([], fetcher_status),
            ):
                collected = collect_stage(object(), ctx)

        entry = next(site for site in collected.statuses if site.get("site_id") == MEDIACRAWLER_DOUYIN_SITE_ID)
        self.assertEqual(entry["item_count"], 52)
        self.assertTrue(entry["partial"])
        self.assertEqual(entry["missing_rows"], 7)
        self.assertEqual(entry["qa02_extra_field"], "must-survive")
        self.assertEqual(entry["site_name"], MEDIACRAWLER_DOUYIN_SITE_NAME)
        self.assertEqual(entry["site_id"], MEDIACRAWLER_DOUYIN_SITE_ID)

    def test_legacy_schema_1_manifest_is_treated_as_unavailable(self):
        manifest = json.dumps({"schema_version": 1, "output_rows": 104, "crawl_output_rows": 52})

        items, status = self.fetch_with_manifest(manifest)

        self.assertEqual(len(items), 1)
        self.assertFalse(status["partial"])
        self.assertFalse(
            status["collection_manifest_available"],
            "旧 schema 没有健康字段，必须当作不可用而不是当成健康",
        )


class BilibiliSpaceVideoFallbackTests(unittest.TestCase):
    def test_space_video_fallback_when_public_opus_is_empty(self):
        class FakeResponse:
            def __init__(self, payload, status=200):
                self._payload = payload
                self.status_code = status

            def json(self):
                return self._payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(f"{self.status_code}")

        class FakeSession:
            def __init__(self):
                self.urls = []

            def get(self, url, params=None, headers=None, timeout=None):
                self.urls.append(url)
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
                if "opus/feed/space" in url:
                    return FakeResponse({"code": 0, "data": {"items": []}})
                if "space/wbi/arc/search" in url:
                    return FakeResponse(
                        {
                            "code": 0,
                            "data": {
                                "list": {
                                    "vlist": [
                                        {
                                            "mid": 3546884870244925,
                                            "bvid": "BV1FLtR6fEEc",
                                            "title": "Obsidian 智能体插件完整教程",
                                            "created": 1788425694,
                                        }
                                    ]
                                }
                            },
                        }
                    )
                raise AssertionError(f"unexpected url {url}")

        env = {
            "BILIBILI_DYNAMIC_ENABLED": "1",
            "BILIBILI_DYNAMIC_UIDS": "3546884870244925",
            "BILIBILI_DYNAMIC_SOURCE_NAMES": "杰森的效率工坊",
            "BILIBILI_COOKIE": "",
            "BILIBILI_DYNAMIC_COOKIE": "",
            "BILIBILI_COOKIE_FILE": "",
            "BILIBILI_DYNAMIC_COOKIE_FILE": "",
        }
        now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        session = FakeSession()
        with patch.dict(os.environ, env, clear=True):
            items, status = maybe_fetch_bilibili_dynamic(
                session, now, existing_source_keys=set(), existing_member_ids=set()
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Obsidian 智能体插件完整教程")
        self.assertEqual(items[0].url, "https://www.bilibili.com/video/BV1FLtR6fEEc")
        self.assertEqual(status["accounts"][0]["fetch_mode"], "space_video_fallback")
        self.assertEqual(status["accounts"][0]["ok"], True)
        self.assertTrue(any("opus/feed/space" in url for url in session.urls))
        self.assertTrue(any("space/wbi/arc/search" in url for url in session.urls))

    def test_fetch_bilibili_space_videos_rejects_other_mids(self):
        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        class FakeSession:
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
                return FakeResponse(
                    {
                        "code": 0,
                        "data": {
                            "list": {
                                "vlist": [
                                    {
                                        "mid": 1,
                                        "bvid": "BVOTHER",
                                        "title": "别人的视频",
                                        "created": 1788425694,
                                    }
                                ]
                            }
                        },
                    }
                )

        with self.assertRaisesRegex(ValueError, "bilibili_space_video_no_items"):
            fetch_bilibili_space_videos(
                FakeSession(),
                datetime(2026, 9, 8, tzinfo=timezone.utc),
                uid="3546884870244925",
                source_name="杰森的效率工坊",
                max_items=5,
            )

    def test_space_video_query_includes_dm_img_risk_params(self):
        params = bilibili_space_video_query_params("3546884870244925", 10)
        risk = bilibili_space_video_risk_params()
        self.assertEqual(params["mid"], "3546884870244925")
        self.assertEqual(params["order"], "pubdate")
        self.assertEqual(params["web_location"], "1550101")
        self.assertEqual(params["dm_img_list"], risk["dm_img_list"])
        self.assertEqual(params["dm_img_str"], risk["dm_img_str"])
        self.assertEqual(params["dm_cover_img_str"], risk["dm_cover_img_str"])
        self.assertEqual(params["dm_img_inter"], risk["dm_img_inter"])

    def test_fetch_bilibili_space_videos_signs_dm_img_params(self):
        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.params = None

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
                self.params = params
                return FakeResponse(
                    {
                        "code": 0,
                        "data": {
                            "list": {
                                "vlist": [
                                    {
                                        "mid": 3546884870244925,
                                        "bvid": "BV1FLtR6fEEc",
                                        "title": "Obsidian 智能体插件完整教程",
                                        "created": 1788425694,
                                    }
                                ]
                            }
                        },
                    }
                )

        session = FakeSession()
        items = fetch_bilibili_space_videos(
            session,
            datetime(2026, 9, 8, tzinfo=timezone.utc),
            uid="3546884870244925",
            source_name="杰森的效率工坊",
            max_items=5,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(session.params["dm_img_list"], "[]")
        self.assertEqual(session.params["dm_img_str"], "V2ViR0wgMS4wIChPcGVuR0wgRVNOKQ")
        self.assertIn("dm_cover_img_str", session.params)
        self.assertIn("dm_img_inter", session.params)
        self.assertRegex(session.params["w_rid"], r"^[0-9a-f]{32}$")
        self.assertTrue(session.params["wts"])

    def test_fetch_bilibili_space_videos_still_raises_on_352(self):
        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        class FakeSession:
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
                return FakeResponse({"code": -352, "message": "风控校验失败"})

        with self.assertRaisesRegex(ValueError, "bilibili_space_video_api_code_-352"):
            fetch_bilibili_space_videos(
                FakeSession(),
                datetime(2026, 9, 8, tzinfo=timezone.utc),
                uid="3546884870244925",
                source_name="杰森的效率工坊",
                max_items=5,
            )


class BilibiliCollectBudgetTests(unittest.TestCase):
    def test_budget_skips_remaining_accounts_when_requests_hang(self):
        calls = {"n": 0}

        class HangSession:
            def get(self, *args, **kwargs):
                calls["n"] += 1
                time.sleep(0.35)
                raise requests.Timeout("simulated hang")

        env = {
            "BILIBILI_DYNAMIC_ENABLED": "1",
            "BILIBILI_DYNAMIC_UIDS": "11,22,33,44,55,66",
            "BILIBILI_DYNAMIC_SOURCE_NAMES": "a,b,c,d,e,f",
            "BILIBILI_DYNAMIC_BUDGET_SECONDS": "1",
            "BILIBILI_DYNAMIC_MAX_PAGES": "8",
            "BILIBILI_COOKIE": "",
            "BILIBILI_DYNAMIC_COOKIE": "",
            "BILIBILI_COOKIE_FILE": "",
            "BILIBILI_DYNAMIC_COOKIE_FILE": "",
        }
        now = datetime(2026, 8, 26, tzinfo=timezone.utc)
        with patch.dict(os.environ, env, clear=True):
            items, status = maybe_fetch_bilibili_dynamic(
                HangSession(), now, existing_source_keys=set(), existing_member_ids=set()
            )

        skipped = [
            account
            for account in status.get("accounts") or []
            if account.get("skip_reason") == "skipped_due_to_budget"
        ]
        self.assertEqual(items, [])
        self.assertGreaterEqual(len(skipped), 1)
        self.assertLess(calls["n"], 6)
        self.assertLessEqual(int(status.get("duration_ms") or 0), 2500)
        self.assertGreaterEqual(int(status.get("deferred_count") or 0), 1)


if __name__ == "__main__":
    unittest.main()
