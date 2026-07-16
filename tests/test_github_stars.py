from __future__ import annotations

import copy
import json
import re
import threading
import unittest
from unittest.mock import patch

import requests

from scripts.radar.server import github_stars, online_sources


ACCOUNT = {"id": 12345678, "login": "example-user"}


def public_repo(repo_id: int, full_name: str | None = None) -> dict:
    name = full_name or f"owner/repo-{repo_id}"
    return {
        "id": repo_id,
        "full_name": name,
        "private": False,
        "visibility": "public",
        "html_url": f"https://github.com/{name}",
    }


def private_repo(repo_id: int, full_name: str, *, visibility: str = "private") -> dict:
    return {
        "id": repo_id,
        "full_name": full_name,
        "private": True,
        "visibility": visibility,
        "html_url": f"https://github.com/{full_name}",
    }


def managed_source(
    repo_id: int,
    repo: str,
    *,
    source_id: str | None = None,
    name: str | None = None,
    notes: str = "只追踪 release",
    state: str = "active",
    account_id: int = ACCOUNT["id"],
) -> dict:
    enabled = state == "active"
    return {
        "id": source_id or f"online_github_repo_{repo_id}",
        "name": name or repo,
        "type": "github_release",
        "enabled": enabled,
        "channel": "GitHub Release",
        "target": repo,
        "locator": repo,
        "env": "",
        "notes": notes,
        "managed_by": "github_stars",
        "managed_account_id": account_id,
        "managed_repo_id": repo_id,
        "managed_state": state,
    }


def manual_source(
    source_id: str,
    repo: str,
    *,
    enabled: bool = True,
    name: str | None = None,
    notes: str = "manual note",
) -> dict:
    return {
        "id": source_id,
        "name": name or repo,
        "type": "github_release",
        "enabled": enabled,
        "channel": "GitHub Release",
        "target": repo,
        "locator": repo,
        "env": "",
        "notes": notes,
    }


def rss_source(index: int, *, enabled: bool = True) -> dict:
    return {
        "id": f"rss_{index}",
        "name": f"Feed {index}",
        "type": "rss",
        "enabled": enabled,
        "channel": "RSS/YouTube",
        "target": f"Feed {index}",
        "locator": f"https://example.com/{index}.xml",
        "env": "",
        "notes": "公开 feed",
    }


def config_with(sources: list[dict], *, bound: bool = True) -> dict:
    config = {
        "version": "1.0",
        "mode": "online-public-source-config",
        "updated_at": "2026-07-15T00:00:00Z",
        "sources": copy.deepcopy(sources),
    }
    if bound:
        config["github_star_sync"] = {
            "version": 1,
            "account_id": ACCOUNT["id"],
            "account_login": ACCOUNT["login"],
        }
    return config


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload,
        *,
        headers: dict[str, str] | None = None,
        on_chunk=None,
        on_eof=None,
        raw_body: bytes | None = None,
    ):
        self.status_code = status_code
        self._payload = payload
        self.headers = dict(headers or {})
        self.on_chunk = on_chunk
        self.on_eof = on_eof
        self.raw_body = raw_body
        self.closed = False
        self.json_calls = 0

    def json(self):
        self.json_calls += 1
        if isinstance(self._payload, Exception):
            raise self._payload
        return copy.deepcopy(self._payload)

    def iter_content(self, chunk_size: int = 65536):
        if isinstance(self._payload, Exception):
            raise self._payload
        body = self.raw_body
        if body is None:
            body = json.dumps(self._payload, ensure_ascii=False).encode("utf-8")
        for offset in range(0, len(body), max(1, chunk_size)):
            if self.on_chunk is not None:
                self.on_chunk()
            yield body[offset : offset + chunk_size]
        if self.on_eof is not None:
            self.on_eof()

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError(f"unexpected request: {url}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class GitHubStarsTestCase(unittest.TestCase):
    def assert_error_code(self, code: str, callback) -> github_stars.GitHubStarsError:
        with self.assertRaises(github_stars.GitHubStarsError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)
        return caught.exception


class GitHubUsernameAndAccountTests(GitHubStarsTestCase):
    def test_username_validation_matches_github_login_rules(self):
        for value in ["a", "A1", "example-user", "a" * 39]:
            with self.subTest(valid=value):
                self.assertEqual(github_stars.validate_github_username(value), value)

        for value in ["", "-bad", "bad-", "bad--name", "bad_name", "a/b", "a" * 40]:
            with self.subTest(invalid=value):
                self.assert_error_code(
                    "github_username_invalid",
                    lambda value=value: github_stars.validate_github_username(value),
                )

    def test_invalid_username_fails_before_network(self):
        session = FakeSession([])

        self.assert_error_code(
            "github_username_invalid",
            lambda: github_stars.fetch_github_star_snapshot(session, username="bad/name"),
        )

        self.assertEqual(session.calls, [])

    def test_username_lookup_returns_only_canonical_identity(self):
        session = FakeSession([FakeResponse(200, {"id": 123, "login": "Canonical", "email": "private@example.com"})])

        account = github_stars.fetch_github_account(session, username="requested-name")

        self.assertEqual(account, {"id": 123, "login": "Canonical"})
        self.assertEqual(session.calls[0]["url"], "https://api.github.com/users/requested-name")

    def test_account_id_lookup_allows_login_rename_but_requires_same_id(self):
        session = FakeSession([FakeResponse(200, {"id": 123, "login": "renamed-user"})])

        account = github_stars.fetch_github_account(session, account_id=123)

        self.assertEqual(account, {"id": 123, "login": "renamed-user"})
        self.assertEqual(session.calls[0]["url"], "https://api.github.com/user/123")

        mismatch = FakeSession([FakeResponse(200, {"id": 999, "login": "renamed-user"})])
        self.assert_error_code(
            "github_star_account_mismatch",
            lambda: github_stars.fetch_github_account(mismatch, account_id=123),
        )

    def test_account_errors_are_structured_and_safe(self):
        not_found = FakeSession([FakeResponse(404, {"message": "Not Found"})])
        self.assert_error_code(
            "github_user_not_found",
            lambda: github_stars.fetch_github_account(not_found, username="missing-user"),
        )

        invalid_payloads = [[], {"login": "missing-id"}, {"id": True, "login": "bad"}, {"id": 1, "login": "bad--name"}]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                session = FakeSession([FakeResponse(200, payload)])
                self.assert_error_code(
                    "github_upstream_invalid_response",
                    lambda session=session: github_stars.fetch_github_account(session, username="example"),
                )


class GitHubStarPaginationTests(GitHubStarsTestCase):
    def test_zero_and_one_public_star_are_complete_snapshots(self):
        for repositories, expected in [([], []), ([public_repo(7, "owner/one")], [{"id": 7, "full_name": "owner/one"}])]:
            with self.subTest(repositories=repositories):
                session = FakeSession([
                    FakeResponse(200, ACCOUNT),
                    FakeResponse(200, repositories),
                ])

                snapshot = github_stars.fetch_github_star_snapshot(session, username=ACCOUNT["login"])

                self.assertEqual(snapshot["repositories"], expected)
                self.assertEqual(snapshot["starred_count"], len(expected))

    def test_link_next_is_followed_even_when_page_is_short(self):
        next_url = "https://api.github.com/users/example-user/starred?per_page=100&page=2"
        session = FakeSession([
            FakeResponse(200, ACCOUNT),
            FakeResponse(
                200,
                [public_repo(20, "owner/twenty")],
                headers={"Link": f'<{next_url}>; rel="next"'},
            ),
            FakeResponse(200, [public_repo(10, "owner/ten"), public_repo(20, "owner/twenty")]),
        ])

        snapshot = github_stars.fetch_github_star_snapshot(session, username=ACCOUNT["login"])

        self.assertEqual(
            snapshot["repositories"],
            [{"id": 10, "full_name": "owner/ten"}, {"id": 20, "full_name": "owner/twenty"}],
        )
        self.assertEqual(session.calls[1]["params"], {"per_page": 100})
        self.assertEqual(session.calls[2]["url"], next_url)
        self.assertNotIn("params", session.calls[2])

    def test_middle_page_failure_aborts_without_partial_snapshot(self):
        next_url = "https://api.github.com/users/example-user/starred?page=2&per_page=100"
        session = FakeSession([
            FakeResponse(200, ACCOUNT),
            FakeResponse(200, [public_repo(1)], headers={"Link": f'<{next_url}>; rel="next"'}),
            FakeResponse(500, {"message": "internal details must not leak"}),
        ])

        error = self.assert_error_code(
            "github_upstream_invalid_response",
            lambda: github_stars.fetch_github_star_snapshot(session, username=ACCOUNT["login"]),
        )

        self.assertNotIn("internal details", str(error))

    def test_malformed_or_conflicting_repo_aborts_snapshot(self):
        invalid_pages = [
            {"not": "a list"},
            [{"id": 1, "full_name": "owner/repo", "private": False}],
            [{"id": 1, "full_name": "not-a-repo", "private": False, "visibility": "public"}],
            [public_repo(1, "owner/one"), public_repo(1, "owner/two")],
        ]
        for page in invalid_pages:
            with self.subTest(page=page):
                session = FakeSession([FakeResponse(200, ACCOUNT), FakeResponse(200, page)])
                self.assert_error_code(
                    "github_upstream_invalid_response",
                    lambda session=session: github_stars.fetch_github_star_snapshot(session, username=ACCOUNT["login"]),
                )

    def test_upstream_error_classification_is_stable(self):
        cases = [
            (FakeResponse(429, {}), "github_upstream_rate_limited"),
            (FakeResponse(403, {}, headers={"X-RateLimit-Remaining": "0"}), "github_upstream_rate_limited"),
            (FakeResponse(403, {}), "github_upstream_forbidden"),
            (requests.Timeout("socket details"), "github_upstream_timeout"),
        ]
        for response, code in cases:
            with self.subTest(code=code):
                session = FakeSession([response])
                error = self.assert_error_code(
                    code,
                    lambda session=session: github_stars.fetch_github_account(session, username="example"),
                )
                self.assertNotIn("socket details", str(error))

    def test_link_must_be_same_host_and_exactly_next_page(self):
        invalid_links = [
            "https://api.github.com/users/example-user/starred?per_page=100&page=3",
            "https://evil.example/users/example-user/starred?per_page=100&page=2",
            "https://api.github.com/users/other-user/starred?per_page=100&page=2",
            "https://api.github.com/users/example-user/starred?page=2",
        ]
        for next_url in invalid_links:
            with self.subTest(next_url=next_url):
                first_page = FakeResponse(
                    200,
                    [public_repo(1)],
                    headers={"Link": f'<{next_url}>; rel="next"'},
                )
                session = FakeSession([FakeResponse(200, ACCOUNT), first_page])
                self.assert_error_code(
                    "github_upstream_invalid_response",
                    lambda session=session: github_stars.fetch_github_star_snapshot(
                        session,
                        username=ACCOUNT["login"],
                    ),
                )

    def test_requests_are_streamed_without_redirects_and_responses_are_closed(self):
        account_response = FakeResponse(200, ACCOUNT)
        stars_response = FakeResponse(200, [public_repo(1)])
        session = FakeSession([account_response, stars_response])

        github_stars.fetch_github_star_snapshot(session, username=ACCOUNT["login"])

        self.assertTrue(account_response.closed)
        self.assertTrue(stars_response.closed)
        self.assertEqual(account_response.json_calls, 0)
        self.assertEqual(stars_response.json_calls, 0)
        self.assertTrue(all(call["stream"] is True for call in session.calls))
        self.assertTrue(all(call["allow_redirects"] is False for call in session.calls))

    def test_session_has_no_automatic_retries(self):
        session = github_stars.create_github_stars_session()

        retries = session.get_adapter("https://").max_retries
        self.assertEqual(retries.total, 0)
        self.assertEqual(retries.connect, 0)
        self.assertEqual(retries.read, 0)

    def test_account_and_pages_share_one_monotonic_budget(self):
        clock = FakeClock()
        account_response = FakeResponse(200, ACCOUNT, on_chunk=lambda: clock.advance(20))
        stars_response = FakeResponse(200, [public_repo(1)], on_chunk=lambda: clock.advance(11))
        session = FakeSession([account_response, stars_response])

        error = self.assert_error_code(
            "github_upstream_timeout",
            lambda: github_stars.fetch_github_star_snapshot(
                session,
                username=ACCOUNT["login"],
                budget_seconds=30,
                monotonic=clock,
            ),
        )

        self.assertTrue(stars_response.closed)
        self.assertGreaterEqual(error.details["overrun_ms"], 1000)

    def test_oversized_response_is_rejected_and_closed(self):
        response = FakeResponse(
            200,
            ACCOUNT,
            headers={"Content-Length": str(github_stars.GITHUB_RESPONSE_MAX_BYTES + 1)},
        )
        session = FakeSession([response])

        self.assert_error_code(
            "github_upstream_invalid_response",
            lambda: github_stars.fetch_github_account(session, username="example"),
        )

        self.assertTrue(response.closed)

    def test_secondary_rate_limit_body_is_classified_without_leaking_message(self):
        response = FakeResponse(
            403,
            {"message": "You have exceeded a secondary rate limit. Secret diagnostic."},
        )
        session = FakeSession([response])

        error = self.assert_error_code(
            "github_upstream_rate_limited",
            lambda: github_stars.fetch_github_account(session, username="example"),
        )

        self.assertNotIn("Secret diagnostic", str(error))

    def test_fixed_http_status_wins_over_empty_or_non_json_error_body(self):
        cases = [
            (404, {}, b"", "github_user_not_found"),
            (429, {}, b"<html>rate limited</html>", "github_upstream_rate_limited"),
            (
                403,
                {"X-RateLimit-Remaining": "0"},
                b"not-json",
                "github_upstream_rate_limited",
            ),
            (403, {}, b"forbidden", "github_upstream_forbidden"),
        ]
        for status, headers, body, code in cases:
            with self.subTest(status=status, code=code):
                response = FakeResponse(status, {}, headers=headers, raw_body=body)
                session = FakeSession([response])
                self.assert_error_code(
                    code,
                    lambda session=session: github_stars.fetch_github_account(
                        session,
                        username="example",
                    ),
                )
                self.assertTrue(response.closed)

    def test_deadline_is_checked_after_waiting_for_eof(self):
        clock = FakeClock()
        response = FakeResponse(200, ACCOUNT, on_eof=lambda: clock.advance(31))
        session = FakeSession([response])

        self.assert_error_code(
            "github_upstream_timeout",
            lambda: github_stars.fetch_github_account(
                session,
                username="example",
                budget_seconds=30,
                monotonic=clock,
            ),
        )

        self.assertTrue(response.closed)


class GitHubStarPrivacyAndLimitTests(GitHubStarsTestCase):
    def test_private_repositories_are_counted_anonymously_and_do_not_use_public_capacity(self):
        public = [public_repo(index) for index in range(1, 51)]
        secret = private_repo(9001, "secret-owner/secret-repo")
        internal = {**private_repo(9002, "corp/internal-repo"), "private": False, "visibility": "internal"}
        session = FakeSession([
            FakeResponse(200, ACCOUNT),
            FakeResponse(200, [secret, *public, internal]),
        ])

        snapshot = github_stars.fetch_github_star_snapshot(session, username=ACCOUNT["login"])
        serialized = json.dumps(snapshot, ensure_ascii=False)

        self.assertEqual(snapshot["starred_count"], 50)
        self.assertEqual(snapshot["private_skipped_count"], 2)
        self.assertNotIn("secret-owner", serialized)
        self.assertNotIn("corp/internal", serialized)
        self.assertNotIn("9001", serialized)
        self.assertNotIn("9002", serialized)

    def test_fifty_first_public_repository_aborts_entire_snapshot(self):
        session = FakeSession([
            FakeResponse(200, ACCOUNT),
            FakeResponse(200, [public_repo(index) for index in range(1, 52)]),
        ])

        self.assert_error_code(
            "github_star_limit_exceeded",
            lambda: github_stars.fetch_github_star_snapshot(session, username=ACCOUNT["login"]),
        )

    def test_private_identity_never_affects_preview_hash(self):
        config = config_with([], bound=False)
        session_a = FakeSession([
            FakeResponse(200, ACCOUNT),
            FakeResponse(200, [public_repo(1, "owner/public"), private_repo(9001, "secret/one")]),
        ])
        session_b = FakeSession([
            FakeResponse(200, ACCOUNT),
            FakeResponse(200, [public_repo(1, "owner/public"), private_repo(9999, "private/renamed")]),
        ])
        snapshot_a = github_stars.fetch_github_star_snapshot(session_a, username=ACCOUNT["login"])
        snapshot_b = github_stars.fetch_github_star_snapshot(session_b, username=ACCOUNT["login"])

        preview_a = github_stars.build_github_star_preview(config, snapshot_a)
        preview_b = github_stars.build_github_star_preview(config, snapshot_b)

        self.assertEqual(preview_a["preview_hash"], preview_b["preview_hash"])
        self.assertNotIn("repositories", preview_a)


class GitHubStarMergeTruthTableTests(GitHubStarsTestCase):
    def test_complete_truth_table_is_pure_and_never_deletes_sources(self):
        sources = [
            managed_source(1, "owner/one", name="Keep one"),
            managed_source(2, "owner/two"),
            managed_source(3, "owner/three", state="auto_disabled"),
            managed_source(4, "old-owner/four", name="Keep four", notes="keep notes"),
            manual_source("manual_five", "owner/five", name="Manual five", notes="manual five notes"),
            manual_source(
                "manual_six",
                "owner/six",
                enabled=False,
                name="Keep six",
                notes="keep six",
            ),
            managed_source(
                8,
                "owner/eight",
                name="Keep eight",
                notes="keep eight",
                state="auto_disabled",
            ),
            rss_source(1),
        ]
        config = config_with(sources)
        original = copy.deepcopy(config)
        repositories = [
            {"id": 1, "full_name": "owner/one"},
            {"id": 3, "full_name": "owner/three"},
            {"id": 4, "full_name": "new-owner/four"},
            {"id": 5, "full_name": "owner/five"},
            {"id": 6, "full_name": "owner/six"},
            {"id": 7, "full_name": "owner/seven"},
        ]

        result = github_stars.merge_github_star_sources(config, account=ACCOUNT, repositories=repositories)
        candidate = result["config"]
        summary = result["summary"]
        by_id = {source["id"]: source for source in candidate["sources"]}

        self.assertEqual(config, original)
        self.assertEqual(len(candidate["sources"]), len(sources) + 1)
        self.assertEqual([item["repo_id"] for item in summary["added"]], [7])
        self.assertEqual([item["repo_id"] for item in summary["disabled"]], [2])
        self.assertEqual([item["repo_id"] for item in summary["re_enabled"]], [3])
        self.assertEqual([item["repo_id"] for item in summary["adopted"]], [5])
        self.assertEqual([item["repo_id"] for item in summary["renamed"]], [4])
        self.assertEqual([item["repo_id"] for item in summary["skipped_manual_disabled"]], [6])

        self.assertFalse(by_id["online_github_repo_2"]["enabled"])
        self.assertEqual(by_id["online_github_repo_2"]["managed_state"], "auto_disabled")
        self.assertTrue(by_id["online_github_repo_3"]["enabled"])
        self.assertEqual(by_id["online_github_repo_3"]["managed_state"], "active")
        self.assertEqual(by_id["online_github_repo_4"]["locator"], "new-owner/four")
        self.assertEqual(by_id["online_github_repo_4"]["name"], "Keep four")
        self.assertEqual(by_id["online_github_repo_4"]["notes"], "keep notes")
        self.assertEqual(by_id["manual_five"]["name"], "Manual five")
        self.assertEqual(by_id["manual_five"]["notes"], "manual five notes")
        self.assertEqual(by_id["manual_five"]["managed_repo_id"], 5)
        self.assertEqual(
            by_id["manual_six"],
            manual_source(
                "manual_six",
                "owner/six",
                enabled=False,
                name="Keep six",
                notes="keep six",
            ),
        )
        self.assertEqual(
            by_id["online_github_repo_8"],
            managed_source(
                8,
                "owner/eight",
                name="Keep eight",
                notes="keep eight",
                state="auto_disabled",
            ),
        )
        self.assertEqual(by_id["rss_1"], rss_source(1))
        self.assertTrue(result["requires_confirmation"])

    def test_account_mismatch_and_narrow_legacy_marker_abort_without_mutation(self):
        mismatch = config_with([managed_source(1, "owner/one", account_id=999)])
        mismatch_before = copy.deepcopy(mismatch)
        with self.assertRaisesRegex(ValueError, "^github_star_account_mismatch:"):
            github_stars.merge_github_star_sources(mismatch, account=ACCOUNT, repositories=[])
        self.assertEqual(mismatch, mismatch_before)

        legacy = config_with(
            [manual_source("legacy_one", "owner/one", notes="managed_by=github_stars")],
            bound=False,
        )
        legacy_before = copy.deepcopy(legacy)
        self.assert_error_code(
            "github_star_binding_ambiguous",
            lambda: github_stars.merge_github_star_sources(
                legacy,
                account=ACCOUNT,
                repositories=[{"id": 1, "full_name": "owner/one"}],
            ),
        )
        self.assertEqual(legacy, legacy_before)

    def test_confirmation_is_required_only_for_risky_merge_classes_or_first_binding(self):
        cases = [
            (config_with([], bound=False), [{"id": 1, "full_name": "owner/one"}], True),
            (config_with([]), [{"id": 1, "full_name": "owner/one"}], False),
            (config_with([managed_source(1, "owner/one")]), [], True),
            (config_with([manual_source("manual_one", "owner/one")]), [{"id": 1, "full_name": "owner/one"}], True),
            (config_with([managed_source(1, "owner/one", state="auto_disabled")]), [{"id": 1, "full_name": "owner/one"}], False),
        ]
        for config, repositories, expected in cases:
            with self.subTest(expected=expected, config=config):
                result = github_stars.merge_github_star_sources(config, account=ACCOUNT, repositories=repositories)
                self.assertEqual(result["requires_confirmation"], expected)


class GitHubStarCapacityTests(GitHubStarsTestCase):
    def test_opml_wrapper_does_not_count_but_disabled_sources_do(self):
        sources = [rss_source(index) for index in range(299)]
        config = config_with([*sources, online_sources.generated_opml_source(True)])

        result = github_stars.merge_github_star_sources(
            config,
            account=ACCOUNT,
            repositories=[{"id": 1, "full_name": "owner/one"}],
        )

        self.assertEqual(len(result["config"]["sources"]), 300)

        full_config = config_with([*sources, rss_source(999, enabled=False)])
        before = copy.deepcopy(full_config)
        self.assert_error_code(
            "github_star_capacity_exceeded",
            lambda: github_stars.merge_github_star_sources(
                full_config,
                account=ACCOUNT,
                repositories=[{"id": 1, "full_name": "owner/one"}],
            ),
        )
        self.assertEqual(full_config, before)

    def test_disabling_does_not_free_capacity_but_adoption_is_allowed(self):
        base = [rss_source(index) for index in range(299)]
        disable_and_add = config_with([*base, managed_source(1, "owner/old")])
        self.assert_error_code(
            "github_star_capacity_exceeded",
            lambda: github_stars.merge_github_star_sources(
                disable_and_add,
                account=ACCOUNT,
                repositories=[{"id": 2, "full_name": "owner/new"}],
            ),
        )

        adopt_at_capacity = config_with([*base, manual_source("manual_one", "owner/one")])
        adopted = github_stars.merge_github_star_sources(
            adopt_at_capacity,
            account=ACCOUNT,
            repositories=[{"id": 1, "full_name": "owner/one"}],
        )
        self.assertEqual(len(adopted["config"]["sources"]), 300)
        self.assertEqual([item["repo_id"] for item in adopted["summary"]["adopted"]], [1])

    def test_three_hundred_user_sources_plus_wrapper_allow_no_change_adoption_and_rename(self):
        base = [rss_source(index) for index in range(299)]
        wrapper = online_sources.generated_opml_source(True)
        cases = [
            (
                config_with([*base, managed_source(1, "owner/one"), wrapper]),
                [{"id": 1, "full_name": "owner/one"}],
                None,
            ),
            (
                config_with([*base, manual_source("manual_one", "owner/one"), wrapper]),
                [{"id": 1, "full_name": "owner/one"}],
                "adopted",
            ),
            (
                config_with([*base, managed_source(1, "owner/old"), wrapper]),
                [{"id": 1, "full_name": "owner/new"}],
                "renamed",
            ),
        ]
        for config, repositories, summary_key in cases:
            with self.subTest(summary_key=summary_key):
                result = github_stars.merge_github_star_sources(
                    config,
                    account=ACCOUNT,
                    repositories=repositories,
                )
                self.assertEqual(len(result["config"]["sources"]), 300)
                if summary_key is not None:
                    self.assertEqual(len(result["summary"][summary_key]), 1)

        too_many = config_with([*[rss_source(index) for index in range(301)], wrapper])
        self.assert_error_code(
            "github_star_capacity_exceeded",
            lambda: github_stars.merge_github_star_sources(
                too_many,
                account=ACCOUNT,
                repositories=[],
            ),
        )


class GitHubStarPreviewHashTests(GitHubStarsTestCase):
    def test_hash_is_stable_for_reordered_repositories_and_summary_arrays(self):
        summary = {key: [] for key in github_stars.SUMMARY_KEYS}
        summary["added"] = [
            {"repo_id": 2, "repo": "owner/two", "source_id": "two"},
            {"repo_id": 1, "repo": "owner/one", "source_id": "one"},
        ]
        kwargs = {
            "account": ACCOUNT,
            "repositories": [{"id": 2, "full_name": "owner/two"}, {"id": 1, "full_name": "owner/one"}],
            "base_config_digest": "a" * 64,
            "binding": None,
            "summary": summary,
        }

        first = github_stars.build_github_star_preview_hash(**kwargs)
        reordered = github_stars.build_github_star_preview_hash(
            **{
                **kwargs,
                "repositories": list(reversed(kwargs["repositories"])),
                "summary": {**summary, "added": list(reversed(summary["added"]))},
            }
        )

        self.assertRegex(first, re.compile(r"^[0-9a-f]{64}$"))
        self.assertEqual(first, reordered)

        changes = [
            {**kwargs, "account": {"id": 999, "login": "example-user"}},
            {
                **kwargs,
                "repositories": [
                    {"id": 2, "full_name": "owner/two"},
                    {"id": 1, "full_name": "owner/renamed"},
                ],
            },
            {**kwargs, "base_config_digest": "b" * 64},
            {**kwargs, "binding": {"version": 1, "account_id": ACCOUNT["id"], "account_login": ACCOUNT["login"]}},
            {**kwargs, "summary": {**summary, "added": [], "disabled": summary["added"]}},
        ]
        for changed in changes:
            with self.subTest(changed=changed):
                self.assertNotEqual(first, github_stars.build_github_star_preview_hash(**changed))

    def test_preview_is_deterministic_and_no_change_preserves_timestamp(self):
        config = config_with([managed_source(1, "owner/one")])
        snapshot = {
            "account": ACCOUNT,
            "repositories": [{"id": 1, "full_name": "owner/one"}],
            "starred_count": 1,
            "private_skipped_count": 0,
        }

        merged = github_stars.merge_github_star_sources(
            config,
            account=ACCOUNT,
            repositories=snapshot["repositories"],
        )
        first = github_stars.build_github_star_preview(config, snapshot)
        second = github_stars.build_github_star_preview(config, snapshot)

        self.assertEqual(merged["config"]["updated_at"], config["updated_at"])
        self.assertEqual(merged["config"], online_sources.validate_online_config_schema(config, existing=True))
        self.assertEqual(first, second)
        self.assertFalse(first["requires_confirmation"])
        self.assertFalse(first["config_changed"])
        self.assertEqual(first["base_config_digest"], online_sources.online_config_digest(config))
        self.assertNotIn("config", first)

    def test_every_merge_class_is_idempotent_on_the_second_pass(self):
        cases = [
            (config_with([]), [{"id": 1, "full_name": "owner/one"}], ()),
            (
                config_with([manual_source("manual_one", "owner/one")]),
                [{"id": 1, "full_name": "owner/one"}],
                (),
            ),
            (
                config_with([managed_source(1, "owner/old")]),
                [{"id": 1, "full_name": "owner/new"}],
                (),
            ),
            (config_with([managed_source(1, "owner/one")]), [], ()),
            (
                config_with([managed_source(1, "owner/one", state="auto_disabled")]),
                [{"id": 1, "full_name": "owner/one"}],
                (),
            ),
            (
                config_with(
                    [
                        manual_source(
                            "manual_one",
                            "owner/one",
                            enabled=False,
                            name="Keep manual disabled",
                            notes="keep manual disabled",
                        )
                    ]
                ),
                [{"id": 1, "full_name": "owner/one"}],
                ("skipped_manual_disabled",),
            ),
            (
                config_with(
                    [
                        managed_source(
                            1,
                            "owner/one",
                            name="Keep auto disabled",
                            notes="keep auto disabled",
                            state="auto_disabled",
                        )
                    ]
                ),
                [],
                (),
            ),
        ]
        for config, repositories, repeated_summary_keys in cases:
            with self.subTest(config=config, repositories=repositories):
                first = github_stars.merge_github_star_sources(
                    config,
                    account=ACCOUNT,
                    repositories=repositories,
                )
                second = github_stars.merge_github_star_sources(
                    first["config"],
                    account=ACCOUNT,
                    repositories=repositories,
                )

                self.assertEqual(second["config"], first["config"])
                self.assertEqual(
                    {key for key, items in second["summary"].items() if items},
                    set(repeated_summary_keys),
                )
                if repeated_summary_keys:
                    self.assertEqual(second["summary"], first["summary"])
                self.assertFalse(second["config_changed"])
                self.assertFalse(second["requires_confirmation"])

    def test_preview_rejects_bool_or_float_starred_count(self):
        config = config_with([], bound=False)
        for value in [True, 1.0]:
            with self.subTest(value=value):
                snapshot = {
                    "account": ACCOUNT,
                    "repositories": [{"id": 1, "full_name": "owner/one"}],
                    "starred_count": value,
                    "private_skipped_count": 0,
                }
                self.assert_error_code(
                    "github_upstream_invalid_response",
                    lambda snapshot=snapshot: github_stars.build_github_star_preview(config, snapshot),
                )


class GitHubStarServiceTests(GitHubStarsTestCase):
    def test_preview_releases_shared_lock_before_github_network(self):
        config = config_with([], bound=False)
        snapshot = {
            "account": ACCOUNT,
            "repositories": [],
            "starred_count": 0,
            "private_skipped_count": 0,
        }
        lock_results = []

        def fetch_while_other_thread_takes_lock(*_args, **_kwargs):
            finished = threading.Event()

            def take_lock():
                try:
                    with online_sources.online_sources_guard():
                        lock_results.append("acquired")
                except online_sources.OnlineSourcesError as exc:
                    lock_results.append(exc.code)
                finally:
                    finished.set()

            thread = threading.Thread(target=take_lock)
            thread.start()
            self.assertTrue(finished.wait(2))
            thread.join(2)
            return snapshot

        with patch.object(online_sources, "audit_online_source_operation", return_value=None), patch.object(
            online_sources, "_read_online_json_config", return_value=config
        ), patch.object(
            github_stars,
            "fetch_github_star_snapshot",
            side_effect=fetch_while_other_thread_takes_lock,
        ):
            result = github_stars.preview_github_star_sync(
                object(),
                {"username": ACCOUNT["login"]},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(lock_results, ["acquired"])

    def test_preview_reads_bound_identity_then_fetches_outside_config_snapshot(self):
        config = config_with([managed_source(1, "owner/one")])
        snapshot = {
            "account": ACCOUNT,
            "repositories": [{"id": 1, "full_name": "owner/one"}],
            "starred_count": 1,
            "private_skipped_count": 0,
        }
        with patch.object(online_sources, "audit_online_source_operation", return_value=None), patch.object(
            online_sources, "_read_online_json_config", return_value=config
        ), patch.object(
            github_stars, "fetch_github_star_snapshot", return_value=snapshot
        ) as fetch_mock:
            result = github_stars.preview_github_star_sync(object(), {})

        self.assertTrue(result["ok"])
        fetch_mock.assert_called_once()
        self.assertEqual(fetch_mock.call_args.kwargs["username"], ACCOUNT["login"])
        self.assertNotIn("account_id", fetch_mock.call_args.kwargs)

    def test_apply_requeries_account_id_and_rejects_config_changed_after_network(self):
        initial = config_with([], bound=False)
        changed = config_with([rss_source(1)], bound=False)
        snapshot = {
            "account": ACCOUNT,
            "repositories": [{"id": 1, "full_name": "owner/one"}],
            "starred_count": 1,
            "private_skipped_count": 0,
        }
        preview_hash = github_stars.build_github_star_preview(initial, snapshot)["preview_hash"]
        with patch.object(online_sources, "audit_online_source_operation", return_value=None), patch.object(
            online_sources,
            "_read_online_json_config",
            side_effect=[initial, changed],
        ), patch.object(
            github_stars, "fetch_github_star_snapshot", return_value=snapshot
        ) as fetch_mock, patch.object(
            online_sources, "apply_online_source_config_operation"
        ) as apply_mock:
            with self.assertRaises(github_stars.GitHubStarsError) as raised:
                github_stars.apply_github_star_sync(
                    object(),
                    {"account_id": ACCOUNT["id"], "preview_hash": preview_hash},
                )

        self.assertEqual(raised.exception.code, "github_star_preview_stale")
        self.assertEqual(fetch_mock.call_args.kwargs["account_id"], ACCOUNT["id"])
        apply_mock.assert_not_called()

    def test_unbind_only_removes_binding_and_managed_fields(self):
        source = managed_source(
            1,
            "owner/one",
            name="Keep name",
            notes="Keep notes",
            state="auto_disabled",
        )
        config = config_with([source])
        captured = {}

        def capture_operation(_root, candidate, **kwargs):
            captured["candidate"] = candidate
            captured["kwargs"] = kwargs
            return {"ok": True, "outcome": "pushed"}

        with patch.object(online_sources, "audit_online_source_operation", return_value=None), patch.object(
            online_sources, "_read_online_json_config", return_value=config
        ), patch.object(
            online_sources,
            "apply_online_source_config_operation",
            side_effect=capture_operation,
        ):
            result = github_stars.unbind_github_star_sync(
                object(),
                {"account_id": ACCOUNT["id"], "confirmed": True},
                if_match=online_sources.online_config_etag(config),
            )

        unbound = captured["candidate"]
        kept = unbound["sources"][0]
        self.assertTrue(result["ok"])
        self.assertNotIn("github_star_sync", unbound)
        for field in online_sources.GITHUB_MANAGED_FIELDS:
            self.assertNotIn(field, kept)
        self.assertEqual(kept["id"], source["id"])
        self.assertEqual(kept["enabled"], source["enabled"])
        self.assertEqual(kept["name"], source["name"])
        self.assertEqual(kept["notes"], source["notes"])
        self.assertEqual(captured["kwargs"]["operation_kind"], "unbind")


if __name__ == "__main__":
    unittest.main()
