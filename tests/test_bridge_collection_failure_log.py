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


PARTIAL_RUNNER = r'''
import argparse, hashlib, json
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

rows = int(scenario["rows"])
source_file = ""
source_sha256 = ""
if rows:
    jsonl_dir = Path(a.crawler_root) / "output" / "douyin" / "jsonl"
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    jsonl = jsonl_dir / "creator_contents_2026-08-08.jsonl"
    jsonl.write_text("".join(json.dumps({"aweme_id": "row-%d" % i}) + "\n" for i in range(rows)), encoding="utf-8")
    source_file = str(jsonl)
    source_sha256 = hashlib.sha256(jsonl.read_bytes()).hexdigest()

receipts = scenario["creator_results"]
result = {
    "run_id": a.run_id,
    "ok": True,
    "login_state": "valid",
    "source_file": source_file,
    "source_last_write_time": None,
    "source_sha256": source_sha256,
    "output_rows": rows,
    "crawl_output_rows": rows,
    "new_unique_items": rows,
    "requested_creator_count": len(receipts),
    "completed_creator_count": sum(1 for r in receipts if r["state"] == "completed"),
    "partial_creator_count": sum(1 for r in receipts if r["state"] == "partial"),
    "failed_creator_count": sum(1 for r in receipts if r["state"] == "failed"),
    "missing_rows": sum(int(r.get("missing_rows") or 0) for r in receipts),
    "partial": any(r["state"] != "completed" for r in receipts) and rows > 0,
    "creator_results": receipts,
    "ambiguous": False,
    "warnings": scenario.get("warnings", []),
    "error": "",
}
Path(a.result_file).write_text(json.dumps(result), encoding="utf-8")
raise SystemExit(0)
'''.strip() + "\n"


def receipt(state: str, listed: int, written: int, sec_uid: str) -> dict:
    return {
        "sec_uid": sec_uid,
        "state": state,
        "profile_valid": state != "failed",
        "api_pages_valid": state != "failed",
        "listed_count": listed,
        "written_rows": written,
        "missing_rows": max(0, listed - written),
        "error": "" if state == "completed" else "douyin_risk_control",
    }


def build_partial_fixture(tmp_path: Path):
    """搭一套「假 runner + 真 .ps1 + 真 git 桥接仓库」的夹具，供部分完成场景使用。"""
    repo_root = Path(__file__).resolve().parent.parent
    radar_root = tmp_path / "radar"
    crawler_root = tmp_path / "MediaCrawler"
    bridge_root = tmp_path / "douyin-bridge"
    bare_root = tmp_path / "douyin-bridge.git"
    (radar_root / "scripts").mkdir(parents=True)
    crawler_root.mkdir()
    bridge_root.mkdir()
    (crawler_root / "main.py").write_text("# fake crawler\n", encoding="utf-8")
    (radar_root / "scripts" / "run_mediacrawler_douyin.py").write_text(PARTIAL_RUNNER, encoding="utf-8")

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

    script = repo_root / "deploy" / "cloud-pc" / "collect-douyin-and-push.ps1"
    creator_ids = ",".join(f"creator-{index}" for index in range(1, 7))
    command = [
        POWERSHELL_EXE, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
        "-RadarRoot", str(radar_root), "-CrawlerRoot", str(crawler_root),
        "-BridgeRoot", str(bridge_root), "-PythonExe", sys.executable,
        "-CreatorIds", creator_ids, "-SkipGitPull",
    ]
    return radar_root, bridge_root, command


def test_partial_collection_still_publishes_and_is_recorded(tmp_path: Path) -> None:
    """TASK-05a：一个号被风控只采到一半时，已采到的必须照常发布，并留下可见的缺失记录。

    这是 BUG-02 的核心诉求（用户 2026-08-08 拍板「不管采集了多少，都同步到 AI 看板」）。
    改动前：6 个号里任意 1 个不完整 → 整轮 state=failed、桥接 HEAD 不动、47~51 条被丢弃。
    """
    radar_root, bridge_root, command = build_partial_fixture(tmp_path)
    head_before = run_git(bridge_root, "rev-parse", "HEAD")

    (radar_root / "runner-scenario.json").write_text(
        json.dumps(
            {
                "rows": 41,
                "creator_results": [
                    receipt("completed", 10, 10, "creator-1"),
                    receipt("completed", 10, 10, "creator-2"),
                    receipt("completed", 10, 10, "creator-3"),
                    receipt("completed", 8, 8, "creator-4"),
                    receipt("partial", 10, 3, "creator-5"),
                    receipt("failed", 0, 0, "creator-6"),
                ],
                # 假 runner 故意带一段含响应体的告警，验证 PS 侧不会把它抄进留痕日志。
                "warnings": ["Expecting value: line 1 column 1 (char 0), <html>SECRET_BODY</html>"],
            }
        ),
        encoding="utf-8",
    )

    status_path = tmp_path / "partial-status.json"
    result = subprocess.run(
        [*command, "-StatusFile", str(status_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    status = json.loads(status_path.read_text(encoding="utf-8-sig"))
    assert status["state"] == "succeeded", status
    assert status["bridge_changed"] is True, "部分完成时桥接必须真的更新"
    assert run_git(bridge_root, "rev-parse", "HEAD") != head_before, "桥接 HEAD 必须前进"

    manifest = json.loads((bridge_root / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["schema_version"] == 2
    assert manifest["partial"] is True
    assert manifest["missing_rows"] == 7
    assert manifest["completed_creator_count"] == 4
    assert manifest["partial_creator_count"] == 1
    assert manifest["failed_creator_count"] == 1

    failure_log = radar_root / "logs" / "bridge-collection-failures.jsonl"
    records = [json.loads(line) for line in failure_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    matches = [record for record in records if record["run_id"] == status["run_id"]]
    assert len(matches) == 1, "缺失必须留痕，且按 run_id 去重只留一条"
    assert matches[0]["channel"] == "douyin"
    assert matches[0]["state"] == "warning"
    assert set(matches[0]) == {
        "recorded_at", "channel", "run_id", "state", "stage", "message",
        "exit_code", "login_state", "started_at", "finished_at",
    }
    assert "SECRET_BODY" not in matches[0]["message"]
    assert "<html>" not in matches[0]["message"]
    assert len(matches[0]["message"]) <= 512
    print(
        f"douyin partial publish returncode={result.returncode} "
        f"missing={manifest['missing_rows']} stage={matches[0]['stage']}"
    )


def test_fully_completed_collection_leaves_no_failure_record(tmp_path: Path) -> None:
    """全采全时不得留痕，也不得把 manifest 标成 partial——否则看板会永远挂黄标。"""
    radar_root, bridge_root, command = build_partial_fixture(tmp_path)

    (radar_root / "runner-scenario.json").write_text(
        json.dumps(
            {
                "rows": 52,
                "creator_results": [receipt("completed", 10, 10, f"creator-{index}") for index in range(1, 7)],
            }
        ),
        encoding="utf-8",
    )

    status_path = tmp_path / "healthy-status.json"
    result = subprocess.run(
        [*command, "-StatusFile", str(status_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    status = json.loads(status_path.read_text(encoding="utf-8-sig"))
    assert status["state"] == "succeeded"

    manifest = json.loads((bridge_root / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["schema_version"] == 2
    assert manifest["partial"] is False
    assert manifest["missing_rows"] == 0

    failure_log = radar_root / "logs" / "bridge-collection-failures.jsonl"
    if failure_log.exists():
        records = [json.loads(line) for line in failure_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert not [record for record in records if record["run_id"] == status["run_id"]]


def test_all_creators_failed_does_not_publish(tmp_path: Path) -> None:
    """fail-safe：一个号都没采到时绝不发布，桥接 HEAD 必须原地不动。"""
    radar_root, bridge_root, command = build_partial_fixture(tmp_path)
    head_before = run_git(bridge_root, "rev-parse", "HEAD")

    (radar_root / "runner-scenario.json").write_text(
        json.dumps(
            {
                "rows": 0,
                "creator_results": [receipt("failed", 0, 0, f"creator-{index}") for index in range(1, 7)],
            }
        ),
        encoding="utf-8",
    )

    status_path = tmp_path / "dead-status.json"
    result = subprocess.run(
        [*command, "-StatusFile", str(status_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert run_git(bridge_root, "rev-parse", "HEAD") == head_before
    assert run_git(bridge_root, "status", "--porcelain") == ""


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
