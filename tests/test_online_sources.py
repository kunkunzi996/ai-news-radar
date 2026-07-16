import hashlib
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

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


class OnlineSourceTransactionFoundationTests(unittest.TestCase):
    def git(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode != 0:
            self.fail(
                f"git {' '.join(args)} failed ({completed.returncode})\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        return completed

    def create_transaction_repo(self) -> tuple[Path, dict, dict]:
        temp_dir = tempfile.TemporaryDirectory(prefix="online-source-transaction-")
        self.addCleanup(temp_dir.cleanup)
        base = Path(temp_dir.name)
        origin = base / "origin.git"
        root = base / "local"
        self.git(base, "init", "--bare", str(origin))
        root.mkdir()
        self.git(root, "init", "-b", "master")
        self.git(root, "config", "user.name", "Test")
        self.git(root, "config", "user.email", "test@example.com")
        self.git(root, "config", "core.autocrlf", "false")
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
        online_sources.write_json_atomic(online_sources.online_config_path(root), config)
        online_sources.write_online_opml(root, [source])
        data_path = root / "data" / "latest-24h.json"
        data_path.parent.mkdir()
        data_path.write_text('{"version":"initial"}\n', encoding="utf-8")
        self.git(
            root,
            "add",
            "config/online-sources.json",
            "feeds/online-sources.opml",
            "data/latest-24h.json",
        )
        self.git(root, "commit", "-m", "initial config")
        self.git(root, "remote", "add", "origin", str(origin))
        self.git(root, "push", "-u", "origin", "master")
        return root, source, config

    def test_shared_guard_is_reentrant_and_busy_across_threads(self):
        results: list[str] = []
        finished = threading.Event()

        def contend_for_lock() -> None:
            try:
                with online_sources.online_sources_guard():
                    results.append("acquired")
            except online_sources.OnlineSourcesError as exc:
                results.append(exc.code)
            finally:
                finished.set()

        with online_sources.online_sources_guard():
            with online_sources.online_sources_guard():
                thread = threading.Thread(target=contend_for_lock)
                thread.start()
                self.assertTrue(finished.wait(timeout=2))
                thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(results, ["online_sources_busy"])

    def test_if_match_requires_one_quoted_current_digest(self):
        digest = "a" * 64

        self.assertEqual(
            online_sources.require_online_config_match(f'"{digest}"', digest),
            digest,
        )

        for value in [None, "", digest, f'W/"{digest}"', '"not-a-digest"', '"' + "b" * 64 + '"']:
            with self.subTest(value=value), self.assertRaises(
                online_sources.OnlineSourcesError
            ) as raised:
                online_sources.require_online_config_match(value, digest)
            self.assertEqual(raised.exception.code, "online_sources_config_stale")
            self.assertEqual(raised.exception.status_code, 409)

    def test_json_config_is_the_only_source_of_truth_for_online_sources(self):
        source_a = {
            "id": "rss_a",
            "name": "Feed A",
            "type": "rss",
            "enabled": True,
            "channel": "RSS/YouTube",
            "target": "Feed A",
            "locator": "https://example.com/a.xml",
            "env": "",
            "notes": "public feed",
        }
        source_b = {
            **source_a,
            "id": "rss_b",
            "name": "Feed B",
            "target": "Feed B",
            "locator": "https://example.com/b.xml",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = online_sources.online_config_path(root)
            online_sources.write_json_atomic(
                config_path,
                online_sources.build_online_config([source_a], updated_at="2026-07-16T00:00:00Z"),
            )
            online_sources.write_online_opml(root, [source_a, source_b])

            result = online_sources.read_online_source_config(root)

        self.assertEqual(
            [source["locator"] for source in result["sources"]],
            ["https://example.com/a.xml"],
        )

    def test_manifest_roundtrip_is_atomic_and_public_recovery_is_redacted(self):
        operation_id = "operation-123"
        manifest = {
            "schema_version": 1,
            "operation_id": operation_id,
            "operation_kind": "apply",
            "phase": "files_written",
            "created_at": "2026-07-16T00:00:00Z",
            "pre_head": "a" * 40,
            "branch": "master",
            "remote_name": "origin",
            "remote_ref": "refs/heads/master",
            "fetch_url_digest": "b" * 64,
            "push_url_digest": "b" * 64,
            "files": {
                "config/online-sources.json": {
                    "before_sha256": "c" * 64,
                    "after_sha256": "d" * 64,
                },
                "feeds/online-sources.opml": {
                    "before_sha256": "e" * 64,
                    "after_sha256": "f" * 64,
                },
            },
            "preview_hash": "1" * 64,
            "base_config_digest": "2" * 64,
            "operation_commit_oid": "",
            "stable_patch_id": "",
            "commit_trailer": f"AI-News-Radar-Operation: {operation_id}",
            "stash": {
                "message": f"ai-news-radar:{operation_id}",
                "oid": "a" * 40,
                "paths": [
                    {
                        "path": "data/private.json",
                        "before_exists": True,
                        "before_sha256": "3" * 64,
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(
                ["git", "init", "-b", "master"],
                cwd=root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            digest = online_sources.write_operation_manifest(root, manifest)
            loaded = online_sources.read_operation_manifest(root)
            public = online_sources.public_operation_recovery(
                loaded,
                actual_phase="files_written",
                outcome="saved_not_committed",
                recovery_pending=True,
                allowed_actions=["rollback", "retry_commit"],
            )
            manifest_path = online_sources.operation_manifest_path(root)

        self.assertEqual(loaded, manifest)
        self.assertEqual(digest, online_sources.operation_manifest_digest(manifest))
        self.assertEqual(
            set(public),
            {
                "operation_id",
                "manifest_digest",
                "operation_kind",
                "phase",
                "outcome",
                "recovery_pending",
                "allowed_actions",
                "created_at",
            },
        )
        serialized = json.dumps(public, ensure_ascii=False)
        for secret in [
            "a" * 40,
            "data/private.json",
            "AI-News-Radar-Operation",
            "fetch_url_digest",
            "before_sha256",
        ]:
            self.assertNotIn(secret, serialized)
        self.assertIn(".git", str(manifest_path))

    def test_manifest_rejects_untrusted_stash_oid_and_paths(self):
        root, _source, config = self.create_transaction_repo()
        target = online_sources._local_git_target(root)
        hashes = {
            path: online_sources.sha256_file(root / path)
            for path in online_sources._allowed_online_paths()
        }
        base = online_sources.new_operation_manifest(
            operation_kind="apply",
            target=target,
            before_hashes=hashes,
            after_hashes=hashes,
            base_config_digest=online_sources.online_config_digest(config),
        )
        cases = [
            {"oid": "not-an-object-id", "paths": []},
            {
                "oid": "a" * 40,
                "paths": [
                    {
                        "path": "../outside.json",
                        "before_exists": True,
                        "before_sha256": "b" * 64,
                    }
                ],
            },
            {
                "oid": "a" * 40,
                "paths": [
                    {
                        "path": "config/online-sources.json",
                        "before_exists": True,
                        "before_sha256": "b" * 64,
                    }
                ],
            },
        ]
        for stash in cases:
            manifest = {**base, "stash": {**base["stash"], **stash}}
            with self.subTest(stash=stash), self.assertRaises(
                online_sources.OnlineSourcesError
            ) as raised:
                online_sources.write_operation_manifest(root, manifest)
            self.assertEqual(raised.exception.code, "online_sources_recovery_mismatch")

    def test_canonical_remote_url_distinguishes_explicit_ports(self):
        root, _source, _config = self.create_transaction_repo()

        first = online_sources._canonical_git_remote_url(
            root,
            "https://example.com:8443/example/repo.git",
        )
        second = online_sources._canonical_git_remote_url(
            root,
            "https://example.com:9443/example/repo.git",
        )

        self.assertNotEqual(first, second)

    def test_canonical_remote_url_preserves_transport_user_authority_and_query(self):
        root, _source, _config = self.create_transaction_repo()
        values = [
            "https://example.com/example/repo.git?mirror=one",
            "ssh://example.com/example/repo.git?mirror=one",
            "alice@example.com:example/repo.git",
            "bob@example.com:example/repo.git",
            "file://server-a/share/example/repo.git",
            "file://server-b/share/example/repo.git",
            "https://example.com/example/repo.git?mirror=two",
        ]

        canonical = {
            online_sources._canonical_git_remote_url(root, value)
            for value in values
        }

        self.assertEqual(len(canonical), len(values))
        with self.assertRaises(online_sources.OnlineSourcesError) as raised:
            online_sources._canonical_git_remote_url(
                root,
                "https://user:password@example.com/example/repo.git",
            )
        self.assertEqual(raised.exception.code, "online_sources_preflight_failed")

    def test_fresh_apply_accepts_clean_autocrlf_worktree(self):
        root, source, config = self.create_transaction_repo()
        self.git(root, "config", "core.autocrlf", "true")
        for relative_path in online_sources._allowed_online_paths():
            path = root / relative_path
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(
            self.git(
                root,
                "diff",
                "--name-only",
                "--",
                *online_sources._allowed_online_paths(),
            ).stdout,
            "",
        )
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )

        result = online_sources.apply_online_source_config_operation(
            root,
            candidate,
            operation_kind="apply",
            base_config_digest=online_sources.online_config_digest(config),
            preview_hash="e" * 64,
            summary={"added": []},
        )

        self.assertEqual(result["outcome"], "pushed")
        self.assertFalse(result["partial"])

    def test_preflight_rejects_multiple_push_urls(self):
        root, _source, _config = self.create_transaction_repo()
        original = self.git(root, "remote", "get-url", "origin").stdout.strip()
        replacement = root.parent / "second-push.git"
        self.git(root.parent, "clone", "--bare", original, str(replacement))
        self.git(root, "remote", "set-url", "--add", "--push", "origin", original)
        self.git(root, "remote", "set-url", "--add", "--push", "origin", str(replacement))

        with self.assertRaises(online_sources.OnlineSourcesError) as raised:
            online_sources.fresh_git_preflight(root)

        self.assertEqual(raised.exception.code, "online_sources_preflight_failed")
        self.assertEqual(raised.exception.details.get("reason"), "remote_url_ambiguous")

    def test_manual_save_no_change_preserves_bytes_timestamp_and_head(self):
        root, source, config = self.create_transaction_repo()
        config_path = online_sources.online_config_path(root)
        opml_path = online_sources.online_opml_path(root)
        before = {
            "config": config_path.read_bytes(),
            "opml": opml_path.read_bytes(),
            "head": self.git(root, "rev-parse", "HEAD").stdout.strip(),
        }
        digest = online_sources.online_config_digest(config)

        result = online_sources.save_online_source_config_transaction(
            root,
            {"sources": [source]},
            if_match=f'"{digest}"',
        )

        self.assertFalse(result["config_changed"])
        self.assertEqual(result["base_config_digest"], digest)
        self.assertEqual(config_path.read_bytes(), before["config"])
        self.assertEqual(opml_path.read_bytes(), before["opml"])
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), before["head"])
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_manual_save_writes_opml_before_json_and_returns_new_etag(self):
        root, source, config = self.create_transaction_repo()
        config_path = online_sources.online_config_path(root)
        opml_path = online_sources.online_opml_path(root)
        digest = online_sources.online_config_digest(config)
        writes: list[str] = []
        original_replace = online_sources.atomic_replace_bytes

        def recording_replace(path: Path, content: bytes) -> None:
            if path in {config_path, opml_path}:
                writes.append(path.name)
            original_replace(path, content)

        with patch.object(online_sources, "atomic_replace_bytes", side_effect=recording_replace):
            result = online_sources.save_online_source_config_transaction(
                root,
                {"sources": [{**source, "name": "Renamed Feed"}]},
                if_match=f'"{digest}"',
            )

        self.assertEqual(writes, ["online-sources.opml", "online-sources.json"])
        self.assertTrue(result["config_changed"])
        self.assertNotEqual(result["base_config_digest"], digest)
        self.assertEqual(result["etag"], f'"{result["base_config_digest"]}"')
        self.assertEqual(result["config"]["sources"][0]["name"], "Renamed Feed")
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_manual_save_stale_etag_does_not_write_or_create_manifest(self):
        root, source, _config = self.create_transaction_repo()
        config_path = online_sources.online_config_path(root)
        opml_path = online_sources.online_opml_path(root)
        before = (config_path.read_bytes(), opml_path.read_bytes())

        with patch.object(online_sources, "atomic_replace_bytes") as replace_mock:
            with self.assertRaises(online_sources.OnlineSourcesError) as raised:
                online_sources.save_online_source_config_transaction(
                    root,
                    {"sources": [{**source, "name": "Renamed Feed"}]},
                    if_match='"' + "9" * 64 + '"',
                )

        self.assertEqual(raised.exception.code, "online_sources_config_stale")
        replace_mock.assert_not_called()
        self.assertEqual((config_path.read_bytes(), opml_path.read_bytes()), before)
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_manual_save_json_failure_repairs_opml_from_current_json(self):
        root, source, config = self.create_transaction_repo()
        config_path = online_sources.online_config_path(root)
        opml_path = online_sources.online_opml_path(root)
        config_before = config_path.read_bytes()
        expected_opml, _ = online_sources.render_online_opml_bytes([source])
        digest = online_sources.online_config_digest(config)
        original_replace = online_sources.atomic_replace_bytes
        failed = False

        def fail_json_once(path: Path, content: bytes) -> None:
            nonlocal failed
            if path == config_path and not failed:
                failed = True
                raise OSError("injected json replace failure")
            original_replace(path, content)

        with patch.object(online_sources, "atomic_replace_bytes", side_effect=fail_json_once):
            with self.assertRaises(online_sources.OnlineSourcesError) as raised:
                online_sources.save_online_source_config_transaction(
                    root,
                    {"sources": [{**source, "name": "Renamed Feed"}]},
                    if_match=f'"{digest}"',
                )

        self.assertEqual(raised.exception.code, "online_sources_write_failed")
        self.assertEqual(config_path.read_bytes(), config_before)
        self.assertEqual(opml_path.read_bytes(), expected_opml)
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_manual_save_audit_repairs_derived_opml_from_current_json(self):
        root, source, config = self.create_transaction_repo()
        config_path = online_sources.online_config_path(root)
        opml_path = online_sources.online_opml_path(root)
        target = online_sources._local_git_target(root)
        before_hashes = {
            "config/online-sources.json": online_sources.sha256_file(config_path),
            "feeds/online-sources.opml": online_sources.sha256_file(opml_path),
        }
        changed_source = {**source, "name": "Interrupted Feed"}
        changed_config = online_sources.build_online_config(
            [changed_source],
            updated_at="2026-07-16T01:00:00Z",
        )
        changed_opml, _ = online_sources.render_online_opml_bytes([changed_source])
        manifest = online_sources.new_operation_manifest(
            operation_kind="manual_save",
            target=target,
            before_hashes=before_hashes,
            after_hashes={
                "config/online-sources.json": online_sources.sha256_bytes(
                    online_sources.render_json_bytes(changed_config)
                ),
                "feeds/online-sources.opml": online_sources.sha256_bytes(changed_opml),
            },
            base_config_digest=online_sources.online_config_digest(config),
        )
        manifest["phase"] = "write_incomplete"
        online_sources.write_operation_manifest(root, manifest)
        online_sources.atomic_replace_bytes(opml_path, changed_opml)

        recovery = online_sources.audit_online_source_operation(root)

        expected_opml, _ = online_sources.render_online_opml_bytes([source])
        self.assertIsNone(recovery)
        self.assertEqual(config_path.read_bytes(), online_sources.render_json_bytes(config))
        self.assertEqual(opml_path.read_bytes(), expected_opml)
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_manual_save_entry_audits_repairable_manifest_before_writing(self):
        root, source, config = self.create_transaction_repo()
        config_path = online_sources.online_config_path(root)
        opml_path = online_sources.online_opml_path(root)
        target = online_sources._local_git_target(root)
        changed_source = {**source, "name": "Interrupted Feed"}
        changed_config = online_sources.build_online_config(
            [changed_source],
            updated_at="2026-07-16T01:00:00Z",
        )
        changed_opml, _ = online_sources.render_online_opml_bytes([changed_source])
        manifest = online_sources.new_operation_manifest(
            operation_kind="manual_save",
            target=target,
            before_hashes={
                "config/online-sources.json": online_sources.sha256_file(config_path),
                "feeds/online-sources.opml": online_sources.sha256_file(opml_path),
            },
            after_hashes={
                "config/online-sources.json": online_sources.sha256_bytes(
                    online_sources.render_json_bytes(changed_config)
                ),
                "feeds/online-sources.opml": online_sources.sha256_bytes(changed_opml),
            },
            base_config_digest=online_sources.online_config_digest(config),
        )
        manifest["phase"] = "write_incomplete"
        online_sources.write_operation_manifest(root, manifest)
        online_sources.atomic_replace_bytes(opml_path, changed_opml)

        result = online_sources.save_online_source_config_transaction(
            root,
            {"sources": [source]},
            if_match=online_sources.online_config_etag(config),
        )

        expected_opml, _ = online_sources.render_online_opml_bytes([source])
        self.assertFalse(result["config_changed"])
        self.assertEqual(config_path.read_bytes(), online_sources.render_json_bytes(config))
        self.assertEqual(opml_path.read_bytes(), expected_opml)
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_manual_sync_rejects_stale_digest_without_git_mutation(self):
        root, source, config = self.create_transaction_repo()
        saved = online_sources.save_online_source_config_transaction(
            root,
            {"sources": [{**source, "name": "Saved Draft"}]},
            if_match=online_sources.online_config_etag(config),
        )
        head_before = self.git(root, "rev-parse", "HEAD").stdout.strip()
        index_before = self.git(root, "write-tree").stdout.strip()

        with self.assertRaises(online_sources.OnlineSourcesError) as raised:
            online_sources.sync_saved_online_source_config(
                root,
                if_match='"' + "9" * 64 + '"',
            )

        self.assertEqual(raised.exception.code, "online_sources_config_stale")
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), head_before)
        self.assertEqual(self.git(root, "write-tree").stdout.strip(), index_before)
        self.assertEqual(
            online_sources.online_config_digest(
                json.loads(online_sources.online_config_path(root).read_text(encoding="utf-8"))
            ),
            saved["base_config_digest"],
        )
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_manual_sync_pushes_one_owned_operation_commit_to_fixed_ref(self):
        root, source, config = self.create_transaction_repo()
        saved = online_sources.save_online_source_config_transaction(
            root,
            {"sources": [{**source, "name": "Saved Draft"}]},
            if_match=online_sources.online_config_etag(config),
        )

        result = online_sources.sync_saved_online_source_config(
            root,
            if_match=saved["etag"],
        )

        local_head = self.git(root, "rev-parse", "HEAD").stdout.strip()
        remote_head = self.git(root, "rev-parse", "refs/remotes/origin/master").stdout.strip()
        changed_paths = self.git(
            root,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            local_head,
        ).stdout.splitlines()
        message = self.git(root, "show", "-s", "--format=%B", local_head).stdout

        self.assertEqual(result["outcome"], "pushed")
        self.assertTrue(result["ok"])
        self.assertTrue(result["pushed"])
        self.assertEqual(local_head, remote_head)
        self.assertEqual(
            set(changed_paths),
            {"config/online-sources.json", "feeds/online-sources.opml"},
        )
        self.assertIn("AI-News-Radar-Operation:", message)
        self.assertRegex(result["commit"], "^[0-9a-f]{40}$")
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

        before_repeat = {
            "head": local_head,
            "config": online_sources.online_config_path(root).read_bytes(),
            "opml": online_sources.online_opml_path(root).read_bytes(),
        }
        repeated = online_sources.sync_saved_online_source_config(
            root,
            if_match=result["etag"],
        )
        self.assertEqual(repeated["outcome"], "no_change")
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), before_repeat["head"])
        self.assertEqual(online_sources.online_config_path(root).read_bytes(), before_repeat["config"])
        self.assertEqual(online_sources.online_opml_path(root).read_bytes(), before_repeat["opml"])

    def test_manual_sync_rejects_config_change_during_fetch(self):
        root, source, config = self.create_transaction_repo()
        saved = online_sources.save_online_source_config_transaction(
            root,
            {"sources": [{**source, "name": "Saved Draft"}]},
            if_match=online_sources.online_config_etag(config),
        )
        concurrent_source = {**source, "name": "Concurrent Draft"}
        concurrent_config = online_sources.build_online_config(
            [concurrent_source],
            updated_at="2026-07-16T02:00:00Z",
        )
        concurrent_config_bytes = online_sources.render_json_bytes(concurrent_config)
        concurrent_opml_bytes, _ = online_sources.render_online_opml_bytes([concurrent_source])
        head_before = self.git(root, "rev-parse", "HEAD").stdout.strip()
        remote_before = self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0]
        original_git_checked = online_sources.git_checked
        injected = False

        def change_config_after_fetch(root_dir: Path, args: list[str], timeout: int = 60):
            nonlocal injected
            completed = original_git_checked(root_dir, args, timeout=timeout)
            if args and args[0] == "fetch" and not injected:
                injected = True
                online_sources.atomic_replace_bytes(
                    online_sources.online_opml_path(root_dir),
                    concurrent_opml_bytes,
                )
                online_sources.atomic_replace_bytes(
                    online_sources.online_config_path(root_dir),
                    concurrent_config_bytes,
                )
            return completed

        with patch.object(online_sources, "git_checked", side_effect=change_config_after_fetch):
            with self.assertRaises(online_sources.OnlineSourcesError) as raised:
                online_sources.sync_saved_online_source_config(root, if_match=saved["etag"])

        self.assertIn(
            raised.exception.code,
            {"online_sources_config_stale", "online_sources_preflight_failed"},
        )
        self.assertEqual(online_sources.online_config_path(root).read_bytes(), concurrent_config_bytes)
        self.assertEqual(online_sources.online_opml_path(root).read_bytes(), concurrent_opml_bytes)
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), head_before)
        self.assertEqual(
            self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0],
            remote_before,
        )
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_apply_rejects_config_change_during_fetch_without_overwrite(self):
        root, source, config = self.create_transaction_repo()
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        external_source = {**source, "name": "External Edit"}
        external_config = online_sources.build_online_config(
            [external_source],
            updated_at="2026-07-16T03:00:00Z",
        )
        external_config_bytes = online_sources.render_json_bytes(external_config)
        external_opml_bytes, _ = online_sources.render_online_opml_bytes([external_source])
        head_before = self.git(root, "rev-parse", "HEAD").stdout.strip()
        remote_before = self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0]
        original_git_checked = online_sources.git_checked
        injected = False

        def change_config_after_fetch(root_dir: Path, args: list[str], timeout: int = 60):
            nonlocal injected
            completed = original_git_checked(root_dir, args, timeout=timeout)
            if args and args[0] == "fetch" and not injected:
                injected = True
                online_sources.atomic_replace_bytes(
                    online_sources.online_opml_path(root_dir),
                    external_opml_bytes,
                )
                online_sources.atomic_replace_bytes(
                    online_sources.online_config_path(root_dir),
                    external_config_bytes,
                )
            return completed

        with patch.object(online_sources, "git_checked", side_effect=change_config_after_fetch):
            with self.assertRaises(online_sources.OnlineSourcesError) as raised:
                online_sources.apply_online_source_config_operation(
                    root,
                    candidate,
                    operation_kind="apply",
                    base_config_digest=online_sources.online_config_digest(config),
                    preview_hash="2" * 64,
                    summary={"added": []},
                )

        self.assertIn(
            raised.exception.code,
            {"online_sources_config_stale", "online_sources_preflight_failed"},
        )
        self.assertEqual(online_sources.online_config_path(root).read_bytes(), external_config_bytes)
        self.assertEqual(online_sources.online_opml_path(root).read_bytes(), external_opml_bytes)
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), head_before)
        self.assertEqual(
            self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0],
            remote_before,
        )
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_apply_second_file_failure_restores_both_files_and_index(self):
        root, source, config = self.create_transaction_repo()
        config_path = online_sources.online_config_path(root)
        opml_path = online_sources.online_opml_path(root)
        before = (config_path.read_bytes(), opml_path.read_bytes())
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        original_replace = online_sources.atomic_replace_bytes
        failed = False

        def fail_config_once(path: Path, content: bytes) -> None:
            nonlocal failed
            if path == config_path and not failed:
                failed = True
                raise OSError("injected config replace failure")
            original_replace(path, content)

        with patch.object(online_sources, "atomic_replace_bytes", side_effect=fail_config_once):
            with self.assertRaises(online_sources.OnlineSourcesError) as raised:
                online_sources.apply_online_source_config_operation(
                    root,
                    candidate,
                    operation_kind="apply",
                    base_config_digest=online_sources.online_config_digest(config),
                    preview_hash="1" * 64,
                    summary={"added": []},
                )

        self.assertEqual(raised.exception.code, "online_sources_write_failed")
        self.assertEqual((config_path.read_bytes(), opml_path.read_bytes()), before)
        self.assertEqual(self.git(root, "diff", "--cached", "--name-only").stdout, "")
        self.assertEqual(self.git(root, "diff", "--name-only").stdout, "")
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_apply_write_failure_never_overwrites_third_party_file_state(self):
        root, source, config = self.create_transaction_repo()
        config_path = online_sources.online_config_path(root)
        opml_path = online_sources.online_opml_path(root)
        config_before = config_path.read_bytes()
        external_opml = b"external concurrent OPML bytes\n"
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        original_replace = online_sources.atomic_replace_bytes
        failed = False

        def inject_external_opml_then_fail(path: Path, content: bytes) -> None:
            nonlocal failed
            if path == config_path and not failed:
                failed = True
                original_replace(opml_path, external_opml)
                raise OSError("injected config replace failure after external edit")
            original_replace(path, content)

        with patch.object(
            online_sources,
            "atomic_replace_bytes",
            side_effect=inject_external_opml_then_fail,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="3" * 64,
                summary={"added": []},
            )

        self.assertEqual(result["outcome"], "saved_not_committed")
        self.assertFalse(result["config_changed"])
        self.assertEqual(
            result["base_config_digest"],
            online_sources.online_config_digest(config),
        )
        self.assertEqual(result["etag"], online_sources.online_config_etag(config))
        self.assertEqual(result["recovery"]["allowed_actions"], [])
        self.assertEqual(config_path.read_bytes(), config_before)
        self.assertEqual(opml_path.read_bytes(), external_opml)
        self.assertTrue(online_sources.operation_manifest_path(root).exists())

    def test_apply_commit_failure_is_saved_not_committed_with_trusted_manifest(self):
        root, source, config = self.create_transaction_repo()
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        original_git_checked = online_sources.git_checked

        def fail_commit(root_dir: Path, args: list[str], timeout: int = 60):
            if args and args[0] == "commit-tree":
                raise RuntimeError("injected commit failure")
            return original_git_checked(root_dir, args, timeout=timeout)

        with patch.object(online_sources, "git_checked", side_effect=fail_commit):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="2" * 64,
                summary={"added": []},
            )

        manifest = online_sources.read_operation_manifest(root)
        self.assertEqual(result["outcome"], "saved_not_committed")
        self.assertFalse(result["ok"])
        self.assertTrue(result["partial"])
        self.assertTrue(result["write_complete"])
        self.assertTrue(result["recovery_pending"])
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["phase"], "files_written")
        self.assertEqual(manifest["operation_commit_oid"], "")
        self.assertEqual(
            set(self.git(root, "diff", "--cached", "--name-only").stdout.splitlines()),
            {"config/online-sources.json", "feeds/online-sources.opml"},
        )

    def create_saved_not_committed_operation(self):
        root, source, config = self.create_transaction_repo()
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        original_git_checked = online_sources.git_checked

        def fail_commit(root_dir: Path, args: list[str], timeout: int = 60):
            if args and args[0] == "commit-tree":
                raise RuntimeError("injected commit failure")
            return original_git_checked(root_dir, args, timeout=timeout)

        with patch.object(online_sources, "git_checked", side_effect=fail_commit):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="3" * 64,
                summary={"added": []},
            )
        return root, config, result

    def test_recovery_rejects_old_operation_or_manifest_digest(self):
        root, _config, result = self.create_saved_not_committed_operation()
        recovery = result["recovery"]
        cases = [
            {**recovery, "operation_id": "old-operation"},
            {**recovery, "manifest_digest": "9" * 64},
        ]
        for request in cases:
            with self.subTest(request=request), self.assertRaises(
                online_sources.OnlineSourcesError
            ) as raised:
                online_sources.recover_online_source_operation(
                    root,
                    action="rollback",
                    operation_id=request["operation_id"],
                    manifest_digest=request["manifest_digest"],
                    confirmed=True,
                )
            self.assertEqual(raised.exception.code, "online_sources_recovery_mismatch")
        self.assertTrue(online_sources.operation_manifest_path(root).exists())

    def test_recovery_rollback_restores_staged_and_worktree(self):
        root, original_config, result = self.create_saved_not_committed_operation()
        recovery = result["recovery"]

        rolled_back = online_sources.recover_online_source_operation(
            root,
            action="rollback",
            operation_id=recovery["operation_id"],
            manifest_digest=recovery["manifest_digest"],
            confirmed=True,
        )

        self.assertEqual(rolled_back["outcome"], "no_change")
        self.assertEqual(
            online_sources.online_config_digest(rolled_back["config"]),
            online_sources.online_config_digest(original_config),
        )
        self.assertEqual(self.git(root, "diff", "--cached", "--name-only").stdout, "")
        self.assertEqual(self.git(root, "diff", "--name-only").stdout, "")
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_recovery_retry_commit_uses_existing_bytes_and_pushes_once(self):
        root, _config, result = self.create_saved_not_committed_operation()
        recovery = result["recovery"]
        config_before = online_sources.online_config_path(root).read_bytes()

        retried = online_sources.recover_online_source_operation(
            root,
            action="retry_commit",
            operation_id=recovery["operation_id"],
            manifest_digest=recovery["manifest_digest"],
        )

        self.assertEqual(retried["outcome"], "pushed")
        self.assertEqual(online_sources.online_config_path(root).read_bytes(), config_before)
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_saved_recovery_blocks_merge_and_cherry_pick_states(self):
        for state_name in ("MERGE_HEAD", "CHERRY_PICK_HEAD"):
            with self.subTest(state_name=state_name):
                root, _config, result = self.create_saved_not_committed_operation()
                config_before = online_sources.online_config_path(root).read_bytes()
                opml_before = online_sources.online_opml_path(root).read_bytes()
                state_path = online_sources._git_path(root, state_name)
                state_path.write_text(
                    self.git(root, "rev-parse", "HEAD").stdout.strip() + "\n",
                    encoding="ascii",
                )

                recovery = online_sources.audit_online_source_operation(root)

                self.assertEqual(recovery["allowed_actions"], [])
                with self.assertRaises(online_sources.OnlineSourcesError) as raised:
                    online_sources.recover_online_source_operation(
                        root,
                        action="rollback",
                        operation_id=result["recovery"]["operation_id"],
                        manifest_digest=result["recovery"]["manifest_digest"],
                        confirmed=True,
                    )
                self.assertEqual(raised.exception.code, "online_sources_recovery_mismatch")
                self.assertEqual(online_sources.online_config_path(root).read_bytes(), config_before)
                self.assertEqual(online_sources.online_opml_path(root).read_bytes(), opml_before)
                self.assertTrue(state_path.exists())
                self.assertTrue(online_sources.operation_manifest_path(root).exists())

    def test_remote_drift_blocks_retry_but_preserves_local_rollback(self):
        root, original_config, _result = self.create_saved_not_committed_operation()
        replacement = root.parent / "replacement-origin.git"
        self.git(root.parent, "init", "--bare", str(replacement))
        self.git(root, "remote", "set-url", "origin", str(replacement))

        recovery = online_sources.audit_online_source_operation(root)

        self.assertEqual(recovery["allowed_actions"], ["rollback"])
        rolled_back = online_sources.recover_online_source_operation(
            root,
            action="rollback",
            operation_id=recovery["operation_id"],
            manifest_digest=recovery["manifest_digest"],
            confirmed=True,
        )
        self.assertEqual(rolled_back["outcome"], "no_change")
        self.assertEqual(
            rolled_back["base_config_digest"],
            online_sources.online_config_digest(original_config),
        )
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_retry_commit_stops_if_merge_starts_after_audit(self):
        root, _config, result = self.create_saved_not_committed_operation()
        recovery = result["recovery"]
        remote_before = self.git(
            root,
            "ls-remote",
            "origin",
            "refs/heads/master",
        ).stdout.split()[0]
        original_audit = online_sources.audit_online_source_operation
        injected = False

        def audit_then_start_merge(root_dir: Path):
            nonlocal injected
            audited = original_audit(root_dir)
            if not injected:
                injected = True
                online_sources._git_path(root_dir, "MERGE_HEAD").write_text(
                    self.git(root_dir, "rev-parse", "HEAD").stdout.strip() + "\n",
                    encoding="ascii",
                )
            return audited

        with patch.object(
            online_sources,
            "audit_online_source_operation",
            side_effect=audit_then_start_merge,
        ):
            retried = online_sources.recover_online_source_operation(
                root,
                action="retry_commit",
                operation_id=recovery["operation_id"],
                manifest_digest=recovery["manifest_digest"],
            )

        self.assertTrue(injected)
        self.assertEqual(retried["outcome"], "saved_not_committed")
        self.assertEqual(retried["recovery"]["allowed_actions"], [])
        self.assertEqual(
            self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0],
            remote_before,
        )
        self.assertTrue(online_sources._git_path(root, "MERGE_HEAD").exists())

    def test_recovery_retry_push_reuses_owned_commit(self):
        root, source, config = self.create_transaction_repo()
        saved = online_sources.save_online_source_config_transaction(
            root,
            {"sources": [{**source, "name": "Saved Draft"}]},
            if_match=online_sources.online_config_etag(config),
        )
        original_git_checked = online_sources.git_checked

        def fail_push(root_dir: Path, args: list[str], timeout: int = 60):
            if args and args[0] == "push":
                raise RuntimeError("injected push failure")
            return original_git_checked(root_dir, args, timeout=timeout)

        with patch.object(online_sources, "git_checked", side_effect=fail_push):
            partial = online_sources.sync_saved_online_source_config(
                root,
                if_match=saved["etag"],
            )
        recovery = partial["recovery"]
        commit_before = partial["commit"]

        retried = online_sources.recover_online_source_operation(
            root,
            action="retry_push",
            operation_id=recovery["operation_id"],
            manifest_digest=recovery["manifest_digest"],
        )

        self.assertEqual(partial["outcome"], "committed_not_pushed")
        self.assertEqual(retried["outcome"], "pushed")
        self.assertEqual(retried["commit"], commit_before)
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_push_timeout_after_remote_receive_is_reported_as_pushed(self):
        root, source, config = self.create_transaction_repo()
        saved = online_sources.save_online_source_config_transaction(
            root,
            {"sources": [{**source, "name": "Saved Draft"}]},
            if_match=online_sources.online_config_etag(config),
        )
        original_git_checked = online_sources.git_checked

        def push_then_timeout(root_dir: Path, args: list[str], timeout: int = 60):
            if args and args[0] == "push":
                original_git_checked(root_dir, args, timeout=timeout)
                raise subprocess.TimeoutExpired(args, timeout)
            return original_git_checked(root_dir, args, timeout=timeout)

        with patch.object(online_sources, "git_checked", side_effect=push_then_timeout):
            result = online_sources.sync_saved_online_source_config(
                root,
                if_match=saved["etag"],
            )

        self.assertEqual(result["outcome"], "pushed")
        self.assertTrue(result["pushed"])
        self.assertFalse(result["partial"])
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def create_manifest_then_commit_without_manifest_update(self):
        root, source, config = self.create_transaction_repo()
        saved = online_sources.save_online_source_config_transaction(
            root,
            {"sources": [{**source, "name": "Saved Draft"}]},
            if_match=online_sources.online_config_etag(config),
        )
        target = online_sources._manual_sync_git_preflight(root)
        before_hashes = {
            path: online_sources.sha256_bytes(
                online_sources._git_blob_bytes(root, target["pre_head"], path)
            )
            for path in online_sources._allowed_online_paths()
        }
        after_hashes = {
            path: online_sources.sha256_file(root / path)
            for path in online_sources._allowed_online_paths()
        }
        manifest = online_sources.new_operation_manifest(
            operation_kind="manual_sync",
            target=target,
            before_hashes=before_hashes,
            after_hashes=after_hashes,
            base_config_digest=saved["base_config_digest"],
        )
        manifest["phase"] = "files_written"
        online_sources.write_operation_manifest(root, manifest)
        self.git(root, "add", *online_sources._allowed_online_paths())
        self.git(
            root,
            "commit",
            "-m",
            "配置：同步线上信源",
            "-m",
            manifest["commit_trailer"],
            "--",
            *online_sources._allowed_online_paths(),
        )
        return root, manifest

    def create_proven_owned_paused_rebase(self):
        root, manifest = self.create_manifest_then_commit_without_manifest_update()
        operation_oid = self.git(root, "rev-parse", "HEAD").stdout.strip()
        patch_id = online_sources._verify_operation_commit(
            root,
            manifest,
            operation_oid,
            require_pre_head_parent=True,
        )
        manifest["phase"] = "rebasing"
        manifest["operation_commit_oid"] = operation_oid
        manifest["stable_patch_id"] = patch_id
        online_sources.write_operation_manifest(root, manifest)

        origin = Path(self.git(root, "remote", "get-url", "origin").stdout.strip())
        peer = root.parent / "owned-rebase-peer"
        self.git(root.parent, "clone", str(origin), str(peer))
        self.git(peer, "config", "user.name", "Test")
        self.git(peer, "config", "user.email", "test@example.com")
        self.git(peer, "config", "core.autocrlf", "false")
        remote_data = peer / "data" / "latest-24h.json"
        remote_data.write_text('{"version":"remote-owned-rebase"}\n', encoding="utf-8")
        self.git(peer, "add", "data/latest-24h.json")
        self.git(peer, "commit", "-m", "remote data snapshot")
        self.git(peer, "push", "origin", "master")
        self.git(root, "fetch", "origin", "refs/heads/master")
        paused = online_sources.git_run(
            root,
            ["rebase", "--exec", "false", "FETCH_HEAD"],
            timeout=60,
        )
        self.assertNotEqual(paused.returncode, 0)
        self.assertTrue(online_sources._git_path(root, "rebase-merge").exists())
        return root, operation_oid

    def create_pushed_operation_with_pending_stash(self):
        root, _manifest = self.create_manifest_then_commit_without_manifest_update()
        online_sources.audit_online_source_operation(root)
        manifest = online_sources.read_operation_manifest(root)
        operation_oid = manifest["operation_commit_oid"]
        data_path = root / "data" / "latest-24h.json"
        expected_bytes = b'{"version":"owned-stash-crash"}\n'
        data_path.write_bytes(expected_bytes)
        manifest["stash"]["paths"] = [
            {
                "path": "data/latest-24h.json",
                "before_exists": True,
                "before_sha256": online_sources.sha256_file(data_path),
            }
        ]
        online_sources.write_operation_manifest(root, manifest)
        self.git(
            root,
            "--literal-pathspecs",
            "stash",
            "push",
            "-m",
            manifest["stash"]["message"],
            "--",
            "data/latest-24h.json",
        )
        stash_oid = self.git(root, "rev-parse", "refs/stash").stdout.strip()
        manifest["stash"]["oid"] = stash_oid
        online_sources.write_operation_manifest(root, manifest)
        self.git(root, "push", "origin", f"{operation_oid}:refs/heads/master")
        recovery = online_sources.audit_online_source_operation(root)
        return root, data_path, expected_bytes, stash_oid, recovery

    def test_audit_reconstructs_commit_after_crash_before_manifest_update(self):
        root, original_manifest = self.create_manifest_then_commit_without_manifest_update()
        head = self.git(root, "rev-parse", "HEAD").stdout.strip()

        recovery = online_sources.audit_online_source_operation(root)
        audited = online_sources.read_operation_manifest(root)

        self.assertEqual(recovery["outcome"], "committed_not_pushed")
        self.assertEqual(recovery["allowed_actions"], ["retry_push"])
        self.assertEqual(audited["operation_commit_oid"], head)
        self.assertRegex(audited["stable_patch_id"], "^[0-9a-f]{40}$")
        self.assertNotEqual(
            online_sources.operation_manifest_digest(audited),
            online_sources.operation_manifest_digest(original_manifest),
        )

    def test_recorded_dangling_operation_commit_is_not_downgraded_to_saved(self):
        root, _manifest = self.create_manifest_then_commit_without_manifest_update()
        online_sources.audit_online_source_operation(root)
        recorded = online_sources.read_operation_manifest(root)
        operation_oid = recorded["operation_commit_oid"]
        self.git(
            root,
            "update-ref",
            "refs/heads/master",
            recorded["pre_head"],
            operation_oid,
        )

        recovery = online_sources.audit_online_source_operation(root)

        self.assertEqual(recovery["outcome"], "committed_not_pushed")
        self.assertEqual(recovery["allowed_actions"], [])
        self.assertEqual(
            online_sources.read_operation_manifest(root)["operation_commit_oid"],
            operation_oid,
        )

    def test_committed_recovery_blocks_merge_and_cherry_pick_states(self):
        for state_name in ("MERGE_HEAD", "CHERRY_PICK_HEAD"):
            with self.subTest(state_name=state_name):
                root, _manifest = self.create_manifest_then_commit_without_manifest_update()
                online_sources.audit_online_source_operation(root)
                state_path = online_sources._git_path(root, state_name)
                state_path.write_text(
                    self.git(root, "rev-parse", "HEAD").stdout.strip() + "\n",
                    encoding="ascii",
                )

                recovery = online_sources.audit_online_source_operation(root)

                self.assertEqual(recovery["outcome"], "committed_not_pushed")
                self.assertEqual(recovery["allowed_actions"], [])
                self.assertTrue(state_path.exists())
                self.assertTrue(online_sources.operation_manifest_path(root).exists())

    def test_audit_does_not_trust_concurrently_rewritten_fetch_head(self):
        root, manifest = self.create_manifest_then_commit_without_manifest_update()
        operation_oid = self.git(root, "rev-parse", "HEAD").stdout.strip()
        manifest["phase"] = "committed"
        manifest["operation_commit_oid"] = operation_oid
        manifest["stable_patch_id"] = online_sources._verify_operation_commit(
            root,
            manifest,
            operation_oid,
            require_pre_head_parent=True,
        )
        online_sources.write_operation_manifest(root, manifest)
        remote_before = self.git(
            root,
            "ls-remote",
            "origin",
            "refs/heads/master",
        ).stdout.split()[0]
        original_git_checked = online_sources.git_checked
        injected = False

        def fetch_then_rewrite_fetch_head(root_dir: Path, args: list[str], timeout: int = 60):
            nonlocal injected
            completed = original_git_checked(root_dir, args, timeout=timeout)
            if args and args[0] == "fetch" and not injected:
                injected = True
                online_sources._git_path(root_dir, "FETCH_HEAD").write_text(
                    operation_oid + "\n",
                    encoding="ascii",
                )
            return completed

        with patch.object(
            online_sources,
            "git_checked",
            side_effect=fetch_then_rewrite_fetch_head,
        ):
            recovery = online_sources.audit_online_source_operation(root)

        self.assertTrue(injected)
        self.assertEqual(recovery["outcome"], "committed_not_pushed")
        self.assertEqual(recovery["allowed_actions"], ["retry_push"])
        self.assertTrue(online_sources.operation_manifest_path(root).exists())
        self.assertEqual(
            self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0],
            remote_before,
        )
        self.assertNotEqual(
            online_sources.git_run(
                root,
                ["merge-base", "--is-ancestor", operation_oid, remote_before],
            ).returncode,
            0,
        )

    def test_audit_preserves_fetch_head_during_foreign_merge(self):
        root, manifest = self.create_manifest_then_commit_without_manifest_update()
        operation_oid = self.git(root, "rev-parse", "HEAD").stdout.strip()
        manifest["phase"] = "committed"
        manifest["operation_commit_oid"] = operation_oid
        manifest["stable_patch_id"] = online_sources._verify_operation_commit(
            root,
            manifest,
            operation_oid,
            require_pre_head_parent=True,
        )
        online_sources.write_operation_manifest(root, manifest)
        fetch_head = online_sources._git_path(root, "FETCH_HEAD")
        fetch_head.write_bytes(b"user fetch metadata\n")
        online_sources._git_path(root, "MERGE_HEAD").write_text(
            manifest["pre_head"] + "\n",
            encoding="ascii",
        )

        recovery = online_sources.audit_online_source_operation(root)

        self.assertEqual(recovery["outcome"], "committed_not_pushed")
        self.assertEqual(recovery["allowed_actions"], [])
        self.assertEqual(fetch_head.read_bytes(), b"user fetch metadata\n")
        self.assertTrue(online_sources.operation_manifest_path(root).exists())

    def test_retry_push_stops_if_merge_starts_after_audit(self):
        root, _manifest = self.create_manifest_then_commit_without_manifest_update()
        recovery = online_sources.audit_online_source_operation(root)
        remote_before = self.git(
            root,
            "ls-remote",
            "origin",
            "refs/heads/master",
        ).stdout.split()[0]
        original_audit = online_sources.audit_online_source_operation
        injected = False

        def audit_then_start_merge(root_dir: Path):
            nonlocal injected
            audited = original_audit(root_dir)
            if not injected:
                injected = True
                online_sources._git_path(root_dir, "MERGE_HEAD").write_text(
                    self.git(root_dir, "rev-parse", "HEAD").stdout.strip() + "\n",
                    encoding="ascii",
                )
            return audited

        with patch.object(
            online_sources,
            "audit_online_source_operation",
            side_effect=audit_then_start_merge,
        ):
            with self.assertRaises(online_sources.OnlineSourcesError) as raised:
                online_sources.recover_online_source_operation(
                    root,
                    action="retry_push",
                    operation_id=recovery["operation_id"],
                    manifest_digest=recovery["manifest_digest"],
                )

        self.assertTrue(injected)
        self.assertEqual(raised.exception.code, "online_sources_recovery_mismatch")
        self.assertEqual(
            self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0],
            remote_before,
        )
        self.assertTrue(online_sources._git_path(root, "MERGE_HEAD").exists())
        self.assertTrue(online_sources.operation_manifest_path(root).exists())

    def test_audit_reconstructs_rebased_operation_oid(self):
        root, manifest = self.create_manifest_then_commit_without_manifest_update()
        old_oid = self.git(root, "rev-parse", "HEAD").stdout.strip()
        patch_id = online_sources._verify_operation_commit(
            root,
            manifest,
            old_oid,
            require_pre_head_parent=True,
        )
        manifest["phase"] = "rebasing"
        manifest["operation_commit_oid"] = old_oid
        manifest["stable_patch_id"] = patch_id
        online_sources.write_operation_manifest(root, manifest)

        base = root.parent
        peer = base / "peer"
        origin = Path(self.git(root, "remote", "get-url", "origin").stdout.strip())
        self.git(base, "clone", str(origin), str(peer))
        self.git(peer, "config", "user.name", "Test")
        self.git(peer, "config", "user.email", "test@example.com")
        self.git(peer, "config", "core.autocrlf", "false")
        remote_data = peer / "data" / "latest-24h.json"
        remote_data.parent.mkdir(exist_ok=True)
        remote_data.write_text('{"remote":true}\n', encoding="utf-8")
        self.git(peer, "add", "data/latest-24h.json")
        self.git(peer, "commit", "-m", "remote data snapshot")
        self.git(peer, "push")
        self.git(root, "fetch", "origin", "refs/heads/master")
        self.git(root, "rebase", "FETCH_HEAD")
        rebased_oid = self.git(root, "rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(rebased_oid, old_oid)

        recovery = online_sources.audit_online_source_operation(root)
        audited = online_sources.read_operation_manifest(root)

        self.assertEqual(recovery["outcome"], "committed_not_pushed")
        self.assertEqual(audited["operation_commit_oid"], rebased_oid)
        self.assertEqual(audited["stable_patch_id"], patch_id)

    def test_audit_recovers_stash_oid_by_unique_operation_message(self):
        root, _manifest = self.create_manifest_then_commit_without_manifest_update()
        online_sources.audit_online_source_operation(root)
        manifest = online_sources.read_operation_manifest(root)
        data_path = root / "data" / "latest-24h.json"
        data_path.write_text('{"version":"local"}\n', encoding="utf-8")
        expected_hash = online_sources.sha256_file(data_path)
        manifest["stash"]["paths"] = [
            {
                "path": "data/latest-24h.json",
                "before_exists": True,
                "before_sha256": expected_hash,
            }
        ]
        online_sources.write_operation_manifest(root, manifest)
        self.git(
            root,
            "stash",
            "push",
            "-m",
            manifest["stash"]["message"],
            "--",
            "data/latest-24h.json",
        )
        stash_oid = self.git(root, "rev-parse", "refs/stash").stdout.strip()

        recovery = online_sources.audit_online_source_operation(root)
        audited = online_sources.read_operation_manifest(root)

        self.assertEqual(audited["stash"]["oid"], stash_oid)
        self.assertEqual(recovery["outcome"], "committed_not_pushed")
        self.assertEqual(recovery["allowed_actions"], ["retry_push"])

    def test_pushed_commit_with_pending_stash_requires_restore_action(self):
        root, _manifest = self.create_manifest_then_commit_without_manifest_update()
        online_sources.audit_online_source_operation(root)
        manifest = online_sources.read_operation_manifest(root)
        operation_oid = manifest["operation_commit_oid"]
        data_path = root / "data" / "latest-24h.json"
        data_path.write_text('{"version":"local"}\n', encoding="utf-8")
        expected_hash = online_sources.sha256_file(data_path)
        manifest["stash"]["paths"] = [
            {
                "path": "data/latest-24h.json",
                "before_exists": True,
                "before_sha256": expected_hash,
            }
        ]
        online_sources.write_operation_manifest(root, manifest)
        self.git(
            root,
            "stash",
            "push",
            "-m",
            manifest["stash"]["message"],
            "--",
            "data/latest-24h.json",
        )
        self.git(root, "push", "origin", f"{operation_oid}:refs/heads/master")

        recovery = online_sources.audit_online_source_operation(root)
        audited = online_sources.read_operation_manifest(root)
        self.assertEqual(recovery["outcome"], "pushed")
        self.assertTrue(recovery["recovery_pending"])
        self.assertEqual(recovery["allowed_actions"], ["restore_worktree"])

        restored = online_sources.recover_online_source_operation(
            root,
            action="restore_worktree",
            operation_id=recovery["operation_id"],
            manifest_digest=recovery["manifest_digest"],
        )
        self.assertEqual(restored["outcome"], "pushed")
        self.assertFalse(restored["recovery_pending"])
        self.assertEqual(data_path.read_text(encoding="utf-8"), '{"version":"local"}\n')
        self.assertEqual(self.git(root, "stash", "list").stdout.strip(), "")
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_audit_continues_after_stash_restore_before_drop(self):
        root, data_path, expected_bytes, stash_oid, _recovery = (
            self.create_pushed_operation_with_pending_stash()
        )
        manifest = online_sources.read_operation_manifest(root)
        manifest, _digest = online_sources.update_operation_manifest(
            root,
            manifest,
            phase="restoring_worktree",
        )
        self.git(
            root,
            "--literal-pathspecs",
            "restore",
            f"--source={stash_oid}",
            "--worktree",
            "--",
            "data/latest-24h.json",
        )

        recovery = online_sources.audit_online_source_operation(root)

        self.assertEqual(recovery["outcome"], "pushed")
        self.assertEqual(recovery["allowed_actions"], ["restore_worktree"])
        completed = online_sources.recover_online_source_operation(
            root,
            action="restore_worktree",
            operation_id=recovery["operation_id"],
            manifest_digest=recovery["manifest_digest"],
        )
        self.assertEqual(completed["outcome"], "pushed")
        self.assertEqual(data_path.read_bytes(), expected_bytes)
        self.assertEqual(self.git(root, "stash", "list").stdout.strip(), "")
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_audit_finalizes_after_stash_drop_before_manifest_update(self):
        root, data_path, expected_bytes, stash_oid, _recovery = (
            self.create_pushed_operation_with_pending_stash()
        )
        manifest = online_sources.read_operation_manifest(root)
        online_sources.update_operation_manifest(
            root,
            manifest,
            phase="restoring_worktree",
        )
        self.git(
            root,
            "--literal-pathspecs",
            "restore",
            f"--source={stash_oid}",
            "--worktree",
            "--",
            "data/latest-24h.json",
        )
        selector = online_sources.git_stash_selector_for_oid(root, stash_oid)
        self.git(root, "stash", "drop", selector)

        recovery = online_sources.audit_online_source_operation(root)

        self.assertIsNone(recovery)
        self.assertEqual(data_path.read_bytes(), expected_bytes)
        self.assertEqual(self.git(root, "stash", "list").stdout.strip(), "")
        self.assertFalse(online_sources.operation_manifest_path(root).exists())

    def test_external_head_change_after_preflight_is_never_pushed(self):
        root, source, config = self.create_transaction_repo()
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        remote_before = self.git(root, "rev-parse", "refs/remotes/origin/master").stdout.strip()
        config_before = online_sources.online_config_path(root).read_bytes()
        opml_before = online_sources.online_opml_path(root).read_bytes()
        stash_before = self.git(root, "stash", "list", "--format=%H%x09%gs").stdout
        original_write_manifest = online_sources.write_operation_manifest
        injected = False

        def write_manifest_then_user_commit(root_dir: Path, manifest: dict):
            nonlocal injected
            digest = original_write_manifest(root_dir, manifest)
            if manifest["phase"] == "prepared" and not injected:
                injected = True
                user_path = Path(root_dir) / "user-note.txt"
                user_path.write_text("user commit\n", encoding="utf-8")
                self.git(root_dir, "add", "user-note.txt")
                self.git(root_dir, "commit", "-m", "user commit after preflight")
            return digest

        with patch.object(
            online_sources,
            "write_operation_manifest",
            side_effect=write_manifest_then_user_commit,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="6" * 64,
                summary={"added": []},
            )

        remote_after = self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0]
        self.assertTrue(injected)
        self.assertEqual(result["outcome"], "saved_not_committed")
        self.assertFalse(result["ok"])
        self.assertFalse(result["write_complete"])
        self.assertFalse(result["config_changed"])
        self.assertFalse(result["pushed"])
        self.assertTrue(result["partial"])
        self.assertTrue(result["recovery_pending"])
        self.assertEqual(result["recovery"]["phase"], "write_incomplete")
        self.assertEqual(result["recovery"]["allowed_actions"], [])
        self.assertEqual(
            result["base_config_digest"],
            online_sources.online_config_digest(config),
        )
        self.assertEqual(result["etag"], online_sources.online_config_etag(config))
        self.assertEqual(remote_after, remote_before)
        self.assertEqual(
            self.git(root, "show", "-s", "--format=%s", "HEAD").stdout.strip(),
            "user commit after preflight",
        )
        self.assertEqual(online_sources.online_config_path(root).read_bytes(), config_before)
        self.assertEqual(online_sources.online_opml_path(root).read_bytes(), opml_before)
        self.assertEqual(
            self.git(root, "stash", "list", "--format=%H%x09%gs").stdout,
            stash_before,
        )
        self.assertEqual(self.git(root, "status", "--porcelain").stdout, "")
        self.assertTrue(online_sources.operation_manifest_path(root).exists())
        manifest = online_sources.read_operation_manifest(root)
        self.assertEqual(manifest["pre_head"], remote_before)
        self.assertEqual(manifest["operation_commit_oid"], "")

    def test_auto_rollback_rechecks_state_immediately_before_restore(self):
        root, source, config = self.create_transaction_repo()
        config_path = online_sources.online_config_path(root)
        opml_path = online_sources.online_opml_path(root)
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        external_config = online_sources.build_online_config(
            [{**source, "name": "External Concurrent Feed"}],
            updated_at="2026-07-16T02:00:00Z",
        )
        external_bytes = online_sources.render_json_bytes(external_config)
        candidate_opml, _ = online_sources.render_online_opml_bytes(candidate["sources"])
        original_replace = online_sources.atomic_replace_bytes
        original_safe_states = online_sources._safe_write_rollback_states
        safe_checks = 0

        def fail_config_replace(path: Path, content: bytes) -> None:
            if path == config_path:
                raise OSError("injected config replace failure")
            original_replace(path, content)

        def inject_external_config_after_first_check(*args, **kwargs):
            nonlocal safe_checks
            states = original_safe_states(*args, **kwargs)
            safe_checks += 1
            if safe_checks == 1:
                config_path.write_bytes(external_bytes)
            return states

        with patch.object(
            online_sources,
            "atomic_replace_bytes",
            side_effect=fail_config_replace,
        ), patch.object(
            online_sources,
            "_safe_write_rollback_states",
            side_effect=inject_external_config_after_first_check,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="a" * 64,
                summary={"added": []},
            )

        self.assertGreaterEqual(safe_checks, 2)
        self.assertEqual(result["outcome"], "saved_not_committed")
        self.assertTrue(result["config_changed"])
        self.assertEqual(
            result["base_config_digest"],
            online_sources.online_config_digest(external_config),
        )
        self.assertEqual(result["recovery"]["allowed_actions"], [])
        self.assertEqual(config_path.read_bytes(), external_bytes)
        self.assertEqual(opml_path.read_bytes(), candidate_opml)
        self.assertTrue(online_sources.operation_manifest_path(root).exists())

    def test_commit_manifest_failure_reports_audited_committed_outcome(self):
        root, source, config = self.create_transaction_repo()
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        original_update_manifest = online_sources.update_operation_manifest
        failed = False

        def fail_first_committed_manifest_update(root_dir: Path, manifest: dict, **changes):
            nonlocal failed
            if (
                not failed
                and changes.get("phase") == "committed"
                and changes.get("operation_commit_oid")
            ):
                failed = True
                raise OSError("injected manifest update failure after update-ref")
            return original_update_manifest(root_dir, manifest, **changes)

        with patch.object(
            online_sources,
            "update_operation_manifest",
            side_effect=fail_first_committed_manifest_update,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="b" * 64,
                summary={"added": []},
            )

        manifest = online_sources.read_operation_manifest(root)
        self.assertTrue(failed)
        self.assertEqual(result["outcome"], "committed_not_pushed")
        self.assertEqual(result["outcome"], result["recovery"]["outcome"])
        self.assertEqual(result["commit"], manifest["operation_commit_oid"])
        self.assertFalse(result["pushed"])
        self.assertEqual(result["recovery"]["allowed_actions"], ["retry_push"])

    def test_commit_manifest_failure_reports_pushed_when_remote_contains_commit(self):
        root, source, config = self.create_transaction_repo()
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        original_update_manifest = online_sources.update_operation_manifest
        pushed_oid = ""

        def push_then_fail_committed_manifest_update(root_dir: Path, manifest: dict, **changes):
            nonlocal pushed_oid
            if (
                not pushed_oid
                and changes.get("phase") == "committed"
                and changes.get("operation_commit_oid")
            ):
                pushed_oid = changes["operation_commit_oid"]
                self.git(
                    root_dir,
                    "push",
                    "origin",
                    f"{pushed_oid}:refs/heads/master",
                )
                raise OSError("injected manifest update failure after remote push")
            return original_update_manifest(root_dir, manifest, **changes)

        with patch.object(
            online_sources,
            "update_operation_manifest",
            side_effect=push_then_fail_committed_manifest_update,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="c" * 64,
                summary={"added": []},
            )

        self.assertTrue(pushed_oid)
        self.assertEqual(result["outcome"], "pushed")
        self.assertTrue(result["pushed"])
        self.assertFalse(result["partial"])
        self.assertFalse(result["recovery_pending"])
        self.assertEqual(result["commit"], pushed_oid)
        self.assertNotIn("recovery", result)
        self.assertFalse(online_sources.operation_manifest_path(root).exists())
        self.assertEqual(
            self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0],
            pushed_oid,
        )

    def test_deleted_stash_path_is_not_confused_with_external_empty_file(self):
        root, _manifest = self.create_manifest_then_commit_without_manifest_update()
        online_sources.audit_online_source_operation(root)
        manifest = online_sources.read_operation_manifest(root)
        operation_oid = manifest["operation_commit_oid"]
        self.git(root, "push", "origin", f"{operation_oid}:refs/heads/master")
        data_path = root / "data" / "latest-24h.json"
        data_path.unlink()
        manifest["stash"]["paths"] = [
            {
                "path": "data/latest-24h.json",
                "before_exists": False,
                "before_sha256": online_sources.sha256_bytes(b""),
            }
        ]
        online_sources.write_operation_manifest(root, manifest)
        self.git(
            root,
            "--literal-pathspecs",
            "stash",
            "push",
            "--keep-index",
            "-m",
            manifest["stash"]["message"],
            "--",
            "data/latest-24h.json",
        )
        manifest["phase"] = "restoring_worktree"
        manifest["stash"]["oid"] = self.git(
            root,
            "rev-parse",
            "--verify",
            "refs/stash",
        ).stdout.strip()
        online_sources.write_operation_manifest(root, manifest)
        data_path.write_bytes(b"")

        recovery = online_sources.audit_online_source_operation(root)

        self.assertEqual(recovery["outcome"], "pushed")
        self.assertEqual(recovery["allowed_actions"], [])
        self.assertTrue(data_path.exists())
        self.assertEqual(data_path.read_bytes(), b"")
        self.assertTrue(online_sources.operation_manifest_path(root).exists())
        self.assertNotEqual(self.git(root, "stash", "list").stdout.strip(), "")

    def test_audit_does_not_finalize_pushed_operation_with_dirty_config(self):
        root, _manifest = self.create_manifest_then_commit_without_manifest_update()
        recovery = online_sources.audit_online_source_operation(root)
        manifest = online_sources.read_operation_manifest(root)
        operation_oid = manifest["operation_commit_oid"]
        self.git(root, "push", "origin", f"{operation_oid}:refs/heads/master")
        config_path = online_sources.online_config_path(root)
        config_path.write_bytes(config_path.read_bytes() + b" ")

        audited = online_sources.audit_online_source_operation(root)

        self.assertEqual(audited["outcome"], "pushed")
        self.assertTrue(audited["recovery_pending"])
        self.assertEqual(audited["allowed_actions"], [])
        self.assertTrue(online_sources.operation_manifest_path(root).exists())

    def test_commit_parent_race_cannot_be_reclaimed_or_pushed(self):
        root, source, config = self.create_transaction_repo()
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        remote_before = self.git(root, "rev-parse", "refs/remotes/origin/master").stdout.strip()
        original_git_checked = online_sources.git_checked
        injected = False

        def inject_user_commit_before_final_cas(root_dir: Path, args: list[str], timeout: int = 60):
            nonlocal injected
            if (
                not injected
                and len(args) > 1
                and args[0] == "update-ref"
                and args[1] == "refs/heads/master"
            ):
                injected = True
                user_path = Path(root_dir) / "user-note.txt"
                user_path.write_text("external user commit\n", encoding="utf-8")
                self.git(root_dir, "add", "user-note.txt")
                self.git(
                    root_dir,
                    "commit",
                    "--only",
                    "-m",
                    "external user commit",
                    "--",
                    "user-note.txt",
                )
            return original_git_checked(root_dir, args, timeout=timeout)

        with patch.object(
            online_sources,
            "git_checked",
            side_effect=inject_user_commit_before_final_cas,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="8" * 64,
                summary={"added": []},
            )

        audit = online_sources.audit_online_source_operation(root)
        self.assertEqual(result["outcome"], "saved_not_committed")
        self.assertEqual(audit["allowed_actions"], [])
        with self.assertRaises(online_sources.OnlineSourcesError):
            online_sources.recover_online_source_operation(
                root,
                action="retry_push",
                operation_id=audit["operation_id"],
                manifest_digest=audit["manifest_digest"],
            )
        remote_after = self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0]
        self.assertEqual(remote_after, remote_before)
        self.assertNotEqual(
            online_sources.git_run(root, ["show", f"{remote_after}:user-note.txt"]).returncode,
            0,
        )

    def test_rebased_looking_operation_cannot_hide_user_parent_commit(self):
        root, _manifest = self.create_manifest_then_commit_without_manifest_update()
        online_sources.audit_online_source_operation(root)
        manifest = online_sources.read_operation_manifest(root)
        original_operation_oid = manifest["operation_commit_oid"]
        origin = Path(self.git(root, "remote", "get-url", "origin").stdout.strip())
        remote_before = self.git(
            root,
            "ls-remote",
            str(origin),
            "refs/heads/master",
        ).stdout.split()[0]

        builder = root.parent / "forged-operation-builder"
        self.git(root.parent, "clone", str(origin), str(builder))
        self.git(builder, "config", "user.name", "Test")
        self.git(builder, "config", "user.email", "test@example.com")
        self.git(builder, "config", "core.autocrlf", "false")
        user_content = "user commit hidden in parent\n"
        (builder / "user-note.txt").write_text(user_content, encoding="utf-8")
        self.git(builder, "add", "user-note.txt")
        self.git(builder, "commit", "-m", "unrelated user parent")
        for relative_path in online_sources._allowed_online_paths():
            (builder / relative_path).write_bytes((root / relative_path).read_bytes())
        self.git(builder, "add", *online_sources._allowed_online_paths())
        self.git(
            builder,
            "commit",
            "-m",
            "配置：同步线上信源",
            "-m",
            manifest["commit_trailer"],
            "--",
            *online_sources._allowed_online_paths(),
        )
        forged_oid = self.git(builder, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(
            online_sources._stable_patch_id(builder, forged_oid),
            manifest["stable_patch_id"],
        )

        (root / "user-note.txt").write_text(user_content, encoding="utf-8")
        self.git(root, "add", "user-note.txt")
        self.git(root, "fetch", str(builder), "refs/heads/master")
        fetched_forged_oid = self.git(root, "rev-parse", "FETCH_HEAD").stdout.strip()
        self.assertEqual(fetched_forged_oid, forged_oid)
        self.git(
            root,
            "update-ref",
            "refs/heads/master",
            forged_oid,
            original_operation_oid,
        )
        self.assertEqual(self.git(root, "diff", "--cached", "--name-only").stdout, "")

        recovery = online_sources.audit_online_source_operation(root)

        self.assertEqual(recovery["outcome"], "committed_not_pushed")
        self.assertEqual(recovery["allowed_actions"], [])
        with self.assertRaises(online_sources.OnlineSourcesError):
            online_sources.recover_online_source_operation(
                root,
                action="retry_push",
                operation_id=recovery["operation_id"],
                manifest_digest=recovery["manifest_digest"],
            )
        self.assertEqual(
            self.git(
                root,
                "ls-remote",
                str(origin),
                "refs/heads/master",
            ).stdout.split()[0],
            remote_before,
        )

    def test_remote_replacement_after_commit_never_receives_operation(self):
        for injected_phase in ("committed", "push_unknown"):
            with self.subTest(injected_phase=injected_phase):
                root, source, config = self.create_transaction_repo()
                original = Path(self.git(root, "remote", "get-url", "origin").stdout.strip())
                replacement = root.parent / f"replacement-{injected_phase}.git"
                self.git(root.parent, "clone", "--bare", str(original), str(replacement))
                remote_before = self.git(
                    root,
                    "ls-remote",
                    str(original),
                    "refs/heads/master",
                ).stdout.split()[0]
                candidate = online_sources.build_online_config(
                    [{**source, "name": "Managed Feed"}],
                    updated_at=config["updated_at"],
                )
                original_write_manifest = online_sources.write_operation_manifest
                replaced = False

                def write_manifest_then_replace_remote(root_dir: Path, manifest: dict):
                    nonlocal replaced
                    digest = original_write_manifest(root_dir, manifest)
                    if (
                        not replaced
                        and manifest["phase"] == injected_phase
                        and manifest["operation_commit_oid"]
                    ):
                        replaced = True
                        self.git(root_dir, "remote", "set-url", "origin", str(replacement))
                    return digest

                with patch.object(
                    online_sources,
                    "write_operation_manifest",
                    side_effect=write_manifest_then_replace_remote,
                ):
                    result = online_sources.apply_online_source_config_operation(
                        root,
                        candidate,
                        operation_kind="apply",
                        base_config_digest=online_sources.online_config_digest(config),
                        preview_hash="a" * 64,
                        summary={"added": []},
                    )

                self.assertTrue(replaced)
                self.assertEqual(result["outcome"], "committed_not_pushed")
                self.assertEqual(result["recovery"]["allowed_actions"], [])
                self.assertTrue(online_sources.operation_manifest_path(root).exists())
                self.assertEqual(
                    self.git(
                        root,
                        "ls-remote",
                        str(original),
                        "refs/heads/master",
                    ).stdout.split()[0],
                    remote_before,
                )
                self.assertEqual(
                    self.git(
                        root,
                        "ls-remote",
                        str(replacement),
                        "refs/heads/master",
                    ).stdout.split()[0],
                    remote_before,
                )

    def test_remote_replacement_before_rebase_never_rewrites_or_pushes(self):
        root, source, config = self.create_transaction_repo()
        original = Path(self.git(root, "remote", "get-url", "origin").stdout.strip())
        replacement = root.parent / "replacement-before-rebase.git"
        peer = root.parent / "replacement-rebase-peer"
        self.git(root.parent, "clone", "--bare", str(original), str(replacement))
        self.git(root.parent, "clone", str(original), str(peer))
        self.git(peer, "config", "user.name", "Test")
        self.git(peer, "config", "user.email", "test@example.com")
        self.git(peer, "config", "core.autocrlf", "false")
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        replacement_before = self.git(
            root,
            "ls-remote",
            str(replacement),
            "refs/heads/master",
        ).stdout.split()[0]
        original_write_manifest = online_sources.write_operation_manifest
        remote_advanced = False
        remote_replaced = False
        operation_oid = ""

        def advance_then_replace(root_dir: Path, manifest: dict):
            nonlocal remote_advanced, remote_replaced, operation_oid
            digest = original_write_manifest(root_dir, manifest)
            if (
                not remote_advanced
                and manifest["phase"] == "committed"
                and manifest["operation_commit_oid"]
            ):
                remote_advanced = True
                remote_data = peer / "data" / "latest-24h.json"
                remote_data.write_text('{"version":"remote"}\n', encoding="utf-8")
                self.git(peer, "add", "data/latest-24h.json")
                self.git(peer, "commit", "-m", "remote data snapshot")
                self.git(peer, "push", "origin", "master")
            elif not remote_replaced and manifest["phase"] == "rebasing":
                remote_replaced = True
                operation_oid = manifest["operation_commit_oid"]
                self.git(root_dir, "remote", "set-url", "origin", str(replacement))
            return digest

        with patch.object(
            online_sources,
            "write_operation_manifest",
            side_effect=advance_then_replace,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="e" * 64,
                summary={"added": []},
            )

        self.assertTrue(remote_advanced)
        self.assertTrue(remote_replaced)
        self.assertEqual(result["outcome"], "committed_not_pushed")
        self.assertEqual(result["recovery"]["allowed_actions"], [])
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), operation_oid)
        original_head = self.git(
            root,
            "ls-remote",
            str(original),
            "refs/heads/master",
        ).stdout.split()[0]
        replacement_head = self.git(
            root,
            "ls-remote",
            str(replacement),
            "refs/heads/master",
        ).stdout.split()[0]
        self.assertEqual(replacement_head, replacement_before)
        for remote_head in (original_head, replacement_head):
            self.assertNotEqual(
                online_sources.git_run(
                    root,
                    ["merge-base", "--is-ancestor", operation_oid, remote_head],
                ).returncode,
                0,
            )

    def test_audit_leaves_unrelated_rebase_exactly_untouched(self):
        root, _manifest = self.create_manifest_then_commit_without_manifest_update()
        online_sources.audit_online_source_operation(root)

        origin = Path(self.git(root, "remote", "get-url", "origin").stdout.strip())
        peer = root.parent / "unrelated-rebase-peer"
        self.git(root.parent, "clone", str(origin), str(peer))
        self.git(peer, "config", "user.name", "Test")
        self.git(peer, "config", "user.email", "test@example.com")
        self.git(peer, "config", "core.autocrlf", "false")
        (peer / "conflict.txt").write_text("remote version\n", encoding="utf-8")
        self.git(peer, "add", "conflict.txt")
        self.git(peer, "commit", "-m", "remote conflict")
        self.git(peer, "push", "origin", "master")

        (root / "conflict.txt").write_text("local version\n", encoding="utf-8")
        self.git(root, "add", "conflict.txt")
        self.git(root, "commit", "-m", "unrelated user commit")
        self.git(root, "fetch", "origin", "refs/heads/master")
        rebased = online_sources.git_run(root, ["rebase", "FETCH_HEAD"], timeout=60)
        self.assertNotEqual(rebased.returncode, 0)

        rebase_dir = next(
            path
            for path in (
                online_sources._git_path(root, "rebase-merge"),
                online_sources._git_path(root, "rebase-apply"),
            )
            if path.exists()
        )

        def rebase_snapshot() -> list[tuple[str, bytes]]:
            return [
                (path.relative_to(rebase_dir).as_posix(), path.read_bytes())
                for path in sorted(rebase_dir.rglob("*"))
                if path.is_file()
            ]

        head_before = self.git(root, "rev-parse", "HEAD").stdout.strip()
        status_before = self.git(root, "status", "--porcelain=v2").stdout
        index_before = self.git(root, "ls-files", "--stage").stdout
        worktree_before = (root / "conflict.txt").read_bytes()
        rebase_before = rebase_snapshot()
        manifest_before = online_sources.operation_manifest_path(root).read_bytes()

        recovery = online_sources.audit_online_source_operation(root)

        self.assertEqual(recovery["phase"], "rebasing")
        self.assertEqual(recovery["allowed_actions"], [])
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), head_before)
        self.assertEqual(self.git(root, "status", "--porcelain=v2").stdout, status_before)
        self.assertEqual(self.git(root, "ls-files", "--stage").stdout, index_before)
        self.assertEqual((root / "conflict.txt").read_bytes(), worktree_before)
        self.assertEqual(rebase_snapshot(), rebase_before)
        self.assertEqual(
            online_sources.operation_manifest_path(root).read_bytes(),
            manifest_before,
        )

    def test_audit_aborts_only_proven_owned_rebase(self):
        root, operation_oid = self.create_proven_owned_paused_rebase()

        recovery = online_sources.audit_online_source_operation(root)
        audited = online_sources.read_operation_manifest(root)

        self.assertFalse(online_sources._git_path(root, "rebase-merge").exists())
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), operation_oid)
        self.assertEqual(recovery["phase"], "committed")
        self.assertEqual(recovery["allowed_actions"], ["retry_push"])
        self.assertEqual(audited["phase"], "committed")

    def test_audit_aborts_proven_owned_rebase_with_dirty_conflict_state(self):
        root, operation_oid = self.create_proven_owned_paused_rebase()
        data_path = root / "data" / "latest-24h.json"
        data_path.write_text('{"version":"conflicted-rebase-state"}\n', encoding="utf-8")

        recovery = online_sources.audit_online_source_operation(root)

        self.assertFalse(online_sources._git_path(root, "rebase-merge").exists())
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), operation_oid)
        self.assertEqual(recovery["phase"], "committed")
        self.assertEqual(recovery["allowed_actions"], ["retry_push"])

    def test_audit_abort_failure_preserves_owned_rebase(self):
        root, _operation_oid = self.create_proven_owned_paused_rebase()
        rebase_dir = online_sources._git_path(root, "rebase-merge")

        def snapshot() -> list[tuple[str, bytes]]:
            return [
                (path.relative_to(rebase_dir).as_posix(), path.read_bytes())
                for path in sorted(rebase_dir.rglob("*"))
                if path.is_file()
            ]

        head_before = self.git(root, "rev-parse", "HEAD").stdout.strip()
        status_before = self.git(root, "status", "--porcelain=v2").stdout
        rebase_before = snapshot()
        manifest_before = online_sources.operation_manifest_path(root).read_bytes()
        original_git_run = online_sources.git_run

        def fail_abort(root_dir: Path, args: list[str], timeout: int = 60):
            if args == ["rebase", "--abort"]:
                return subprocess.CompletedProcess(
                    ["git", *args],
                    1,
                    stdout="",
                    stderr="injected abort failure",
                )
            return original_git_run(root_dir, args, timeout=timeout)

        with patch.object(online_sources, "git_run", side_effect=fail_abort):
            recovery = online_sources.audit_online_source_operation(root)

        self.assertEqual(recovery["phase"], "rebasing")
        self.assertEqual(recovery["allowed_actions"], [])
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), head_before)
        self.assertEqual(self.git(root, "status", "--porcelain=v2").stdout, status_before)
        self.assertEqual(snapshot(), rebase_before)
        self.assertEqual(
            online_sources.operation_manifest_path(root).read_bytes(),
            manifest_before,
        )

    def test_restore_worktree_never_overwrites_newer_user_edit(self):
        root, _manifest = self.create_manifest_then_commit_without_manifest_update()
        online_sources.audit_online_source_operation(root)
        manifest = online_sources.read_operation_manifest(root)
        operation_oid = manifest["operation_commit_oid"]
        data_path = root / "data" / "latest-24h.json"
        data_path.write_text('{"version":"owned-stash"}\n', encoding="utf-8")
        manifest["stash"]["paths"] = [
            {
                "path": "data/latest-24h.json",
                "before_exists": True,
                "before_sha256": online_sources.sha256_file(data_path),
            }
        ]
        online_sources.write_operation_manifest(root, manifest)
        self.git(
            root,
            "stash",
            "push",
            "-m",
            manifest["stash"]["message"],
            "--",
            "data/latest-24h.json",
        )
        self.git(root, "push", "origin", f"{operation_oid}:refs/heads/master")
        recovery = online_sources.audit_online_source_operation(root)

        newer_bytes = b'{"version":"newer-user-edit"}\n'
        data_path.write_bytes(newer_bytes)
        stash_before = self.git(root, "stash", "list", "--format=%H%x09%gs").stdout
        manifest_before = online_sources.operation_manifest_path(root).read_bytes()

        with self.assertRaises(online_sources.OnlineSourcesError) as raised:
            online_sources.recover_online_source_operation(
                root,
                action="restore_worktree",
                operation_id=recovery["operation_id"],
                manifest_digest=recovery["manifest_digest"],
            )

        self.assertEqual(raised.exception.code, "online_sources_recovery_mismatch")
        self.assertEqual(data_path.read_bytes(), newer_bytes)
        self.assertEqual(
            self.git(root, "stash", "list", "--format=%H%x09%gs").stdout,
            stash_before,
        )
        self.assertEqual(
            online_sources.operation_manifest_path(root).read_bytes(),
            manifest_before,
        )

    def test_owned_stash_treats_dirty_paths_as_literal_names(self):
        root, source, config = self.create_transaction_repo()
        literal_path = root / "data" / "[snapshot].json"
        glob_match_path = root / "data" / "s.json"
        literal_path.write_text('{"version":"initial-literal"}\n', encoding="utf-8")
        glob_match_path.write_text('{"version":"initial-glob-match"}\n', encoding="utf-8")
        self.git(
            root,
            "--literal-pathspecs",
            "add",
            "--",
            "data/[snapshot].json",
            "data/s.json",
        )
        self.git(root, "commit", "-m", "add pathspec-shaped data files")
        self.git(root, "push", "origin", "master")
        literal_path.write_text('{"version":"local-literal"}\n', encoding="utf-8")
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )

        result = online_sources.apply_online_source_config_operation(
            root,
            candidate,
            operation_kind="apply",
            base_config_digest=online_sources.online_config_digest(config),
            preview_hash="1" * 64,
            summary={"added": []},
        )

        self.assertEqual(result["outcome"], "pushed")
        self.assertEqual(literal_path.read_text(encoding="utf-8"), '{"version":"local-literal"}\n')
        self.assertEqual(
            glob_match_path.read_text(encoding="utf-8"),
            '{"version":"initial-glob-match"}\n',
        )
        self.assertEqual(
            self.git(root, "diff", "--name-only").stdout.splitlines(),
            ["data/[snapshot].json"],
        )
        self.assertEqual(self.git(root, "stash", "list").stdout.strip(), "")

    def test_external_commit_during_fetch_is_not_rebased_or_pushed(self):
        root, source, config = self.create_transaction_repo()
        origin = Path(self.git(root, "remote", "get-url", "origin").stdout.strip())
        peer = root.parent / "fetch-race-peer"
        self.git(root.parent, "clone", str(origin), str(peer))
        self.git(peer, "config", "user.name", "Test")
        self.git(peer, "config", "user.email", "test@example.com")
        self.git(peer, "config", "core.autocrlf", "false")
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        original_write_manifest = online_sources.write_operation_manifest
        original_git_checked = online_sources.git_checked
        remote_advanced = False
        user_commit_oid = ""

        def write_manifest_then_advance_remote(root_dir: Path, manifest: dict):
            nonlocal remote_advanced
            digest = original_write_manifest(root_dir, manifest)
            if (
                not remote_advanced
                and manifest["phase"] == "committed"
                and manifest["operation_commit_oid"]
            ):
                remote_advanced = True
                remote_data = peer / "data" / "latest-24h.json"
                remote_data.write_text('{"version":"remote"}\n', encoding="utf-8")
                self.git(peer, "add", "data/latest-24h.json")
                self.git(peer, "commit", "-m", "remote data snapshot")
                self.git(peer, "push", "origin", "master")
            return digest

        def inject_user_commit_after_fetch(root_dir: Path, args: list[str], timeout: int = 60):
            nonlocal user_commit_oid
            completed = original_git_checked(root_dir, args, timeout=timeout)
            if (
                not user_commit_oid
                and remote_advanced
                and args
                and args[0] == "fetch"
            ):
                user_path = Path(root_dir) / "user-note.txt"
                user_path.write_text("external user commit\n", encoding="utf-8")
                self.git(root_dir, "add", "user-note.txt")
                self.git(
                    root_dir,
                    "commit",
                    "--only",
                    "-m",
                    "external commit during fetch",
                    "--",
                    "user-note.txt",
                )
                user_commit_oid = self.git(root_dir, "rev-parse", "HEAD").stdout.strip()
            return completed

        with patch.object(
            online_sources,
            "write_operation_manifest",
            side_effect=write_manifest_then_advance_remote,
        ), patch.object(
            online_sources,
            "git_checked",
            side_effect=inject_user_commit_after_fetch,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="b" * 64,
                summary={"added": []},
            )

        self.assertTrue(remote_advanced)
        self.assertTrue(user_commit_oid)
        self.assertEqual(result["outcome"], "committed_not_pushed")
        self.assertEqual(self.git(root, "rev-parse", "HEAD").stdout.strip(), user_commit_oid)
        self.assertEqual(
            self.git(root, "show", "-s", "--format=%s", "HEAD").stdout.strip(),
            "external commit during fetch",
        )
        manifest = online_sources.read_operation_manifest(root)
        remote_oid = self.git(
            root,
            "ls-remote",
            str(origin),
            "refs/heads/master",
        ).stdout.split()[0]
        self.assertNotEqual(
            online_sources.git_run(
                root,
                ["merge-base", "--is-ancestor", manifest["operation_commit_oid"], remote_oid],
            ).returncode,
            0,
        )

    def test_stash_race_preserves_staged_and_unstaged_versions(self):
        root, source, config = self.create_transaction_repo()
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        data_path = root / "data" / "latest-24h.json"
        staged_bytes = b'{"version":"staged-user-edit"}\n'
        unstaged_bytes = b'{"version":"unstaged-user-edit"}\n'
        remote_before = self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0]
        stash_before = self.git(root, "stash", "list", "--format=%H%x09%gs").stdout
        original_update_manifest = online_sources.update_operation_manifest
        injected = False

        def stage_then_edit_before_stash(root_dir: Path, manifest: dict, **changes):
            nonlocal injected
            updated, digest = original_update_manifest(root_dir, manifest, **changes)
            if (
                not injected
                and updated["phase"] == "committed"
                and updated["operation_commit_oid"]
            ):
                injected = True
                data_path.write_bytes(staged_bytes)
                self.git(root_dir, "add", "data/latest-24h.json")
                data_path.write_bytes(unstaged_bytes)
            return updated, digest

        with patch.object(
            online_sources,
            "update_operation_manifest",
            side_effect=stage_then_edit_before_stash,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="4" * 64,
                summary={"added": []},
            )

        self.assertTrue(injected)
        self.assertEqual(result["outcome"], "committed_not_pushed")
        self.assertEqual(result["recovery"]["allowed_actions"], [])
        self.assertEqual(data_path.read_bytes(), unstaged_bytes)
        self.assertEqual(
            self.git(root, "show", ":data/latest-24h.json").stdout.encode("utf-8"),
            staged_bytes,
        )
        self.assertEqual(
            self.git(root, "stash", "list", "--format=%H%x09%gs").stdout,
            stash_before,
        )
        self.assertEqual(
            self.git(root, "ls-remote", "origin", "refs/heads/master").stdout.split()[0],
            remote_before,
        )

    def test_remote_non_data_advance_is_never_rebased_or_pushed(self):
        root, source, config = self.create_transaction_repo()
        origin = Path(self.git(root, "remote", "get-url", "origin").stdout.strip())
        peer = root.parent / "non-data-peer"
        self.git(root.parent, "clone", str(origin), str(peer))
        self.git(peer, "config", "user.name", "Test")
        self.git(peer, "config", "user.email", "test@example.com")
        self.git(peer, "config", "core.autocrlf", "false")
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        original_write_manifest = online_sources.write_operation_manifest
        remote_advanced = False

        def write_manifest_then_advance_remote(root_dir: Path, manifest: dict):
            nonlocal remote_advanced
            digest = original_write_manifest(root_dir, manifest)
            if (
                not remote_advanced
                and manifest["phase"] == "committed"
                and manifest["operation_commit_oid"]
            ):
                remote_advanced = True
                (peer / "README-race.md").write_text("remote code change\n", encoding="utf-8")
                self.git(peer, "add", "README-race.md")
                self.git(peer, "commit", "-m", "remote non-data change")
                self.git(peer, "push", "origin", "master")
            return digest

        with patch.object(
            online_sources,
            "write_operation_manifest",
            side_effect=write_manifest_then_advance_remote,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="c" * 64,
                summary={"added": []},
            )

        self.assertTrue(remote_advanced)
        self.assertEqual(result["outcome"], "committed_not_pushed")
        manifest = online_sources.read_operation_manifest(root)
        remote_oid = self.git(
            root,
            "ls-remote",
            str(origin),
            "refs/heads/master",
        ).stdout.split()[0]
        self.assertNotEqual(
            online_sources.git_run(
                root,
                ["merge-base", "--is-ancestor", manifest["operation_commit_oid"], remote_oid],
            ).returncode,
            0,
        )

    def test_remote_non_data_history_cannot_hide_behind_revert(self):
        root, source, config = self.create_transaction_repo()
        origin = Path(self.git(root, "remote", "get-url", "origin").stdout.strip())
        peer = root.parent / "hidden-non-data-peer"
        self.git(root.parent, "clone", str(origin), str(peer))
        self.git(peer, "config", "user.name", "Test")
        self.git(peer, "config", "user.email", "test@example.com")
        self.git(peer, "config", "core.autocrlf", "false")
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        original_write_manifest = online_sources.write_operation_manifest
        remote_advanced = False

        def write_manifest_then_push_hidden_history(root_dir: Path, manifest: dict):
            nonlocal remote_advanced
            digest = original_write_manifest(root_dir, manifest)
            if (
                not remote_advanced
                and manifest["phase"] == "committed"
                and manifest["operation_commit_oid"]
            ):
                remote_advanced = True
                readme = peer / "README-hidden.md"
                readme.write_text("temporary remote code change\n", encoding="utf-8")
                self.git(peer, "add", "README-hidden.md")
                self.git(peer, "commit", "-m", "temporary non-data change")
                self.git(peer, "revert", "--no-edit", "HEAD")
                remote_data = peer / "data" / "latest-24h.json"
                remote_data.write_text('{"version":"remote"}\n', encoding="utf-8")
                self.git(peer, "add", "data/latest-24h.json")
                self.git(peer, "commit", "-m", "remote data snapshot")
                self.git(peer, "push", "origin", "master")
            return digest

        with patch.object(
            online_sources,
            "write_operation_manifest",
            side_effect=write_manifest_then_push_hidden_history,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="f" * 64,
                summary={"added": []},
            )

        self.assertTrue(remote_advanced)
        self.assertEqual(result["outcome"], "committed_not_pushed")
        self.assertEqual(result["recovery"]["allowed_actions"], [])
        manifest = online_sources.read_operation_manifest(root)
        remote_oid = self.git(
            root,
            "ls-remote",
            str(origin),
            "refs/heads/master",
        ).stdout.split()[0]
        self.assertNotEqual(
            online_sources.git_run(
                root,
                ["merge-base", "--is-ancestor", manifest["operation_commit_oid"], remote_oid],
            ).returncode,
            0,
        )

    def test_pushed_operation_keeps_manifest_when_config_changes_before_finalize(self):
        root, source, config = self.create_transaction_repo()
        candidate = online_sources.build_online_config(
            [{**source, "name": "Managed Feed"}],
            updated_at=config["updated_at"],
        )
        original_remote_contains = online_sources._remote_contains_commit
        injected = False
        external_config = online_sources.build_online_config(
            [{**source, "name": "External Concurrent Feed"}],
            updated_at="2026-07-16T03:00:00Z",
        )

        def confirm_push_then_dirty_config(root_dir: Path, manifest: dict, commit_oid: str):
            nonlocal injected
            pushed = original_remote_contains(root_dir, manifest, commit_oid)
            if pushed and not injected:
                injected = True
                config_path = online_sources.online_config_path(root_dir)
                config_path.write_bytes(online_sources.render_json_bytes(external_config))
            return pushed

        with patch.object(
            online_sources,
            "_remote_contains_commit",
            side_effect=confirm_push_then_dirty_config,
        ):
            result = online_sources.apply_online_source_config_operation(
                root,
                candidate,
                operation_kind="apply",
                base_config_digest=online_sources.online_config_digest(config),
                preview_hash="d" * 64,
                summary={"added": []},
            )

        self.assertTrue(injected)
        self.assertEqual(result["outcome"], "pushed")
        self.assertTrue(result["partial"])
        self.assertTrue(result["recovery_pending"])
        self.assertEqual(result["recovery"]["allowed_actions"], [])
        self.assertEqual(
            result["base_config_digest"],
            online_sources.online_config_digest(external_config),
        )
        self.assertEqual(result["etag"], online_sources.online_config_etag(external_config))
        self.assertTrue(online_sources.operation_manifest_path(root).exists())


class OnlineSourceSchemaWriteProtectionTests(unittest.TestCase):
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
