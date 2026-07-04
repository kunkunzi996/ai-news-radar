import json
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.run_mediacrawler_douyin import limited_douyin_creator_posts, summarize_creator_jsonl_by_window, row_publish_time


class MediaCrawlerRunnerTests(unittest.TestCase):
    def test_row_publish_time_accepts_seconds_and_milliseconds(self):
        published = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(row_publish_time({"create_time": int(published.timestamp())}), published)
        self.assertEqual(row_publish_time({"time": int(published.timestamp() * 1000)}), published)

    def test_summarize_creator_jsonl_by_window_preserves_raw_file(self):
        now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(prefix="ai-news-radar-mediacrawler-runner-test-") as tmp:
            crawler_root = Path(tmp)
            jsonl_dir = crawler_root / "output" / "xhs" / "jsonl"
            jsonl_dir.mkdir(parents=True)
            jsonl = jsonl_dir / "creator_contents_2026-07-04.jsonl"
            fresh = {"note_id": "fresh", "time": int((now - timedelta(hours=2)).timestamp() * 1000)}
            old = {"note_id": "old", "time": int((now - timedelta(days=3)).timestamp() * 1000)}
            missing_time = {"note_id": "missing"}
            jsonl.write_text(
                "\n".join(json.dumps(row) for row in (fresh, old, missing_time)) + "\n",
                encoding="utf-8",
            )

            original_text = jsonl.read_text(encoding="utf-8")

            result = summarize_creator_jsonl_by_window(crawler_root, "xhs", 24, now=now)

            self.assertTrue(result["ok"])
            self.assertEqual(result["total"], 3)
            self.assertEqual(result["kept"], 1)
            self.assertEqual(result["skipped"], 2)
            self.assertEqual(jsonl.read_text(encoding="utf-8"), original_text)
            summary_path = crawler_root / "mediacrawler-xhs-collection-window.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["kept"], 1)
            self.assertEqual(summary["total"], 3)

    def test_limited_douyin_creator_posts_stops_at_per_creator_limit(self):
        class FakeDouyinClient:
            def __init__(self):
                self.calls = 0

            async def get_user_aweme_posts(self, sec_user_id, max_cursor=""):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "has_more": 1,
                        "max_cursor": "page2",
                        "aweme_list": [{"aweme_id": f"video-{index}"} for index in range(1, 19)],
                    }
                return {
                    "has_more": 0,
                    "max_cursor": "",
                    "aweme_list": [{"aweme_id": "video-19"}],
                }

        callback_batches = []

        async def callback(items):
            callback_batches.append([item["aweme_id"] for item in items])

        client = FakeDouyinClient()

        result = asyncio.run(limited_douyin_creator_posts(client, "sec-user", 5, callback))

        self.assertEqual([item["aweme_id"] for item in result], [f"video-{index}" for index in range(1, 6)])
        self.assertEqual(callback_batches, [[f"video-{index}" for index in range(1, 6)]])
        self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()
