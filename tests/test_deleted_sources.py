"""deleted_sources 台账：随配置进仓库、由管线在写出 data/** 前剔除，NUC 不再改写 data/**。"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.radar.cli import parse_cli_args, prepare_run_context
from scripts.radar.deleted_sources import (
    DELETED_SOURCE_LEDGER_DAYS,
    deleted_source_cleanup_status,
    filter_archive_by_deleted_sources,
    merge_deleted_sources,
    normalize_deleted_sources,
    prune_deleted_sources,
    record_deleted_sources,
    record_matches_deleted_sources,
)
from scripts.radar.server import online_sources


NOW = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)


class LedgerShapeTests(unittest.TestCase):
    def test_normalize_accepts_missing_and_sorts_entries(self):
        self.assertEqual(normalize_deleted_sources(None), {})
        ledger = normalize_deleted_sources(
            {"opmlrss": {"Simon Willison": "2026-09-12T00:17:49Z", "Microsoft AI Blog": "2026-09-11T09:28:04Z"}}
        )
        self.assertEqual(list(ledger["opmlrss"]), ["Microsoft AI Blog", "Simon Willison"])

    def test_normalize_rejects_unknown_site_bad_timestamp_and_wrong_shape(self):
        with self.assertRaisesRegex(ValueError, "deleted_sources_invalid"):
            normalize_deleted_sources({"hackernews": {"x": "2026-09-12T00:00:00Z"}})
        with self.assertRaisesRegex(ValueError, "deleted_sources_invalid"):
            normalize_deleted_sources({"opmlrss": {"x": "yesterday"}})
        with self.assertRaisesRegex(ValueError, "deleted_sources_invalid"):
            normalize_deleted_sources({"opmlrss": ["x"]})
        with self.assertRaisesRegex(ValueError, "deleted_sources_invalid"):
            normalize_deleted_sources([])

    def test_record_stamps_now_and_refreshes_redeleted_token(self):
        first = record_deleted_sources({}, {"opmlrss": {"Wired AI"}}, now=NOW - timedelta(days=3))
        second = record_deleted_sources(first, {"opmlrss": {"Wired AI"}, "hackernews": {"ignored"}}, now=NOW)
        self.assertEqual(second, {"opmlrss": {"Wired AI": "2026-09-12T08:00:00Z"}})

    def test_prune_drops_alive_and_expired(self):
        ledger = record_deleted_sources({}, {"bilibili_dynamic": {"111", "222"}}, now=NOW)
        ledger = record_deleted_sources(
            ledger, {"opmlrss": {"Old"}}, now=NOW - timedelta(days=DELETED_SOURCE_LEDGER_DAYS + 1)
        )
        pruned = prune_deleted_sources(ledger, {"bilibili_dynamic": {"111"}}, now=NOW)
        self.assertEqual(pruned, {"bilibili_dynamic": {"222": "2026-09-12T08:00:00Z"}})

    def test_merge_takes_union_with_latest_stamp(self):
        local = {"opmlrss": {"A": "2026-09-12T01:00:00Z", "B": "2026-09-12T02:00:00Z"}}
        remote = {"opmlrss": {"A": "2026-09-12T03:00:00Z"}, "bilibili_dynamic": {"1": "2026-09-12T00:00:00Z"}}
        merged = merge_deleted_sources(local, remote)
        self.assertEqual(
            merged,
            {
                "bilibili_dynamic": {"1": "2026-09-12T00:00:00Z"},
                "opmlrss": {"A": "2026-09-12T03:00:00Z", "B": "2026-09-12T02:00:00Z"},
            },
        )


class MatchingTests(unittest.TestCase):
    def test_named_channels_only_match_stable_ids(self):
        tokens = {"bilibili_dynamic": {"222"}, "mediacrawler_douyin": {"sec-2"}, "opmlrss": {"UCabc", "Wired AI"}}
        self.assertTrue(record_matches_deleted_sources({"site_id": "bilibili_dynamic", "bilibili_uid": "222", "source": "李四"}, tokens))
        self.assertFalse(record_matches_deleted_sources({"site_id": "bilibili_dynamic", "source": "李四"}, tokens))
        self.assertTrue(record_matches_deleted_sources({"site_id": "mediacrawler_douyin", "douyin_sec_user_id": "sec-2"}, tokens))
        self.assertTrue(record_matches_deleted_sources({"site_id": "opmlrss", "source": "Wired AI"}, tokens))
        self.assertFalse(record_matches_deleted_sources({"site_id": "opmlrss", "source": "OpenAI News"}, tokens))
        self.assertFalse(record_matches_deleted_sources({"site_id": "hackernews", "source": "Wired AI"}, tokens))

    def test_youtube_member_matches_channel_id_not_title(self):
        tokens = {"opmlrss": {"UCzkPX3KCIVquUPa8oXjHn0g"}}
        record = {
            "site_id": "opmlrss",
            "source": "HighLevelz",
            "url": "https://www.youtube.com/watch?v=abc",
            "feed_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCzkPX3KCIVquUPa8oXjHn0g",
        }
        self.assertTrue(record_matches_deleted_sources(record, tokens))
        self.assertFalse(record_matches_deleted_sources(record, {"opmlrss": {"HighLevelz"}}))

    def test_filter_reports_removed_by_source_and_keeps_object_when_untouched(self):
        archive = {
            "a": {"site_id": "opmlrss", "source": "Simon Willison"},
            "b": {"site_id": "opmlrss", "source": "Simon Willison"},
            "c": {"site_id": "opmlrss", "source": "小岛大浪吹-非正经政经频道"},
        }
        kept, removed = filter_archive_by_deleted_sources(archive, {"opmlrss": {"Simon Willison": "2026-09-12T00:00:00Z"}})
        self.assertEqual(list(kept), ["c"])
        self.assertEqual(removed, {("opmlrss", "Simon Willison"): 2})
        same, none = filter_archive_by_deleted_sources(archive, {})
        self.assertIs(same, archive)
        self.assertEqual(none, {})

    def test_status_payload_lists_tokens_and_removed(self):
        status = deleted_source_cleanup_status(
            {"opmlrss": {"Simon Willison": "2026-09-12T00:00:00Z"}},
            {("opmlrss", "Simon Willison"): 15},
        )
        self.assertEqual(status["enabled"], True)
        self.assertEqual(status["token_count"], 1)
        self.assertEqual(status["removed_total"], 15)
        self.assertEqual(status["removed"], [{"site_id": "opmlrss", "source": "Simon Willison", "count": 15}])


class PipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="deleted-sources-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.cwd)
        (self.root / "config").mkdir()
        (self.root / "data").mkdir()

    def write_config(self, config):
        (self.root / "config" / "online-sources.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def write_archive(self, items):
        (self.root / "data" / "archive.json").write_text(
            json.dumps({"items": items, "total_items": len(items)}, ensure_ascii=False), encoding="utf-8"
        )

    def run_context(self):
        args = parse_cli_args(
            ["--source-config", "config/online-sources.json", "--output-dir", "data", "--window-hours", "24", "--all-time"]
        )
        with patch.dict(os.environ, {"RADAR_SOURCE_CONFIG": ""}, clear=False):
            ctx = prepare_run_context(args)
        self.assertNotIsInstance(ctx, int)
        return ctx

    def test_run_context_drops_ledgered_history_and_reports_it(self):
        config = online_sources.build_online_config(
            [
                {"id": "online_youtube_x", "name": "小岛大浪吹-非正经政经频道", "type": "rss", "enabled": True,
                 "locator": "https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw"},
            ],
            deleted_sources={"opmlrss": {"Simon Willison": "2026-09-12T00:17:49Z"}},
        )
        self.write_config(config)
        self.write_archive(
            [
                {"id": "1", "site_id": "opmlrss", "source": "Simon Willison", "title": "gone", "url": "https://simonwillison.net/1"},
                {"id": "2", "site_id": "opmlrss", "source": "小岛大浪吹-非正经政经频道", "title": "stay",
                 "url": "https://www.youtube.com/watch?v=x", "feed_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCYPT3wl0MgbOz63ho166KOw"},
            ]
        )

        ctx = self.run_context()

        self.assertEqual([record["title"] for record in ctx.archive.values()], ["stay"])
        self.assertEqual(ctx.deleted_source_cleanup["removed_total"], 1)
        self.assertEqual(ctx.deleted_source_cleanup["sites"], {"opmlrss": ["Simon Willison"]})

    def test_run_context_without_ledger_keeps_archive(self):
        config = online_sources.build_online_config([])
        self.write_config(config)
        self.write_archive([{"id": "1", "site_id": "opmlrss", "source": "Simon Willison", "title": "kept", "url": "https://x/1"}])

        ctx = self.run_context()

        self.assertEqual(len(ctx.archive), 1)
        self.assertEqual(ctx.deleted_source_cleanup["enabled"], False)
        self.assertEqual(ctx.deleted_source_cleanup["removed_total"], 0)

    def test_run_context_with_invalid_ledger_skips_cleanup_but_still_runs(self):
        config = online_sources.build_online_config([])
        config["deleted_sources"] = {"hackernews": {"x": "2026-09-12T00:00:00Z"}}
        self.write_config(config)
        self.write_archive([{"id": "1", "site_id": "opmlrss", "source": "Simon Willison", "title": "kept", "url": "https://x/1"}])

        ctx = self.run_context()

        self.assertEqual(len(ctx.archive), 1)
        self.assertIn("deleted_sources_invalid", ctx.deleted_source_cleanup["error"])


if __name__ == "__main__":
    unittest.main()
