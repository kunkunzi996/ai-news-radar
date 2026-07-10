import unittest

from scripts.radar.server.online_sources import (
    normalize_douyin_homepage,
    normalize_online_source_record,
    normalize_online_sources,
    normalize_online_type,
)

DOUYIN_SEC_UID = "MS4wLjABAAAACsVvwoWhwaNZkd4kOY7bu6UhcfCiYmd_k_wcUnN9bYo8jOANJ1iyts7MXQB8nsZ0"
DOUYIN_HOMEPAGE = f"https://www.douyin.com/user/{DOUYIN_SEC_UID}"


class OnlineDouyinSourceTests(unittest.TestCase):
    def test_type_aliases_map_to_mediacrawler_jsonl(self):
        self.assertEqual(normalize_online_type("douyin"), "mediacrawler_jsonl")
        self.assertEqual(normalize_online_type("抖音"), "mediacrawler_jsonl")
        self.assertEqual(normalize_online_type("mediacrawler_douyin"), "mediacrawler_jsonl")

    def test_normalize_douyin_homepage_strips_query(self):
        raw = f"{DOUYIN_HOMEPAGE}?from_tab_name=main&vid=123"
        self.assertEqual(normalize_douyin_homepage(raw, 0), DOUYIN_HOMEPAGE)

    def test_normalize_douyin_homepage_rejects_other_hosts(self):
        with self.assertRaises(ValueError):
            normalize_douyin_homepage("https://www.xiaohongshu.com/user/profile/abc", 0)
        with self.assertRaises(ValueError):
            normalize_douyin_homepage("https://www.douyin.com/video/123", 0)
        with self.assertRaises(ValueError):
            normalize_douyin_homepage("D:/data/creator_local.jsonl", 0)

    def test_normalize_douyin_record_shape(self):
        record = normalize_online_source_record(
            {
                "name": "Simon林",
                "type": "mediacrawler_jsonl",
                "locator": f"{DOUYIN_HOMEPAGE}?from_tab_name=main",
                "enabled": False,
            },
            0,
        )
        self.assertTrue(record["id"].startswith("online_douyin_"))
        self.assertEqual(record["type"], "mediacrawler_jsonl")
        self.assertEqual(record["channel"], "抖音订阅")
        self.assertEqual(record["locator"], DOUYIN_HOMEPAGE)
        self.assertFalse(record["enabled"])
        self.assertEqual(record["env"], "")

    def test_normalize_douyin_record_requires_name(self):
        with self.assertRaises(ValueError):
            normalize_online_source_record(
                {"type": "mediacrawler_jsonl", "locator": DOUYIN_HOMEPAGE},
                0,
            )

    def test_normalize_online_sources_sorts_douyin_between_github_and_rss(self):
        sources = normalize_online_sources(
            [
                {"name": "Feed", "type": "rss", "locator": "https://example.com/feed.xml"},
                {"name": "Simon林", "type": "mediacrawler_jsonl", "locator": DOUYIN_HOMEPAGE},
                {"name": "repo", "type": "github_release", "locator": "owner/repo"},
                {"name": "UP", "type": "bilibili_dynamic", "locator": "316183842"},
            ]
        )
        self.assertEqual(
            [source["type"] for source in sources],
            ["bilibili_dynamic", "github_release", "mediacrawler_jsonl", "rss"],
        )

    def test_normalize_online_sources_dedupes_douyin_by_clean_locator(self):
        sources = normalize_online_sources(
            [
                {"name": "Simon林", "type": "mediacrawler_jsonl", "locator": f"{DOUYIN_HOMEPAGE}?a=1"},
                {"name": "Simon林2", "type": "mediacrawler_jsonl", "locator": f"{DOUYIN_HOMEPAGE}?b=2"},
            ]
        )
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["locator"], DOUYIN_HOMEPAGE)


if __name__ == "__main__":
    unittest.main()
