import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.radar.server import online_sources

from scripts.radar.server.online_sources import (
    normalize_douyin_homepage,
    normalize_online_source_record,
    normalize_online_sources,
    normalize_online_type,
)

DOUYIN_SEC_UID = "MS4wLjABAAAACsVvwoWhwaNZkd4kOY7bu6UhcfCiYmd_k_wcUnN9bYo8jOANJ1iyts7MXQB8nsZ0"
DOUYIN_HOMEPAGE = f"https://www.douyin.com/user/{DOUYIN_SEC_UID}"


def managed_github_source(
    *,
    source_id: str = "online_github_repo_987654321",
    repo: str = "owner/repo",
    account_id: int = 12345678,
    repo_id: int = 987654321,
    enabled: bool = True,
    state: str = "active",
) -> dict:
    return {
        "id": source_id,
        "name": repo,
        "type": "github_release",
        "enabled": enabled,
        "channel": "GitHub Release",
        "target": repo,
        "locator": repo,
        "env": "",
        "notes": "只追踪 release",
        "managed_by": "github_stars",
        "managed_account_id": account_id,
        "managed_repo_id": repo_id,
        "managed_state": state,
    }


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


class OnlineSourceSchemaTests(unittest.TestCase):
    def test_existing_valid_source_ids_are_preserved(self):
        sources = normalize_online_sources(
            [
                {
                    "id": "legacy_bilibili_id",
                    "name": "UP",
                    "type": "bilibili_dynamic",
                    "locator": "316183842",
                },
                {
                    "id": "legacy_github_id",
                    "name": "Repo",
                    "type": "github_release",
                    "locator": "owner/repo",
                },
                {
                    "id": "legacy_rss_id",
                    "name": "Feed",
                    "type": "rss",
                    "locator": "https://example.com/feed.xml",
                },
            ],
            existing=True,
        )

        self.assertEqual(
            {source["id"] for source in sources},
            {"legacy_bilibili_id", "legacy_github_id", "legacy_rss_id"},
        )

    def test_existing_missing_invalid_duplicate_or_reserved_id_requires_migration(self):
        cases = {
            "missing": [
                {"name": "Repo", "type": "github_release", "locator": "owner/repo"}
            ],
            "invalid": [
                {
                    "id": "Invalid ID",
                    "name": "Repo",
                    "type": "github_release",
                    "locator": "owner/repo",
                }
            ],
            "duplicate": [
                {
                    "id": "duplicate_id",
                    "name": "One",
                    "type": "github_release",
                    "locator": "owner/one",
                },
                {
                    "id": "duplicate_id",
                    "name": "Two",
                    "type": "github_release",
                    "locator": "owner/two",
                },
            ],
            "reserved": [
                {
                    "id": "online_opmlrss",
                    "name": "Repo",
                    "type": "github_release",
                    "locator": "owner/repo",
                }
            ],
        }

        for label, sources in cases.items():
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "^online_source_id_migration_required:"):
                    normalize_online_sources(sources, existing=True)

    def test_new_github_ids_use_separate_managed_and_manual_namespaces(self):
        manual = normalize_online_source_record(
            {"name": "Repo", "type": "github_release", "locator": "Owner/Repo"},
            0,
        )
        managed = normalize_online_source_record(
            managed_github_source(source_id="client_supplied_id"),
            0,
        )
        expected_hash = hashlib.sha256(b"owner/repo").hexdigest()[:12]

        self.assertEqual(manual["id"], f"online_github_manual_{expected_hash}")
        self.assertEqual(managed["id"], "online_github_repo_987654321")
        self.assertEqual(managed["managed_repo_id"], 987654321)

    def test_manual_github_id_extends_hash_when_short_candidate_is_occupied(self):
        digest = hashlib.sha256(b"owner/repo").hexdigest()
        occupied = {f"online_github_manual_{digest[:12]}"}

        record = normalize_online_source_record(
            {"name": "Repo", "type": "github_release", "locator": "owner/repo"},
            0,
            used_ids=occupied,
        )

        self.assertEqual(record["id"], f"online_github_manual_{digest[:16]}")

    def test_managed_github_id_cannot_take_an_occupied_source_id(self):
        with self.assertRaisesRegex(ValueError, "^online_source_id_conflict:"):
            normalize_online_source_record(
                managed_github_source(),
                0,
                used_ids={"online_github_repo_987654321"},
            )

    def test_source_id_grammar_accepts_128_characters_and_rejects_129(self):
        valid_id = "a" * 128
        source = {
            "id": valid_id,
            "name": "Repo",
            "type": "github_release",
            "locator": "owner/repo",
        }

        normalized = normalize_online_sources([source], existing=True)
        self.assertEqual(normalized[0]["id"], valid_id)

        with self.assertRaisesRegex(ValueError, "^online_source_id_migration_required:"):
            normalize_online_sources([{**source, "id": "a" * 129}], existing=True)

    def test_duplicate_manual_github_locator_is_a_conflict(self):
        with self.assertRaisesRegex(ValueError, "^online_source_id_conflict:"):
            normalize_online_sources(
                [
                    {
                        "id": "manual_one",
                        "name": "One",
                        "type": "github_release",
                        "locator": "owner/repo",
                    },
                    {
                        "id": "manual_two",
                        "name": "Two",
                        "type": "github_release",
                        "locator": "https://github.com/owner/repo",
                    },
                ],
                existing=True,
            )

    def test_managed_schema_requires_complete_consistent_binding(self):
        config = {
            "github_star_sync": {
                "version": 1,
                "account_id": 12345678,
                "account_login": "example-user",
            },
            "sources": [managed_github_source()],
        }

        normalized = online_sources.validate_online_config_schema(config, existing=True)
        self.assertEqual(normalized["github_star_sync"]["account_id"], 12345678)
        self.assertEqual(normalized["sources"][0]["managed_repo_id"], 987654321)

        invalid_cases = []
        partial = managed_github_source()
        partial.pop("managed_state")
        invalid_cases.append({"github_star_sync": config["github_star_sync"], "sources": [partial]})
        mismatch = managed_github_source(account_id=87654321)
        invalid_cases.append({"github_star_sync": config["github_star_sync"], "sources": [mismatch]})
        contradictory = managed_github_source(enabled=False, state="active")
        invalid_cases.append({"github_star_sync": config["github_star_sync"], "sources": [contradictory]})
        duplicate_repo = managed_github_source(source_id="online_github_repo_duplicate")
        invalid_cases.append(
            {"github_star_sync": config["github_star_sync"], "sources": [config["sources"][0], duplicate_repo]}
        )

        for candidate in invalid_cases:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    online_sources.validate_online_config_schema(candidate, existing=True)

    def test_validated_github_words_do_not_trigger_marker_false_positives(self):
        repos = ["openai/tiktoken", "owner/password-manager", "foo/secret-sauce"]

        records = [
            normalize_online_source_record(
                {"name": repo, "type": "github_release", "locator": repo},
                index,
            )
            for index, repo in enumerate(repos)
        ]

        self.assertEqual([record["locator"] for record in records], repos)

    def test_high_confidence_credentials_are_rejected_in_every_github_field(self):
        cases = [
            {
                "name": "ghp_abcdefghijklmnopqrstuvwxyz123456",
                "type": "github_release",
                "locator": "owner/repo",
            },
            {
                "name": "Repo",
                "type": "github_release",
                "locator": "owner/repo",
                "notes": "Bearer abcdefghijklmnop",
            },
            {
                "name": "Repo",
                "type": "github_release",
                "locator": "owner/repo",
                "Authorization": "secret:value",
            },
        ]

        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    normalize_online_source_record(source, 0)

    def test_notes_and_non_github_urls_keep_strict_sensitive_checks(self):
        with self.assertRaises(ValueError):
            normalize_online_source_record(
                {
                    "name": "openai/tiktoken",
                    "type": "github_release",
                    "locator": "openai/tiktoken",
                    "notes": "tiktoken",
                },
                0,
            )
        with self.assertRaises(ValueError):
            normalize_online_source_record(
                {
                    "name": "Feed",
                    "type": "rss",
                    "locator": "https://example.com/feed.xml?access_token=abcdef",
                },
                0,
            )
        self.assertEqual(
            online_sources.normalize_github_star_sync(
                {"version": 1, "account_id": 123, "account_login": "token"}
            )["account_login"],
            "token",
        )

    def test_digest_excludes_updated_at_and_wrapper_but_preserves_array_order(self):
        source_a = {
            "id": "source_a",
            "name": "A",
            "type": "rss",
            "enabled": True,
            "locator": "https://example.com/a.xml",
        }
        source_b = {
            "id": "source_b",
            "name": "B",
            "type": "rss",
            "enabled": True,
            "locator": "https://example.com/b.xml",
        }
        config_a = {
            "version": "1.0",
            "mode": "online-public-source-config",
            "updated_at": "2026-01-01T00:00:00Z",
            "sources": [source_a, source_b, online_sources.generated_opml_source(True)],
        }
        config_b = {
            "mode": "online-public-source-config",
            "version": "1.0",
            "updated_at": "2026-07-15T00:00:00Z",
            "sources": [dict(reversed(list(source_a.items()))), source_b],
        }

        digest = online_sources.online_config_digest(config_a)
        self.assertEqual(digest, online_sources.online_config_digest(config_b))
        self.assertNotEqual(
            digest,
            online_sources.online_config_digest({**config_b, "sources": [source_b, source_a]}),
        )
        self.assertEqual(online_sources.online_config_etag(digest), f'"{digest}"')

        managed_config = {
            "github_star_sync": {
                "version": 1,
                "account_id": 12345678,
                "account_login": "example-user",
            },
            "sources": [managed_github_source()],
        }
        changed_managed = json.loads(json.dumps(managed_config))
        changed_managed["sources"][0]["managed_state"] = "auto_disabled"
        self.assertNotEqual(
            online_sources.online_config_digest(managed_config),
            online_sources.online_config_digest(changed_managed),
        )

    def test_read_old_valid_config_keeps_ids_and_returns_digest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "config" / "online-sources.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "updated_at": "2026-01-01T00:00:00Z",
                        "sources": [
                            {
                                "id": "legacy_github_source",
                                "name": "Repo",
                                "type": "github_release",
                                "locator": "owner/repo",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = online_sources.read_online_source_config(root)

        self.assertEqual(result["sources"][0]["id"], "legacy_github_source")
        self.assertRegex(result["base_config_digest"], "^[0-9a-f]{64}$")
        self.assertEqual(result["etag"], f'"{result["base_config_digest"]}"')

    def test_ordinary_save_preserves_binding_and_managed_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "config" / "online-sources.json"
            path.parent.mkdir(parents=True)
            current = {
                "version": "1.0",
                "mode": "online-public-source-config",
                "updated_at": "2026-01-01T00:00:00Z",
                "github_star_sync": {
                    "version": 1,
                    "account_id": 12345678,
                    "account_login": "example-user",
                },
                "sources": [managed_github_source()],
            }
            path.write_text(json.dumps(current), encoding="utf-8")
            client_source = {
                key: value
                for key, value in managed_github_source().items()
                if not key.startswith("managed_") and key != "managed_by"
            }

            result = online_sources.write_online_source_config(root, {"sources": [client_source]})

        self.assertEqual(result["config"]["github_star_sync"], current["github_star_sync"])
        self.assertEqual(result["sources"][0]["managed_by"], "github_stars")
        self.assertEqual(result["sources"][0]["managed_repo_id"], 987654321)

    def test_ordinary_save_rejects_managed_tampering_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "config" / "online-sources.json"
            path.parent.mkdir(parents=True)
            current = {
                "github_star_sync": {
                    "version": 1,
                    "account_id": 12345678,
                    "account_login": "example-user",
                },
                "sources": [managed_github_source()],
            }
            path.write_text(json.dumps(current), encoding="utf-8")
            before = path.read_bytes()
            tampered = managed_github_source(enabled=False)

            with self.assertRaisesRegex(ValueError, "^github_star_managed_fields_readonly:"):
                online_sources.write_online_source_config(root, {"sources": [tampered]})

            self.assertEqual(path.read_bytes(), before)

    def test_ordinary_save_rejects_every_protected_projection_change(self):
        current_source = managed_github_source()
        current_binding = {
            "version": 1,
            "account_id": 12345678,
            "account_login": "example-user",
        }
        cases = {
            "delete": {"sources": []},
            "rename": {"sources": [{**current_source, "name": "Renamed"}]},
            "add_managed": {
                "sources": [
                    current_source,
                    managed_github_source(
                        source_id="online_github_repo_555",
                        repo="other/repo",
                        repo_id=555,
                    ),
                ]
            },
            "binding": {
                "github_star_sync": {**current_binding, "account_login": "renamed-user"},
                "sources": [current_source],
            },
        }

        for label, payload in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                path = root / "config" / "online-sources.json"
                path.parent.mkdir(parents=True)
                path.write_text(
                    json.dumps(
                        {
                            "github_star_sync": current_binding,
                            "sources": [current_source],
                        }
                    ),
                    encoding="utf-8",
                )
                before = path.read_bytes()

                with self.assertRaisesRegex(ValueError, "^github_star_managed_fields_readonly:"):
                    online_sources.write_online_source_config(root, payload)

                self.assertEqual(path.read_bytes(), before)

    def test_invalid_existing_id_aborts_before_any_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "config" / "online-sources.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "id": "Invalid ID",
                                "name": "Repo",
                                "type": "github_release",
                                "locator": "owner/repo",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            before = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "^online_source_id_migration_required:"):
                online_sources.write_online_source_config(root, {"sources": []})

            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
