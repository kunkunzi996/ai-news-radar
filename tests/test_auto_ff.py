import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class GitScriptFixtureMixin:
    @staticmethod
    def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=check,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="ai-news-radar-auto-ff-")
        self.base = Path(self.temp_dir.name)
        self.root, self.origin, self.peer = self.create_git_fixture()
        self.script = Path(__file__).resolve().parents[1] / "scripts" / "windows" / "auto-ff.sh"
        self.bash = self.find_bash()

    def tearDown(self):
        self.temp_dir.cleanup()

    def find_bash(self) -> str:
        candidates = [shutil.which("bash")]
        candidates.extend(
            str(path)
            for path in (
                Path(os.environ.get("ProgramFiles", "")) / "Git" / "bin" / "bash.exe",
                Path("E:/Program Files/Git/bin/bash.exe"),
                Path("C:/Program Files/Git/bin/bash.exe"),
            )
            if str(path) != "."
        )
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        self.skipTest("未找到 Git Bash，无法执行 auto-ff.sh")

    def create_git_fixture(self):
        origin = self.base / "origin.git"
        root = self.base / "root"
        peer = self.base / "peer"
        self.git(self.base, "init", "--bare", str(origin))
        root.mkdir()
        self.git(root, "init", "-b", "master")
        self.git(root, "config", "user.name", "Test")
        self.git(root, "config", "user.email", "test@example.com")
        (root / "state.txt").write_text("initial\n", encoding="utf-8")
        self.git(root, "add", "state.txt")
        self.git(root, "commit", "-m", "initial")
        self.git(root, "remote", "add", "origin", str(origin))
        self.git(root, "push", "-u", "origin", "master")
        self.git(self.base, "clone", str(origin), str(peer))
        self.git(peer, "config", "user.name", "Test")
        self.git(peer, "config", "user.email", "test@example.com")
        return root, origin, peer



class AutoFastForwardScriptTests(GitScriptFixtureMixin, unittest.TestCase):
    def run_script(self) -> str:
        log_path = self.base / "logs" / "auto-ff.log"
        env = os.environ.copy()
        env["RADAR_ROOT"] = self.root.as_posix()
        env["RADAR_AUTO_FF_LOG"] = log_path.as_posix()
        result = subprocess.run(
            [self.bash, self.script.as_posix()],
            cwd=self.root,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return log_path.read_text(encoding="utf-8")

    def test_fast_forward_success_records_old_and_new_head(self):
        old_head = self.git(self.root, "rev-parse", "HEAD").stdout.strip()
        (self.peer / "state.txt").write_text("remote\n", encoding="utf-8")
        self.git(self.peer, "add", "state.txt")
        self.git(self.peer, "commit", "-m", "remote update")
        self.git(self.peer, "push")

        log = self.run_script()
        new_head = self.git(self.root, "rev-parse", "HEAD").stdout.strip()

        self.assertNotEqual(new_head, old_head)
        self.assertIn("event=ff-ok command=merge_ff_only reason=fast_forwarded exit=0", log)
        self.assertRegex(log, r"duration_ms=[0-9]+")
        self.assertIn(f"old_head={old_head}", log)
        self.assertIn(f"new_head={new_head}", log)

    def test_dirty_worktree_records_worktree_dirty_reason(self):
        (self.peer / "state.txt").write_text("remote\n", encoding="utf-8")
        self.git(self.peer, "add", "state.txt")
        self.git(self.peer, "commit", "-m", "remote update")
        self.git(self.peer, "push")
        (self.root / "state.txt").write_text("local dirty\n", encoding="utf-8")

        log = self.run_script()

        self.assertIn("event=failed command=merge_ff_only reason=worktree_dirty", log)
        self.assertIn("exit=1", log)
        self.assertEqual((self.root / "state.txt").read_text(encoding="utf-8"), "local dirty\n")

    def test_non_fast_forward_records_remote_diverged_reason(self):
        (self.peer / "state.txt").write_text("remote\n", encoding="utf-8")
        self.git(self.peer, "add", "state.txt")
        self.git(self.peer, "commit", "-m", "remote update")
        self.git(self.peer, "push")
        (self.root / "local.txt").write_text("local\n", encoding="utf-8")
        self.git(self.root, "add", "local.txt")
        self.git(self.root, "commit", "-m", "local divergence")

        log = self.run_script()

        self.assertIn("event=failed command=merge_ff_only reason=remote_diverged", log)
        self.assertIn("exit=1", log)

    def test_fetch_failure_records_fetch_reason_and_exit_code(self):
        missing_origin = self.base / "missing-origin.git"
        self.git(self.root, "remote", "set-url", "origin", str(missing_origin))

        log = self.run_script()

        self.assertIn("event=failed command=fetch_origin reason=fetch_failed", log)
        self.assertRegex(log, r"exit=[1-9][0-9]*")

    def test_three_consecutive_failures_raise_alert_and_run_alert_command(self):
        (self.peer / "state.txt").write_text("remote\n", encoding="utf-8")
        self.git(self.peer, "add", "state.txt")
        self.git(self.peer, "commit", "-m", "remote update")
        self.git(self.peer, "push")
        (self.root / "state.txt").write_text("local dirty\n", encoding="utf-8")
        marker = self.base / "alert-fired.txt"
        os.environ["RADAR_AUTO_FF_ALERT_COMMAND"] = (
            f'printf "%s %s" "$RADAR_AUTO_FF_ALERT_REASON" "$RADAR_AUTO_FF_ALERT_STREAK" > "{marker.as_posix()}"'
        )
        self.addCleanup(os.environ.pop, "RADAR_AUTO_FF_ALERT_COMMAND", None)

        self.run_script()
        self.run_script()
        self.assertFalse(marker.exists(), "两次失败还不该报警")
        log = self.run_script()

        self.assertEqual(log.count("event=alert"), 1)
        self.assertIn("event=alert command=auto_ff reason=worktree_dirty", log)
        self.assertIn("detail=consecutive_failures=3", log)
        self.assertEqual(marker.read_text(encoding="utf-8"), "worktree_dirty 3")
        self.assertEqual((self.root / "state.txt").read_text(encoding="utf-8"), "local dirty\n")

    def test_success_after_failures_does_not_alert(self):
        (self.peer / "state.txt").write_text("remote\n", encoding="utf-8")
        self.git(self.peer, "add", "state.txt")
        self.git(self.peer, "commit", "-m", "remote update")
        self.git(self.peer, "push")
        (self.root / "state.txt").write_text("local dirty\n", encoding="utf-8")
        self.run_script()
        self.run_script()
        (self.root / "state.txt").write_text("initial\n", encoding="utf-8")

        log = self.run_script()

        self.assertIn("event=ff-ok", log)
        self.assertNotIn("event=alert", log)


class FreshnessCheckScriptTests(GitScriptFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.script = Path(__file__).resolve().parents[1] / "scripts" / "windows" / "check-radar-freshness.sh"

    def write_data(self, root: Path, generated_at: str) -> None:
        path = root / "data" / "latest-24h-all.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text('{"generated_at":"%s","items_all":[]}' % generated_at, encoding="utf-8")

    def run_freshness(self) -> str:
        log_path = self.base / "logs" / "freshness.log"
        env = os.environ.copy()
        env["RADAR_ROOT"] = self.root.as_posix()
        env["RADAR_FRESHNESS_LOG"] = log_path.as_posix()
        result = subprocess.run(
            [self.bash, self.script.as_posix()],
            cwd=self.root,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return log_path.read_text(encoding="utf-8")

    def test_fresh_snapshot_logs_fresh(self):
        from datetime import datetime, timedelta, timezone

        recent = (datetime.now(timezone.utc) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.write_data(self.root, recent)
        self.git(self.root, "add", "data/latest-24h-all.json")
        self.git(self.root, "commit", "-m", "data")
        self.git(self.root, "push")

        log = self.run_freshness()

        self.assertIn("event=fresh", log)
        self.assertIn(f"local={recent}", log)
        self.assertIn("behind_remote_minutes=0", log)

    def test_nuc_behind_cloud_logs_stale_with_reason(self):
        from datetime import datetime, timedelta, timezone

        old = (datetime.now(timezone.utc) - timedelta(hours=13)).strftime("%Y-%m-%dT%H:%M:%SZ")
        new = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.write_data(self.root, old)
        self.git(self.root, "add", "data/latest-24h-all.json")
        self.git(self.root, "commit", "-m", "old data")
        self.git(self.root, "push")
        self.git(self.peer, "pull", "--ff-only")
        self.write_data(self.peer, new)
        self.git(self.peer, "add", "data/latest-24h-all.json")
        self.git(self.peer, "commit", "-m", "cloud data")
        self.git(self.peer, "push")
        marker = self.base / "stale-fired.txt"
        os.environ["RADAR_FRESHNESS_ALERT_COMMAND"] = f'printf "%s" "$RADAR_FRESHNESS_DETAIL" > "{marker.as_posix()}"'
        self.addCleanup(os.environ.pop, "RADAR_FRESHNESS_ALERT_COMMAND", None)

        log = self.run_freshness()

        self.assertIn("event=stale", log)
        self.assertIn("detail=nuc_behind_cloud", log)
        self.assertRegex(log, r"lag_minutes=7[0-9]{2}")
        self.assertEqual(marker.read_text(encoding="utf-8"), "nuc_behind_cloud")


if __name__ == "__main__":
    unittest.main()
