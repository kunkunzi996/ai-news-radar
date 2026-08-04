import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class AutoFastForwardScriptTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
