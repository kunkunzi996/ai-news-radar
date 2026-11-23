import unittest

from scripts.radar.pipeline import add_bilingual_fields


YOUTUBE_TITLE = "I Sent This Godot Game From My iPad to the App Store, No Mac"
YOUTUBE_ZH = "我用 iPad 把这个 Godot 游戏发到了 App Store，没有 Mac"
OTHER_TITLE = "A Plain English Blog Post About Cooking Pasta Tonight"
OTHER_ZH = "一篇关于今晚做意大利面的英文博客"
AI_TITLE = "Claude writes a long essay about language models today"
AI_ZH = "Claude 写了一篇关于语言模型的长文"


class FakeTranslateSession:
    def __init__(self):
        self.queries = []

    def get(self, url, params=None, timeout=None):
        query = str((params or {}).get("q") or "")
        self.queries.append(query)
        zh = {
            YOUTUBE_TITLE: YOUTUBE_ZH,
            OTHER_TITLE: OTHER_ZH,
            AI_TITLE: AI_ZH,
        }[query]

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return [[[zh]]]

        return Response()


def youtube_item():
    return {
        "site_id": "opmlrss",
        "source": "Letta Corporation",
        "title": YOUTUBE_TITLE,
        "url": "https://www.youtube.com/shorts/X08xPy3YLXc",
        "youtube_channel_id": "UCK7nhJBW05-tCmbmvbHThmw",
    }


def other_item():
    return {
        "site_id": "hackernews",
        "source": "Example",
        "title": OTHER_TITLE,
        "url": "https://example.com/pasta",
    }


class YoutubeTitleTranslationTests(unittest.TestCase):
    def test_youtube_title_in_full_list_is_translated_without_ai_flag(self):
        session = FakeTranslateSession()
        _ai, all_out, cache = add_bilingual_fields(
            [],
            [youtube_item(), other_item()],
            session,
            {},
            max_new_translations=80,
        )

        by_url = {item["url"]: item for item in all_out}
        youtube = by_url["https://www.youtube.com/shorts/X08xPy3YLXc"]
        other = by_url["https://example.com/pasta"]
        self.assertEqual(youtube["title_zh"], YOUTUBE_ZH)
        self.assertEqual(youtube["title_bilingual"], f"{YOUTUBE_ZH} / {YOUTUBE_TITLE}")
        self.assertIsNone(other["title_zh"])
        self.assertEqual(other["title_bilingual"], OTHER_TITLE)
        self.assertEqual(session.queries, [YOUTUBE_TITLE])
        self.assertEqual(cache[YOUTUBE_TITLE], YOUTUBE_ZH)

    def test_cached_youtube_title_is_not_requested_again(self):
        session = FakeTranslateSession()
        _ai, all_out, cache = add_bilingual_fields(
            [],
            [youtube_item()],
            session,
            {YOUTUBE_TITLE: YOUTUBE_ZH},
            max_new_translations=80,
        )

        self.assertEqual(all_out[0]["title_zh"], YOUTUBE_ZH)
        self.assertEqual(session.queries, [])
        self.assertEqual(cache[YOUTUBE_TITLE], YOUTUBE_ZH)

    def test_youtube_translation_uses_the_same_new_translation_budget(self):
        session = FakeTranslateSession()
        ai_item = {
            "site_id": "hackernews",
            "source": "Example",
            "title": AI_TITLE,
            "url": "https://example.com/claude",
        }
        _ai, all_out, _cache = add_bilingual_fields(
            [ai_item],
            [ai_item, youtube_item()],
            session,
            {},
            max_new_translations=1,
        )

        by_url = {item["url"]: item for item in all_out}
        self.assertEqual(by_url["https://example.com/claude"]["title_zh"], AI_ZH)
        self.assertIsNone(by_url["https://www.youtube.com/shorts/X08xPy3YLXc"]["title_zh"])
        self.assertEqual(session.queries, [AI_TITLE])

    def test_zero_budget_does_not_translate_youtube_titles(self):
        session = FakeTranslateSession()
        _ai, all_out, cache = add_bilingual_fields(
            [],
            [youtube_item()],
            session,
            {},
            max_new_translations=0,
        )

        self.assertIsNone(all_out[0]["title_zh"])
        self.assertEqual(session.queries, [])
        self.assertEqual(cache, {})


if __name__ == "__main__":
    unittest.main()
