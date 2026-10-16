import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.windows.nudge_snapshot import decide, nudge, redact


NOW = datetime(2026, 10, 16, 2, 30, tzinfo=timezone.utc)


def run(created_at: datetime, status: str = "completed", conclusion: str = "success") -> dict:
    return {
        "status": status,
        "conclusion": conclusion,
        "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


class DecideTests(unittest.TestCase):
    def test_fresh_success_is_left_alone(self):
        action, reason, age = decide([run(NOW - timedelta(minutes=10))], NOW, 40)
        self.assertEqual((action, reason, age), ("skip", "fresh", 10))

    def test_stale_success_asks_for_a_run(self):
        action, reason, age = decide([run(NOW - timedelta(minutes=50))], NOW, 40)
        self.assertEqual((action, reason, age), ("dispatch", "stale", 50))

    def test_in_progress_is_not_interrupted(self):
        runs = [
            run(NOW - timedelta(minutes=2), status="in_progress", conclusion=""),
            run(NOW - timedelta(minutes=80)),
        ]
        action, reason, _age = decide(runs, NOW, 40)
        self.assertEqual((action, reason), ("skip", "already_running"))

    def test_no_history_asks_for_a_run(self):
        action, reason, age = decide([], NOW, 40)
        self.assertEqual((action, reason, age), ("dispatch", "no_success", None))


class NudgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nudge-snapshot-")
        self.log = Path(self.temp.name) / "nudge.log"
        self._old = os.environ.get("RADAR_NUDGE_LOG")
        os.environ["RADAR_NUDGE_LOG"] = str(self.log)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("RADAR_NUDGE_LOG", None)
        else:
            os.environ["RADAR_NUDGE_LOG"] = self._old
        self.temp.cleanup()

    def test_missing_token_does_not_call_github(self):
        called = []

        def request(method, url, token, body):
            called.append(method)
            return 200, "{}"

        event, reason = nudge(NOW, "", request)
        self.assertEqual((event, reason), ("failed", "token_missing"))
        self.assertEqual(called, [])
        self.assertIn("reason=token_missing", self.log.read_text(encoding="utf-8"))

    def test_disabled_fork_is_an_alert(self):
        def request(method, url, token, body):
            if method == "GET":
                payload = {"workflow_runs": [run(NOW - timedelta(minutes=90))]}
                return 200, json.dumps(payload)
            return 422, '{"message":"Actions has been disabled for this repository."}'

        event, reason = nudge(NOW, "test-token", request)
        self.assertEqual((event, reason), ("alert", "actions_disabled"))
        text = self.log.read_text(encoding="utf-8")
        self.assertIn("event=alert", text)
        self.assertIn("reason=actions_disabled", text)
        self.assertNotIn("test-token", text)

    def test_stale_success_dispatches_once(self):
        calls = []

        def request(method, url, token, body):
            calls.append((method, body))
            if method == "GET":
                payload = {"workflow_runs": [run(NOW - timedelta(minutes=70))]}
                return 200, json.dumps(payload)
            return 204, ""

        event, reason = nudge(NOW, "test-token", request)
        self.assertEqual((event, reason), ("dispatched", "stale"))
        self.assertEqual(calls[1][0], "POST")
        self.assertEqual(calls[1][1], {"ref": "master"})

    def test_redact_hides_token_shapes(self):
        self.assertNotIn("gho_secret", redact("failed gho_secret more"))
        self.assertIn("<redacted>", redact("failed gho_secret more"))


if __name__ == "__main__":
    unittest.main()
