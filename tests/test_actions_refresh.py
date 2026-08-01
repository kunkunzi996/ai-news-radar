import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.radar.server import actions_refresh


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f0Z")


class ParseTimeTests(unittest.TestCase):
    def test_parses_powershell_round_trip_format(self):
        parsed = actions_refresh._parse_time("2026-08-01T06:26:39.0974360Z")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, timezone.utc)

    def test_returns_none_for_blank_or_bad_values(self):
        self.assertIsNone(actions_refresh._parse_time(None))
        self.assertIsNone(actions_refresh._parse_time(""))
        self.assertIsNone(actions_refresh._parse_time("not-a-time"))


class WaitForCollectFinishTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # 状态文件在仓库的父目录，所以 root 必须是子目录。
        self.parent = Path(self._tmp.name)
        self.root = self.parent / "ai-news-radar-run"
        self.root.mkdir()
        self.addCleanup(self._tmp.cleanup)
        self.since = datetime(2026, 8, 1, 6, 0, 0, tzinfo=timezone.utc)

    def write_status(self, filename, *, started, finished=None, state="running"):
        payload = {
            "state": state,
            "started_at": iso(started) if started else None,
            "finished_at": iso(finished) if finished else None,
        }
        (self.parent / filename).write_text(json.dumps(payload), encoding="utf-8")

    def test_returns_when_channel_finished(self):
        self.write_status(
            actions_refresh.DOUYIN_STATUS_FILENAME,
            started=self.since + timedelta(seconds=2),
            finished=self.since + timedelta(minutes=3),
            state="completed",
        )
        result = actions_refresh.wait_for_collect_finish(
            self.root, self.since, timeout_seconds=60, sleep=lambda _s: None
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["channels"]["douyin"]["state"], "completed")

    def test_stale_status_from_previous_round_is_ignored(self):
        # 上一轮的状态文件（早于本次触发）不能被当成本轮已完成。
        self.write_status(
            actions_refresh.DOUYIN_STATUS_FILENAME,
            started=self.since - timedelta(hours=2),
            finished=self.since - timedelta(hours=1),
            state="completed",
        )
        result = actions_refresh.wait_for_collect_finish(
            self.root, self.since, timeout_seconds=0, sleep=lambda _s: None
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["channels"], {})

    def test_waits_while_a_channel_is_still_running(self):
        # 抖音已完成但微信仍在跑：整轮未结束，不能提前触发刷新。
        self.write_status(
            actions_refresh.DOUYIN_STATUS_FILENAME,
            started=self.since + timedelta(seconds=1),
            finished=self.since + timedelta(minutes=2),
            state="completed",
        )
        self.write_status(
            actions_refresh.WECHAT_STATUS_FILENAME,
            started=self.since + timedelta(minutes=2),
            finished=None,
        )
        result = actions_refresh.wait_for_collect_finish(
            self.root, self.since, timeout_seconds=0, sleep=lambda _s: None
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])

    def test_both_channels_finished(self):
        self.write_status(
            actions_refresh.DOUYIN_STATUS_FILENAME,
            started=self.since + timedelta(seconds=1),
            finished=self.since + timedelta(minutes=2),
            state="completed",
        )
        self.write_status(
            actions_refresh.WECHAT_STATUS_FILENAME,
            started=self.since + timedelta(minutes=2),
            finished=self.since + timedelta(minutes=3),
            state="warning",
        )
        result = actions_refresh.wait_for_collect_finish(
            self.root, self.since, timeout_seconds=60, sleep=lambda _s: None
        )
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["channels"]), {"douyin", "wechat"})

    def test_missing_status_files_time_out(self):
        result = actions_refresh.wait_for_collect_finish(
            self.root, self.since, timeout_seconds=0, sleep=lambda _s: None
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])


class PushRefreshMarkerTests(unittest.TestCase):
    def test_missing_pat_is_reported_not_raised(self):
        with patch.object(actions_refresh, "read_pat", return_value=""):
            result = actions_refresh.push_refresh_marker({"a": 1})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "pat_not_available")

    def test_update_sends_sha_when_file_exists(self):
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200, json=lambda: {"sha": "abc123"})
        session.put.return_value = MagicMock(
            status_code=200, json=lambda: {"commit": {"sha": "def456"}}
        )
        with patch.object(actions_refresh, "read_pat", return_value="token"):
            result = actions_refresh.push_refresh_marker({"a": 1}, session=session)
        self.assertTrue(result["ok"])
        self.assertEqual(result["commit"], "def456")
        self.assertEqual(session.put.call_args.kwargs["json"]["sha"], "abc123")
        self.assertEqual(
            session.put.call_args.kwargs["json"]["message"],
            actions_refresh.REFRESH_COMMIT_MESSAGE,
        )

    def test_create_omits_sha_when_file_absent(self):
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=404, json=lambda: {})
        session.put.return_value = MagicMock(status_code=201, json=lambda: {"commit": {"sha": "new1"}})
        with patch.object(actions_refresh, "read_pat", return_value="token"):
            result = actions_refresh.push_refresh_marker({"a": 1}, session=session)
        self.assertTrue(result["ok"])
        self.assertNotIn("sha", session.put.call_args.kwargs["json"])

    def test_http_error_is_reported_not_raised(self):
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=404, json=lambda: {})
        session.put.return_value = MagicMock(status_code=403, json=lambda: {}, text="forbidden")
        with patch.object(actions_refresh, "read_pat", return_value="token"):
            result = actions_refresh.push_refresh_marker({"a": 1}, session=session)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "http_403")

    def test_network_exception_is_swallowed(self):
        session = MagicMock()
        session.get.side_effect = RuntimeError("network down")
        with patch.object(actions_refresh, "read_pat", return_value="token"):
            result = actions_refresh.push_refresh_marker({"a": 1}, session=session)
        self.assertFalse(result["ok"])
        self.assertIn("network down", result["error"])

    def test_marker_path_is_outside_paths_ignore(self):
        # data/** 被 workflow 的 paths-ignore 忽略；标记文件必须留在仓库根才能触发。
        self.assertFalse(actions_refresh.REFRESH_MARKER_PATH.startswith("data/"))


class WaitThenRefreshTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self._tmp.name)
        self.root = self.parent / "ai-news-radar-run"
        self.root.mkdir()
        self.addCleanup(self._tmp.cleanup)
        self.since = datetime(2026, 8, 1, 6, 0, 0, tzinfo=timezone.utc)

    def test_timeout_records_status_and_skips_push(self):
        with patch.object(actions_refresh, "push_refresh_marker") as push:
            entry = actions_refresh.wait_then_refresh(
                self.root, self.since, {"added_names": ["X"]},
                timeout_seconds=0, sleep=lambda _s: None,
            )
        push.assert_not_called()
        self.assertFalse(entry["ok"])
        self.assertEqual(entry["error"], "collect_wait_timeout")
        saved = json.loads(actions_refresh.status_path(self.root).read_text(encoding="utf-8"))
        self.assertEqual(len(saved["runs"]), 1)

    def test_successful_flow_pushes_marker_with_reason(self):
        payload = {
            "state": "completed",
            "started_at": iso(self.since + timedelta(seconds=1)),
            "finished_at": iso(self.since + timedelta(minutes=1)),
        }
        (self.parent / actions_refresh.DOUYIN_STATUS_FILENAME).write_text(
            json.dumps(payload), encoding="utf-8"
        )
        with patch.object(
            actions_refresh, "push_refresh_marker", return_value={"ok": True, "commit": "c1"}
        ) as push:
            entry = actions_refresh.wait_then_refresh(
                self.root, self.since, {"added_names": ["Game AI Lab"]},
                timeout_seconds=60, sleep=lambda _s: None,
            )
        self.assertTrue(entry["ok"])
        marker = push.call_args[0][0]
        self.assertEqual(marker["reason"]["added_names"], ["Game AI Lab"])
        self.assertIn("douyin", marker["collect"])

    def test_unexpected_exception_is_swallowed(self):
        with patch.object(
            actions_refresh, "wait_for_collect_finish", side_effect=RuntimeError("boom")
        ):
            entry = actions_refresh.wait_then_refresh(
                self.root, self.since, {}, timeout_seconds=1, sleep=lambda _s: None
            )
        self.assertFalse(entry["ok"])
        self.assertIn("boom", entry["error"])


if __name__ == "__main__":
    unittest.main()
