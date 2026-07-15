import json
import asyncio
import argparse
import contextlib
import hashlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts import run_mediacrawler_douyin as runner
from scripts.run_mediacrawler_douyin import (
    DouyinRunObserver,
    PipelineFileLock,
    assert_dedicated_browser_process,
    assert_window_mode_result,
    browser_window_commands,
    creator_output_delta,
    dedicated_browser_args,
    ensure_dedicated_browser,
    limited_douyin_creator_posts,
    parse_args,
    row_publish_time,
    set_window_bounds_with_retry,
    summarize_creator_jsonl_by_window,
    validate_douyin_aweme_page,
    validate_douyin_profile_response,
    validate_parent_lock_owner,
)


class MediaCrawlerRunnerTests(unittest.TestCase):
    @staticmethod
    def jsonl_bytes(*ids, extra=None):
        rows = [{"aweme_id": value, **(extra or {})} for value in ids]
        return ("\n".join(json.dumps(row) for row in rows) + ("\n" if rows else "")).encode()

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

    def test_dedicated_browser_args_use_exact_mode_and_url_last(self):
        profile = Path("C:/collector/profile")
        offscreen = dedicated_browser_args("chrome.exe", 9333, profile, "https://www.douyin.com/", True)
        visible = dedicated_browser_args("chrome.exe", 9333, profile, "https://www.douyin.com/", False)

        self.assertIn("--window-position=-32000,-32000", offscreen)
        self.assertIn("--window-size=1600,900", offscreen)
        self.assertNotIn("--start-maximized", offscreen)
        self.assertIn("--hide-crash-restore-bubble", offscreen)
        self.assertIn("--start-maximized", visible)
        self.assertIn("--hide-crash-restore-bubble", visible)
        self.assertFalse(any(arg.startswith("--window-position") for arg in visible))
        self.assertEqual(offscreen[-1], "https://www.douyin.com/")
        self.assertEqual(visible[-1], "https://www.douyin.com/")

    def test_window_mode_commands_normalize_before_target_state(self):
        screen = {"left": -1920, "top": 0, "width": 3840, "height": 1080}

        self.assertEqual(
            browser_window_commands(False, screen),
            [
                {"windowState": "normal"},
                {"left": 80, "top": 80, "width": 1600, "height": 900},
                {"windowState": "maximized"},
            ],
        )
        self.assertEqual(
            browser_window_commands(True, screen),
            [
                {"windowState": "normal"},
                {"left": -3620, "top": 0, "width": 1600, "height": 900},
            ],
        )

    def test_window_mode_rejects_rdp_clamped_offscreen_bounds(self):
        screen = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        with self.assertRaisesRegex(RuntimeError, "still_intersects"):
            assert_window_mode_result({"left": 0, "top": 0, "width": 1600, "height": 900}, screen, True)
        assert_window_mode_result({"left": -1700, "top": 0, "width": 1600, "height": 900}, screen, True)
        assert_window_mode_result({"left": 0, "top": 0, "width": 1600, "height": 900}, screen, False)

    def test_window_bounds_retry_waits_for_maximized_window_to_become_normal(self):
        class FakeSession:
            def __init__(self):
                self.get_results = [
                    {"bounds": {"left": 80, "top": 80, "width": 1600, "height": 900, "windowState": "maximized"}},
                    {"bounds": {"left": 80, "top": 80, "width": 1600, "height": 900, "windowState": "normal"}},
                ]
                self.set_calls = []

            async def send(self, method, payload=None):
                if method == "Browser.setWindowBounds":
                    self.set_calls.append(payload)
                    return {}
                if method == "Browser.getWindowBounds":
                    return self.get_results.pop(0)
                raise AssertionError(method)

        session = FakeSession()
        requested = {"windowState": "normal"}
        actual = asyncio.run(set_window_bounds_with_retry(session, 7, requested, attempts=2, delay_seconds=0))

        self.assertEqual(actual["windowState"], "normal")
        self.assertEqual(len(session.set_calls), 2)
        self.assertTrue(all(call == {"windowId": 7, "bounds": requested} for call in session.set_calls))

    def test_existing_cdp_still_applies_requested_window_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp)
            profile = (crawler / "chrome-profile").resolve()
            lookup = lambda port: [{
                "pid": 41,
                "command_line": f'chrome.exe --remote-debugging-port={port} "--user-data-dir={profile}"',
            }]
            applied = []
            with mock.patch.object(runner, "is_port_open", return_value=True), mock.patch.object(runner, "cdp_ready", return_value=True):
                port = ensure_dedicated_browser(
                    crawler,
                    9333,
                    "",
                    "",
                    "https://www.douyin.com/",
                    True,
                    process_lookup=lookup,
                    window_mode_applier=lambda value, mode: applied.append((value, mode)),
                )

            self.assertEqual(port, 9333)
            self.assertEqual(applied, [(9333, True)])

    def test_new_cdp_is_verified_then_window_mode_is_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp)
            profile = (crawler / "chrome-profile").resolve()
            lookup = lambda port: [{
                "pid": 42,
                "command_line": f'chrome.exe --remote-debugging-port={port} "--user-data-dir={profile}"',
            }]
            applied = []
            with mock.patch.object(runner, "is_port_open", return_value=False), \
                    mock.patch.object(runner, "cdp_ready", return_value=True), \
                    mock.patch.object(runner, "find_chrome", return_value="chrome.exe"), \
                    mock.patch.object(runner, "launch_dedicated_browser") as launch:
                port = ensure_dedicated_browser(
                    crawler,
                    9333,
                    "",
                    "",
                    "https://www.douyin.com/",
                    False,
                    process_lookup=lookup,
                    window_mode_applier=lambda value, mode: applied.append((value, mode)),
                )

            self.assertEqual(port, 9333)
            launch.assert_called_once_with("chrome.exe", 9333, profile, "https://www.douyin.com/", False)
            self.assertEqual(applied, [(9333, False)])

    def test_cdp_conflicts_never_move_window_or_choose_another_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp)
            with mock.patch.object(runner, "is_port_open", return_value=True), mock.patch.object(runner, "cdp_ready", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "cdp_port_conflict"):
                    ensure_dedicated_browser(crawler, 9333, "", "", "https://www.douyin.com/")

            profile = (crawler / "chrome-profile").resolve()
            wrong_lookup = lambda port: [{
                "pid": 99,
                "command_line": f'chrome.exe --remote-debugging-port={port} "--user-data-dir={crawler / "other"}"',
            }]
            with self.assertRaisesRegex(RuntimeError, "different browser profile"):
                assert_dedicated_browser_process(9333, profile, wrong_lookup)

    def test_window_mode_failure_propagates_before_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp)
            profile = (crawler / "chrome-profile").resolve()
            lookup = lambda port: [{
                "pid": 41,
                "command_line": f'chrome.exe --remote-debugging-port={port} "--user-data-dir={profile}"',
            }]
            with mock.patch.object(runner, "is_port_open", return_value=True), mock.patch.object(runner, "cdp_ready", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "mode failed"):
                    ensure_dedicated_browser(
                        crawler,
                        9333,
                        "",
                        "",
                        "https://www.douyin.com/",
                        process_lookup=lookup,
                        window_mode_applier=lambda *_: (_ for _ in ()).throw(RuntimeError("mode failed")),
                    )

    def test_offscreen_default_ignores_environment_strings(self):
        argv = ["runner", "--crawler-root", "C:/crawler", "--platform", "douyin"]
        with mock.patch.dict(os.environ, {"MEDIACRAWLER_BROWSER_OFFSCREEN": "false"}), mock.patch("sys.argv", argv):
            self.assertFalse(parse_args().offscreen)
        with mock.patch.dict(os.environ, {"MEDIACRAWLER_BROWSER_OFFSCREEN": "0"}), mock.patch("sys.argv", argv):
            self.assertFalse(parse_args().offscreen)

    def test_pipeline_lock_is_nonblocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pipeline.lock"
            with PipelineFileLock(path):
                with self.assertRaisesRegex(RuntimeError, "busy"):
                    with PipelineFileLock(path):
                        self.fail("second lock unexpectedly succeeded")
            with PipelineFileLock(path):
                pass

    def test_parent_lock_requires_token_run_id_and_live_owner(self):
        token = "one-time-secret"
        owner = {
            "owner_pid": 123,
            "run_id": "run-a",
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        }
        self.assertTrue(validate_parent_lock_owner("run-a", token, owner_data=owner, alive_checker=lambda _: True, start_monitor=False))
        self.assertFalse(validate_parent_lock_owner("run-b", token, owner_data=owner, alive_checker=lambda _: True, start_monitor=False))
        self.assertFalse(validate_parent_lock_owner("run-a", "wrong", owner_data=owner, alive_checker=lambda _: True, start_monitor=False))
        self.assertFalse(validate_parent_lock_owner("run-a", token, owner_data=owner, alive_checker=lambda _: False, start_monitor=False))

    def test_output_delta_counts_duplicate_and_unique_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "creator_contents_2026-07-15.jsonl"
            before_data = self.jsonl_bytes("A", "B")
            after_data = before_data + self.jsonl_bytes("A", "C", "C")
            path.write_bytes(after_data)

            delta = creator_output_delta({str(path): before_data}, {str(path): after_data})

            self.assertFalse(delta["ambiguous"])
            self.assertEqual(delta["output_rows"], 5)
            self.assertEqual(delta["crawl_output_rows"], 3)
            self.assertEqual(delta["new_unique_items"], 1)

    def test_output_delta_duplicate_only_is_not_new_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "creator_contents_2026-07-15.jsonl"
            before_data = self.jsonl_bytes("A")
            after_data = before_data + self.jsonl_bytes("A", "A")
            path.write_bytes(after_data)

            delta = creator_output_delta({str(path): before_data}, {str(path): after_data})

            self.assertEqual(delta["crawl_output_rows"], 2)
            self.assertEqual(delta["new_unique_items"], 0)

    def test_output_delta_uses_all_historical_files_for_new_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            yesterday = Path(tmp) / "creator_contents_2026-07-14.jsonl"
            today = Path(tmp) / "creator_contents_2026-07-15.jsonl"
            old_data = self.jsonl_bytes("A", "B")
            new_data = self.jsonl_bytes("A", "C", "C")
            yesterday.write_bytes(old_data)
            today.write_bytes(new_data)

            delta = creator_output_delta({str(yesterday): old_data}, {str(yesterday): old_data, str(today): new_data})

            self.assertEqual(delta["source_file"], str(today))
            self.assertEqual(delta["output_rows"], 3)
            self.assertEqual(delta["crawl_output_rows"], 3)
            self.assertEqual(delta["new_unique_items"], 1)

    def test_zero_output_never_falls_back_to_old_file(self):
        old = self.jsonl_bytes("A")
        delta = creator_output_delta({"old.jsonl": old}, {"old.jsonl": old})
        self.assertEqual(delta["source_file"], "")
        self.assertEqual(delta["crawl_output_rows"], 0)
        self.assertEqual(delta["new_unique_items"], 0)

    def test_rewrite_bad_json_empty_id_and_two_changed_files_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "creator_contents_a.jsonl"
            second = Path(tmp) / "creator_contents_b.jsonl"
            first.write_bytes(self.jsonl_bytes("B"))
            second.write_bytes(self.jsonl_bytes("C"))
            cases = [
                creator_output_delta({str(first): self.jsonl_bytes("A")}, {str(first): self.jsonl_bytes("B")}),
                creator_output_delta({}, {str(first): b"not-json\n"}),
                creator_output_delta({}, {str(first): b'{"aweme_id":""}\n'}),
                creator_output_delta({}, {str(first): self.jsonl_bytes("B"), str(second): self.jsonl_bytes("C")}),
            ]
            for delta in cases:
                self.assertTrue(delta["ambiguous"])
                self.assertIsNone(delta["crawl_output_rows"])
                self.assertIsNone(delta["new_unique_items"])

    def test_profile_and_api_pages_require_explicit_valid_responses(self):
        self.assertEqual(validate_douyin_profile_response({"status_code": 0, "user": {"sec_uid": "abc"}}, "abc")["status_code"], 0)
        for response in ({"user": {"sec_uid": "abc"}}, {"status_code": 1, "user": {"sec_uid": "abc"}}, {"status_code": 0, "user": {"sec_uid": "other"}}):
            with self.assertRaises(RuntimeError):
                validate_douyin_profile_response(response, "abc")
        valid_page = {"status_code": 0, "aweme_list": [], "has_more": 0, "max_cursor": ""}
        self.assertIs(validate_douyin_aweme_page(valid_page), valid_page)
        invalid_pages = [
            {"status_code": 0, "has_more": 0},
            {"status_code": 1, "aweme_list": [], "has_more": 0},
            {"status_code": 0, "aweme_list": [], "has_more": 1, "max_cursor": "next"},
            {"status_code": 0, "aweme_list": [{"aweme_id": "A"}], "has_more": 1, "max_cursor": "same"},
        ]
        for response in invalid_pages:
            with self.assertRaises(RuntimeError):
                validate_douyin_aweme_page(response, "same")

    def test_partial_creator_receipt_cannot_finalize_as_success(self):
        observer = DouyinRunObserver(["a", "b"])
        first = observer.record("a")
        first.update(profile_valid=True, api_pages_valid=True, listed_count=2, written_rows=2)
        second = observer.record("b")
        second.update(profile_valid=True, api_pages_valid=True, listed_count=2, written_rows=1)

        observer.finalize()
        summary = observer.summary()

        self.assertEqual(summary["completed_creator_count"], 1)
        self.assertEqual(summary["failed_creator_count"], 1)

    def test_browser_only_never_calls_mediacrawler(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp)
            (crawler / "main.py").write_text("", encoding="utf-8")
            args = argparse.Namespace(
                crawler_root=str(crawler), platform="douyin", creator_id="", max_notes=0,
                collect_window_hours=0, cdp_port=9333, chrome_path="", profile_dir="",
                offscreen=False, browser_only=True, run_id="", result_file="",
                parent_holds_collection_lock=False,
            )
            with mock.patch.object(runner, "parse_args", return_value=args), \
                    mock.patch.object(runner, "collection_lock_context", return_value=contextlib.nullcontext()), \
                    mock.patch.object(runner, "ensure_dedicated_browser", return_value=9333), \
                    mock.patch.object(runner, "check_douyin_login_state", return_value="login_required"), \
                    mock.patch.object(runner, "run_mediacrawler") as collect:
                self.assertEqual(runner.main(), 0)
            collect.assert_not_called()

    def test_offscreen_login_required_writes_result_and_skips_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp) / "crawler"
            crawler.mkdir()
            (crawler / "main.py").write_text("", encoding="utf-8")
            result_file = Path(tmp) / "result.json"
            args = argparse.Namespace(
                crawler_root=str(crawler), platform="douyin", creator_id="abc123", max_notes=10,
                collect_window_hours=0, cdp_port=9333, chrome_path="", profile_dir="",
                offscreen=True, browser_only=False, run_id="run-login", result_file=str(result_file),
                parent_holds_collection_lock=False,
            )
            with mock.patch.object(runner, "parse_args", return_value=args), \
                    mock.patch.object(runner, "collection_lock_context", return_value=contextlib.nullcontext()), \
                    mock.patch.object(runner, "ensure_dedicated_browser", return_value=9333), \
                    mock.patch.object(runner, "check_douyin_login_state", return_value="login_required"), \
                    mock.patch.object(runner, "run_mediacrawler") as collect:
                self.assertEqual(runner.main(), 1)
            collect.assert_not_called()
            payload = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["run_id"], "run-login")
            self.assertEqual(payload["login_state"], "login_required")
            self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
