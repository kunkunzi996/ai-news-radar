import json
import asyncio
import argparse
import contextlib
import hashlib
import os
import sys
import tempfile
import types
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
    close_cdp_page_targets,
    creator_output_delta,
    dedicated_browser_args,
    ensure_dedicated_browser,
    list_cdp_page_targets,
    limited_douyin_creator_posts,
    parse_args,
    row_publish_time,
    select_leaked_page_targets,
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

    def test_window_mode_failure_does_not_block_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp)
            profile = (crawler / "chrome-profile").resolve()
            lookup = lambda port: [{
                "pid": 41,
                "command_line": f'chrome.exe --remote-debugging-port={port} "--user-data-dir={profile}"',
            }]
            with mock.patch.object(runner, "is_port_open", return_value=True), mock.patch.object(runner, "cdp_ready", return_value=True):
                port = ensure_dedicated_browser(
                    crawler,
                    9333,
                    "",
                    "",
                    "https://www.douyin.com/",
                    True,
                    process_lookup=lookup,
                    window_mode_applier=lambda *_: (_ for _ in ()).throw(
                        RuntimeError("browser_window_bounds_not_applied:requested={'left': -1700}")
                    ),
                )
            self.assertEqual(port, 9333)

    def test_new_cdp_window_mode_failure_does_not_block_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp)
            profile = (crawler / "chrome-profile").resolve()
            lookup = lambda port: [{
                "pid": 42,
                "command_line": f'chrome.exe --remote-debugging-port={port} "--user-data-dir={profile}"',
            }]
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
                    True,
                    process_lookup=lookup,
                    window_mode_applier=lambda *_: (_ for _ in ()).throw(
                        RuntimeError("offscreen_window_still_intersects_virtual_screen")
                    ),
                )
            self.assertEqual(port, 9333)
            launch.assert_called_once()

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

        # BUG-02 三态改造后，「少写一条」从 failed 变为 partial（用户 2026-08-08 拍板）。
        # 本条测试的保护意图不变：**不完整的回执绝不能被当成 completed**。
        self.assertEqual(summary["completed_creator_count"], 1)
        self.assertEqual(summary["partial_creator_count"], 1)
        self.assertEqual(observer.record("b")["state"], "partial")
        self.assertNotEqual(observer.record("b")["state"], "completed")
        self.assertTrue(summary["partial"])

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

    # --- BUG-01 / TASK-01a: 采集结束后只关闭本轮新增的标签页 ---

    DOUYIN_PAGE_URL = "https://www.douyin.com/jingxuan"

    def page_target(self, target_id, url=None):
        return {"id": target_id, "url": url if url is not None else self.DOUYIN_PAGE_URL}

    def test_select_leaked_page_targets_returns_only_new_ids(self):
        before = {"A"}
        after = [self.page_target("A"), self.page_target("B"), self.page_target("C")]

        self.assertEqual(select_leaked_page_targets(before, after), ["B", "C"])

    def test_select_leaked_page_targets_returns_empty_without_new_pages(self):
        self.assertEqual(select_leaked_page_targets({"A"}, [self.page_target("A")]), [])
        self.assertEqual(select_leaked_page_targets(set(), []), [])

    def test_select_leaked_page_targets_keeps_at_least_one_page(self):
        # 关光全部标签页会让 Chrome 退出，等于滑向已放弃的口径 B；保留最早的那个。
        after = [self.page_target("A"), self.page_target("B")]

        self.assertEqual(select_leaked_page_targets(set(), after), ["B"])

    def test_select_leaked_page_targets_distinguishes_identical_urls(self):
        # NUC 实测：三个标签页 URL 完全相同，只有 id 不同，必须按 id 差集判断。
        after = [self.page_target("A"), self.page_target("B")]

        self.assertEqual(select_leaked_page_targets({"A"}, after), ["B"])

    def test_select_leaked_page_targets_tolerates_disappeared_pages(self):
        # 采集前存在的 A 中途被关掉：不报错，也不出现在待关清单里。
        after = [self.page_target("B"), self.page_target("C")]

        self.assertEqual(select_leaked_page_targets({"A", "B"}, after), ["C"])

    # --- BUG-01 / TASK-02a: 列出与关闭 CDP 标签页 ---

    def test_list_cdp_page_targets_keeps_only_page_type(self):
        payload = json.dumps([
            {"id": "A", "type": "page", "url": self.DOUYIN_PAGE_URL},
            {"id": "W", "type": "service_worker", "url": "https://www.douyin.com/sw.js"},
            {"id": "F", "type": "iframe", "url": "https://www.douyin.com/frame"},
            {"id": "B", "type": "page", "url": self.DOUYIN_PAGE_URL},
        ])
        with mock.patch.object(runner, "cdp_request_text", return_value=payload) as request:
            targets = list_cdp_page_targets(9333)

        request.assert_called_once_with(9333, "/json/list")
        self.assertEqual([target["id"] for target in targets], ["A", "B"])
        self.assertEqual(targets[0]["url"], self.DOUYIN_PAGE_URL)

    def test_list_cdp_page_targets_tolerates_missing_fields(self):
        payload = json.dumps([
            {"id": "A", "type": "page"},
            {"type": "page", "url": self.DOUYIN_PAGE_URL},
            "not-a-dict",
        ])
        with mock.patch.object(runner, "cdp_request_text", return_value=payload):
            targets = list_cdp_page_targets(9333)

        self.assertEqual([target["id"] for target in targets], ["A"])
        self.assertEqual(targets[0]["url"], "")

    def test_close_cdp_page_targets_closes_each_id_in_order(self):
        with mock.patch.object(runner, "cdp_request_text", return_value="Target is closing") as request:
            result = close_cdp_page_targets(9333, ["B", "C"])

        self.assertEqual([call.args[1] for call in request.call_args_list], ["/json/close/B", "/json/close/C"])
        self.assertEqual(result, {"closed": 2, "failed": 0})

    def test_close_cdp_page_targets_continues_after_failure(self):
        with mock.patch.object(
            runner, "cdp_request_text", side_effect=[OSError("boom"), "Target is closing"]
        ) as request:
            result = close_cdp_page_targets(9333, ["B", "C"])

        self.assertEqual(request.call_count, 2)
        self.assertEqual(result, {"closed": 1, "failed": 1})

    def test_close_cdp_page_targets_skips_request_for_empty_list(self):
        with mock.patch.object(runner, "cdp_request_text") as request:
            result = close_cdp_page_targets(9333, [])

        request.assert_not_called()
        self.assertEqual(result, {"closed": 0, "failed": 0})

    # --- BUG-01 / TASK-03a: 把清理接进采集主流程 ---

    def collect_args(self, crawler_root, **overrides):
        defaults = dict(
            crawler_root=str(crawler_root), platform="douyin", creator_id="", max_notes=10,
            collect_window_hours=0, cdp_port=9333, chrome_path="", profile_dir="",
            offscreen=False, browser_only=False, run_id="run-cleanup", result_file="",
            parent_holds_collection_lock=False,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    @contextlib.contextmanager
    def patched_collect_run(self, args, *, snapshots, collect_result=0, close_side_effect=None):
        with mock.patch.object(runner, "parse_args", return_value=args), \
                mock.patch.object(runner, "collection_lock_context", return_value=contextlib.nullcontext()), \
                mock.patch.object(runner, "ensure_dedicated_browser", return_value=9333), \
                mock.patch.object(runner, "check_douyin_login_state", return_value="logged_in"), \
                mock.patch.object(runner, "list_cdp_page_targets", side_effect=snapshots) as listed, \
                mock.patch.object(
                    runner, "close_cdp_page_targets",
                    return_value={"closed": 1, "failed": 0}, side_effect=close_side_effect,
                ) as closed, \
                mock.patch.object(runner, "run_mediacrawler", return_value=collect_result):
            yield listed, closed

    def test_collect_closes_only_pages_opened_during_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp)
            (crawler / "main.py").write_text("", encoding="utf-8")
            snapshots = [
                [self.page_target("A")],
                [self.page_target("A"), self.page_target("B")],
            ]
            with self.patched_collect_run(self.collect_args(crawler), snapshots=snapshots) as (listed, closed):
                self.assertEqual(runner.main(), 0)

            self.assertEqual(listed.call_count, 2)
            closed.assert_called_once_with(9333, ["B"])

    def test_browser_only_keeps_every_page_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp)
            (crawler / "main.py").write_text("", encoding="utf-8")
            args = self.collect_args(crawler, browser_only=True)
            snapshots = [[self.page_target("A")], [self.page_target("A")]]
            with self.patched_collect_run(args, snapshots=snapshots) as (_listed, closed):
                self.assertEqual(runner.main(), 0)

            closed.assert_not_called()

    def test_failed_collection_still_closes_leaked_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp)
            (crawler / "main.py").write_text("", encoding="utf-8")
            snapshots = [
                [self.page_target("A")],
                [self.page_target("A"), self.page_target("B")],
            ]
            with self.patched_collect_run(
                self.collect_args(crawler), snapshots=snapshots, collect_result=1
            ) as (_listed, closed):
                self.assertEqual(runner.main(), 1)

            closed.assert_called_once_with(9333, ["B"])

    def test_cleanup_failure_does_not_change_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler = Path(tmp)
            (crawler / "main.py").write_text("", encoding="utf-8")
            snapshots = [
                [self.page_target("A")],
                [self.page_target("A"), self.page_target("B")],
            ]
            with self.patched_collect_run(
                self.collect_args(crawler), snapshots=snapshots, close_side_effect=OSError("cdp down")
            ) as (_listed, closed):
                self.assertEqual(runner.main(), 0)

            closed.assert_called_once_with(9333, ["B"])


class DouyinCreatorIsolationTests(unittest.TestCase):
    """TASK-01：一个创作者被风控，其余创作者必须照常采完。

    复刻 MediaCrawler ``core.py:277-291`` 的创作者循环——那里对
    ``get_user_info`` 与 ``get_all_user_aweme_posts`` 没有任何 try/except，
    所以只要包装层向外抛异常，排在后面的号就一条都采不到。
    """

    @staticmethod
    @contextlib.contextmanager
    def fake_mediacrawler_modules():
        """把 MediaCrawler 的两个模块假注入 sys.modules，用完原样恢复。"""

        class FakeDouYinClient:
            async def get_user_info(self, sec_user_id):  # pragma: no cover - 被 patch 覆盖
                raise AssertionError("stub should be replaced")

            async def get_user_aweme_posts(self, sec_user_id, max_cursor=""):  # pragma: no cover
                raise AssertionError("stub should be replaced")

            async def get_all_user_aweme_posts(self, sec_user_id, callback=None):  # pragma: no cover
                raise AssertionError("stub should be replaced")

            async def get_video_by_id(self, aweme_id):  # pragma: no cover
                raise AssertionError("stub should be replaced")

        stored = []

        async def noop_store(aweme_item):
            return None

        media_platform = types.ModuleType("media_platform")
        media_platform.__path__ = []
        douyin_pkg = types.ModuleType("media_platform.douyin")
        douyin_pkg.__path__ = []
        client_mod = types.ModuleType("media_platform.douyin.client")
        client_mod.DouYinClient = FakeDouYinClient
        store_pkg = types.ModuleType("store")
        store_pkg.__path__ = []
        store_douyin = types.ModuleType("store.douyin")
        store_douyin.update_douyin_aweme = noop_store

        names = {
            "media_platform": media_platform,
            "media_platform.douyin": douyin_pkg,
            "media_platform.douyin.client": client_mod,
            "store": store_pkg,
            "store.douyin": store_douyin,
        }
        saved = {name: sys.modules.get(name) for name in names}
        sys.modules.update(names)
        try:
            yield FakeDouYinClient, store_douyin, stored
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    @staticmethod
    async def run_creator_loop(client, sec_uids):
        """复刻 MediaCrawler 的创作者循环：没有 try/except，异常会中断全部剩余创作者。"""
        visited = []
        for sec_uid in sec_uids:
            visited.append(sec_uid)
            creator_info = await client.get_user_info(sec_uid)
            if creator_info:
                pass  # 对应 core.py 的 save_creator
            await client.get_all_user_aweme_posts(sec_uid, callback=None)
        return visited

    def test_profile_failure_is_isolated_and_returns_empty(self):
        with self.fake_mediacrawler_modules() as (client_cls, _store, _rows):
            observer = DouyinRunObserver(["good", "blocked"])

            async def failing_profile(self, sec_user_id):
                if sec_user_id == "blocked":
                    raise RuntimeError("Blocked by ArgusSecurityPlugin Validate Error")
                return {"status_code": 0, "user": {"sec_uid": sec_user_id}}

            client_cls.get_user_info = failing_profile
            runner.install_douyin_observer(observer, 10)
            client = client_cls()

            result = asyncio.run(client.get_user_info("blocked"))

            self.assertEqual(result, {})
            self.assertEqual(observer.record("blocked")["state"], "failed")

    def test_listing_failure_returns_collected_rows_without_raising(self):
        with self.fake_mediacrawler_modules() as (client_cls, _store, _rows):
            observer = DouyinRunObserver(["creator"])
            calls = []

            async def flaky_pages(self, sec_user_id, max_cursor=""):
                calls.append(max_cursor)
                if len(calls) == 1:
                    return {
                        "status_code": 0,
                        "aweme_list": [{"aweme_id": "A"}, {"aweme_id": "B"}],
                        "has_more": 1,
                        "max_cursor": "cursor-2",
                    }
                raise RuntimeError("Blocked by ArgusSecurityPlugin Validate Error")

            client_cls.get_user_aweme_posts = flaky_pages
            runner.install_douyin_observer(observer, 10)
            client = client_cls()

            rows = asyncio.run(client.get_all_user_aweme_posts("creator", callback=None))

            self.assertEqual([row["aweme_id"] for row in rows], ["A", "B"])
            self.assertEqual(observer.record("creator")["state"], "failed")

    def test_one_blocked_creator_does_not_stop_the_remaining_ones(self):
        with self.fake_mediacrawler_modules() as (client_cls, _store, _rows):
            sec_uids = [f"creator-{index}" for index in range(1, 7)]
            observer = DouyinRunObserver(sec_uids)

            async def profile(self, sec_user_id):
                if sec_user_id == "creator-2":
                    raise RuntimeError("Blocked by ArgusSecurityPlugin Validate Error")
                return {"status_code": 0, "user": {"sec_uid": sec_user_id}}

            async def pages(self, sec_user_id, max_cursor=""):
                if sec_user_id == "creator-2":
                    raise RuntimeError("Blocked by ArgusSecurityPlugin Validate Error")
                return {"status_code": 0, "aweme_list": [{"aweme_id": f"{sec_user_id}-A"}], "has_more": 0, "max_cursor": ""}

            client_cls.get_user_info = profile
            client_cls.get_user_aweme_posts = pages
            runner.install_douyin_observer(observer, 10)
            client = client_cls()

            visited = asyncio.run(self.run_creator_loop(client, sec_uids))

            self.assertEqual(visited, sec_uids, "第 2 个号被风控后，第 3~6 个号必须照常被访问")
            self.assertEqual(observer.record("creator-2")["state"], "failed")
            self.assertEqual(observer.record("creator-6")["listed_count"], 1)


class DouyinDetailRetryTests(unittest.TestCase):
    """TASK-02：视频详情被风控拦下时先退避重试，耗尽后必须抛回原异常。

    MediaCrawler ``core.py:227`` 只 catch ``DataFetchError``，靠它把失败的那条
    转成 ``return None``。所以重试耗尽后抛回的必须是**原异常对象**，
    类型一旦被改写，上游的 except 就接不住，整轮采集会直接崩。
    """

    fake_mediacrawler_modules = staticmethod(DouyinCreatorIsolationTests.fake_mediacrawler_modules)

    def test_detail_retries_and_succeeds_without_surfacing_the_error(self):
        with self.fake_mediacrawler_modules() as (client_cls, _store, _rows):
            observer = DouyinRunObserver(["creator"])
            attempts = []
            slept = []

            async def flaky_detail(self, aweme_id):
                attempts.append(aweme_id)
                if len(attempts) == 1:
                    raise RuntimeError("Blocked by ArgusSecurityPlugin Validate Error")
                return {"aweme_id": aweme_id, "desc": "ok"}

            async def fake_sleep(seconds):
                slept.append(seconds)

            client_cls.get_video_by_id = flaky_detail
            runner.install_douyin_observer(observer, 10, sleeper=fake_sleep)
            client = client_cls()

            detail = asyncio.run(client.get_video_by_id("aweme-1"))

            self.assertEqual(detail, {"aweme_id": "aweme-1", "desc": "ok"})
            self.assertEqual(len(attempts), 2, "首次被风控后必须重试一次")
            self.assertEqual(len(slept), 1, "重试之间必须退避等待")
            self.assertGreater(slept[0], 0)

    def test_detail_raises_the_original_exception_after_retries_are_exhausted(self):
        with self.fake_mediacrawler_modules() as (client_cls, _store, _rows):
            observer = DouyinRunObserver(["creator"])
            attempts = []
            errors = []

            async def always_blocked(self, aweme_id):
                attempts.append(aweme_id)
                error = RuntimeError("Blocked by ArgusSecurityPlugin Validate Error")
                errors.append(error)
                raise error

            async def fake_sleep(seconds):
                return None

            client_cls.get_video_by_id = always_blocked
            runner.install_douyin_observer(observer, 10, sleeper=fake_sleep)
            client = client_cls()

            with self.assertRaises(RuntimeError) as caught:
                asyncio.run(client.get_video_by_id("aweme-2"))

            self.assertIs(caught.exception, errors[-1], "必须抛回原异常对象，类型不可被改写")
            self.assertGreaterEqual(len(attempts), 2, "耗尽前必须真的重试过")

    def test_detail_wrapper_does_not_retry_on_success(self):
        with self.fake_mediacrawler_modules() as (client_cls, _store, _rows):
            observer = DouyinRunObserver(["creator"])
            attempts = []
            slept = []

            async def healthy_detail(self, aweme_id):
                attempts.append(aweme_id)
                return {"aweme_id": aweme_id}

            async def fake_sleep(seconds):
                slept.append(seconds)

            client_cls.get_video_by_id = healthy_detail
            runner.install_douyin_observer(observer, 10, sleeper=fake_sleep)
            client = client_cls()

            detail = asyncio.run(client.get_video_by_id("aweme-3"))

            self.assertEqual(detail, {"aweme_id": "aweme-3"})
            self.assertEqual(len(attempts), 1, "成功时不得产生多余请求")
            self.assertEqual(slept, [], "成功时不得退避等待")


class DouyinPartialReceiptTests(unittest.TestCase):
    """TASK-03：回执三态 + 采到多少发多少 + 异常消息净化。

    用户 2026-08-08 拍板：「不管采集了多少，都同步到 AI 看板上」。
    保留的唯一 fail-safe 是「一个号都没采到」——那不是风控偶发，是登录态或网络挂了。
    """

    @staticmethod
    def record_of(observer, creator_id, **fields):
        record = observer.record(creator_id)
        record.update(fields)
        return record

    def test_finalize_marks_three_distinct_states(self):
        observer = DouyinRunObserver(["full", "short", "dead", "empty"])
        self.record_of(observer, "full", profile_valid=True, api_pages_valid=True, listed_count=10, written_rows=10)
        self.record_of(observer, "short", profile_valid=True, api_pages_valid=True, listed_count=10, written_rows=9)
        self.record_of(observer, "dead", profile_valid=False, api_pages_valid=False, listed_count=0, written_rows=0)
        self.record_of(observer, "empty", profile_valid=True, api_pages_valid=True, listed_count=0, written_rows=0)

        observer.finalize()

        self.assertEqual(observer.record("full")["state"], "completed")
        self.assertEqual(observer.record("short")["state"], "partial")
        self.assertEqual(observer.record("dead")["state"], "failed")
        self.assertEqual(
            observer.record("empty")["state"], "completed",
            "合法空账号必须仍算完成，否则 PS 脚本的 allExplicitlyEmpty 分支会被破坏",
        )
        self.assertEqual(observer.record("short")["missing_rows"], 1)

    def test_summary_reports_partial_counts_and_missing_rows(self):
        observer = DouyinRunObserver(["full", "short", "dead"])
        self.record_of(observer, "full", profile_valid=True, api_pages_valid=True, listed_count=10, written_rows=10)
        self.record_of(observer, "short", profile_valid=True, api_pages_valid=True, listed_count=10, written_rows=7)
        self.record_of(observer, "dead", profile_valid=False, api_pages_valid=False, listed_count=0, written_rows=0)

        observer.finalize()
        summary = observer.summary()

        self.assertEqual(summary["completed_creator_count"], 1)
        self.assertEqual(summary["partial_creator_count"], 1)
        self.assertEqual(summary["failed_creator_count"], 1)
        self.assertEqual(summary["missing_rows"], 3)
        self.assertTrue(summary["partial"])

    def test_summary_is_not_partial_when_everything_completed(self):
        observer = DouyinRunObserver(["a", "b"])
        self.record_of(observer, "a", profile_valid=True, api_pages_valid=True, listed_count=3, written_rows=3)
        self.record_of(observer, "b", profile_valid=True, api_pages_valid=True, listed_count=4, written_rows=4)

        observer.finalize()
        summary = observer.summary()

        self.assertFalse(summary["partial"])
        self.assertEqual(summary["missing_rows"], 0)

    def test_failure_message_never_leaks_the_raw_response_body(self):
        observer = DouyinRunObserver(["creator"])
        # MediaCrawler client.py:135 抛的是 DataFetchError(f"{e}, {response.text}")，
        # 也就是把抖音的原始响应体拼进了异常消息。
        observer.fail("creator", "Expecting value: line 1 column 1 (char 0), <html>SECRET_BODY</html>")

        stored = observer.record("creator")["error"]

        self.assertNotIn("SECRET_BODY", stored)
        self.assertNotIn("<html>", stored)
        self.assertLessEqual(len(stored), 200)
        self.assertTrue(stored, "净化后仍须保留可诊断的分类，不能变成空字符串")

    def test_risk_control_message_is_normalized_to_a_stable_category(self):
        observer = DouyinRunObserver(["creator"])
        observer.fail("creator", "Expecting value: line 1 column 1 (char 0), Blocked by ArgusSecurityPlugin Validate Error")

        self.assertEqual(observer.record("creator")["error"], "douyin_risk_control")

    def collect_args(self, crawler_root, **overrides):
        defaults = dict(
            crawler_root=str(crawler_root), platform="douyin", creator_id="c1,c2,c3", max_notes=10,
            collect_window_hours=0, cdp_port=9333, chrome_path="", profile_dir="",
            offscreen=False, browser_only=False, run_id="run-partial", result_file="",
            parent_holds_collection_lock=False,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    @contextlib.contextmanager
    def patched_main(self, args, collect):
        with mock.patch.object(runner, "parse_args", return_value=args), \
                mock.patch.object(runner, "collection_lock_context", return_value=contextlib.nullcontext()), \
                mock.patch.object(runner, "ensure_dedicated_browser", return_value=9333), \
                mock.patch.object(runner, "check_douyin_login_state", return_value="logged_in"), \
                mock.patch.object(runner, "snapshot_cdp_page_ids", return_value=[]), \
                mock.patch.object(runner, "close_leaked_pages", return_value=None), \
                mock.patch.object(runner, "run_mediacrawler", side_effect=collect):
            yield

    @staticmethod
    def make_crawler_root(tmp):
        crawler = Path(tmp) / "crawler"
        jsonl_dir = crawler / "output" / "douyin" / "jsonl"
        jsonl_dir.mkdir(parents=True)
        (crawler / "main.py").write_text("", encoding="utf-8")
        jsonl = jsonl_dir / "creator_contents_2026-08-08.jsonl"
        jsonl.write_text("", encoding="utf-8")
        return crawler, jsonl

    def test_main_publishes_when_some_creators_are_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler, jsonl = self.make_crawler_root(tmp)
            result_file = Path(tmp) / "result.json"

            def collect(_root, _port, _platform, _creator, _max_notes, observer=None):
                self.record_of(observer, "c1", profile_valid=True, api_pages_valid=True, listed_count=2, written_rows=2)
                self.record_of(observer, "c2", profile_valid=True, api_pages_valid=True, listed_count=3, written_rows=2)
                self.record_of(observer, "c3", profile_valid=False, api_pages_valid=False)
                with jsonl.open("a", encoding="utf-8") as handle:
                    for index in range(4):
                        handle.write(json.dumps({"aweme_id": f"row-{index}"}) + "\n")
                return 0

            args = self.collect_args(crawler, result_file=str(result_file))
            with self.patched_main(args, collect):
                self.assertEqual(runner.main(), 0, "有号采到内容时必须发布，不能整轮作废")

            payload = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["partial"])
            self.assertEqual(payload["missing_rows"], 1)
            self.assertEqual(payload["completed_creator_count"], 1)
            self.assertEqual(payload["partial_creator_count"], 1)
            self.assertEqual(payload["failed_creator_count"], 1)
            self.assertEqual(payload["crawl_output_rows"], 4)

    def test_main_still_fails_when_no_creator_produced_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            crawler, _jsonl = self.make_crawler_root(tmp)
            result_file = Path(tmp) / "result.json"

            def collect(_root, _port, _platform, _creator, _max_notes, observer=None):
                for creator_id in ("c1", "c2", "c3"):
                    observer.fail(creator_id, "Blocked by ArgusSecurityPlugin Validate Error")
                return 0

            args = self.collect_args(crawler, result_file=str(result_file))
            with self.patched_main(args, collect):
                self.assertEqual(runner.main(), 1, "一个号都没采到时必须保持失败，不能发空快照")

            payload = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["completed_creator_count"], 0)
            self.assertEqual(payload["partial_creator_count"], 0)
            for text in [payload["error"], *payload["warnings"]]:
                self.assertNotIn("SECRET_BODY", str(text))


if __name__ == "__main__":
    unittest.main()
