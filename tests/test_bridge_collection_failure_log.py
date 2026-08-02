from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


POWERSHELL_EXE = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="requires Windows PowerShell 5.1",
)


def run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    )
    return result.stdout.strip()


def test_douyin_login_failure_is_recorded_and_success_is_silent(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    radar_root = tmp_path / "radar"
    crawler_root = tmp_path / "MediaCrawler"
    bridge_root = tmp_path / "douyin-bridge"
    bare_root = tmp_path / "douyin-bridge.git"
    (radar_root / "scripts").mkdir(parents=True)
    crawler_root.mkdir()
    bridge_root.mkdir()
    (crawler_root / "main.py").write_text("# fake crawler\n", encoding="utf-8")

    runner = r'''
import argparse, json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--crawler-root")
p.add_argument("--platform")
p.add_argument("--creator-id")
p.add_argument("--max-notes")
p.add_argument("--run-id", required=True)
p.add_argument("--result-file", required=True)
p.add_argument("--parent-holds-collection-lock", action="store_true")
p.add_argument("--offscreen", action="store_true")
a = p.parse_args()
scenario = json.loads((Path(__file__).resolve().parents[1] / "runner-scenario.json").read_text(encoding="utf-8"))
result = {
    "run_id": a.run_id,
    "login_state": scenario["login_state"],
    "source_file": "",
    "source_last_write_time": None,
    "source_sha256": "",
    "output_rows": 0,
    "crawl_output_rows": 0,
    "new_unique_items": 0,
    "requested_creator_count": 1,
    "completed_creator_count": 1,
    "failed_creator_count": 0,
    "creator_results": [{
        "state": "completed",
        "profile_valid": True,
        "api_pages_valid": True,
        "written_rows": 0,
        "listed_count": 0,
    }],
    "warnings": [],
}
Path(a.result_file).write_text(json.dumps(result), encoding="utf-8")
raise SystemExit(int(scenario["exit_code"]))
'''.strip() + "\n"
    (radar_root / "scripts" / "run_mediacrawler_douyin.py").write_text(runner, encoding="utf-8")
    (radar_root / "runner-scenario.json").write_text(
        json.dumps({"login_state": "login_required", "exit_code": 1}), encoding="utf-8"
    )

    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(bare_root)],
        check=True, capture_output=True,
    )
    run_git(bridge_root, "init", "-b", "main")
    run_git(bridge_root, "config", "user.name", "test")
    run_git(bridge_root, "config", "user.email", "test@example.com")
    (bridge_root / "manifest.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    run_git(bridge_root, "add", ".")
    run_git(bridge_root, "commit", "-m", "initial bridge")
    run_git(bridge_root, "remote", "add", "origin", str(bare_root))
    run_git(bridge_root, "push", "-u", "origin", "main")
    initial_head = run_git(bridge_root, "rev-parse", "HEAD")

    script = repo_root / "deploy" / "cloud-pc" / "collect-douyin-and-push.ps1"
    status_path = tmp_path / "failed-status.json"
    command = [
        POWERSHELL_EXE, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
        "-RadarRoot", str(radar_root), "-CrawlerRoot", str(crawler_root),
        "-BridgeRoot", str(bridge_root), "-PythonExe", sys.executable,
        "-CreatorIds", "creator-1", "-SkipGitPull", "-StatusFile", str(status_path),
    ]
    failed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    status = json.loads(status_path.read_text(encoding="utf-8-sig"))
    assert status["state"] == "failed"
    assert status["stage"] == "login_required"
    assert status["login_state"] == "login_required"
    assert status["exit_code"] == 1
    assert run_git(bridge_root, "rev-parse", "HEAD") == initial_head
    assert run_git(bridge_root, "status", "--porcelain") == ""

    failure_log = radar_root / "logs" / "bridge-collection-failures.jsonl"
    records = [json.loads(line) for line in failure_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    matches = [record for record in records if record["run_id"] == status["run_id"]]
    assert len(matches) == 1
    assert matches[0]["channel"] == "douyin"
    assert matches[0]["stage"] == "login_required"
    assert matches[0]["login_state"] == "login_required"
    print(
        f"douyin failure returncode={failed.returncode} channel={matches[0]['channel']} "
        f"run_id={status['run_id']} stage={matches[0]['stage']}"
    )
    assert set(matches[0]) == {
        "recorded_at", "channel", "run_id", "state", "stage", "message",
        "exit_code", "login_state", "started_at", "finished_at",
    }

    (radar_root / "runner-scenario.json").write_text(
        json.dumps({"login_state": "valid", "exit_code": 0}), encoding="utf-8"
    )
    success_status_path = tmp_path / "success-status.json"
    success = subprocess.run(
        [*command[:-1], str(success_status_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    assert success.returncode == 0, success.stdout + success.stderr
    success_status = json.loads(success_status_path.read_text(encoding="utf-8-sig"))
    assert success_status["state"] == "succeeded"
    assert success_status["login_state"] == "valid"
    print(f"douyin recovery returncode={success.returncode} failure_records={len(records)}")
    records_after_success = [
        json.loads(line) for line in failure_log.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert records_after_success == records
    assert run_git(bridge_root, "rev-parse", "HEAD") == initial_head
    assert run_git(bridge_root, "status", "--porcelain") == ""

    (radar_root / "runner-scenario.json").write_text(
        json.dumps({"login_state": "invalid", "exit_code": 0}), encoding="utf-8"
    )
    invalid_status_path = tmp_path / "invalid-status.json"
    invalid_login = subprocess.run(
        [*command[:-1], str(invalid_status_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    assert invalid_login.returncode == 0, invalid_login.stdout + invalid_login.stderr
    invalid_status = json.loads(invalid_status_path.read_text(encoding="utf-8-sig"))
    assert invalid_status["state"] == "succeeded"
    assert invalid_status["login_state"] == "invalid"
    records_after_invalid = [
        json.loads(line) for line in failure_log.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    invalid_matches = [record for record in records_after_invalid if record["run_id"] == invalid_status["run_id"]]
    assert len(invalid_matches) == 1
    assert invalid_matches[0]["channel"] == "douyin"
    assert invalid_matches[0]["login_state"] == "invalid"
