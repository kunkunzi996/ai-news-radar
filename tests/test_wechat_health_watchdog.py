from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


IS_WINDOWS = os.name == "nt"
POWERSHELL_EXE = shutil.which("powershell.exe") if IS_WINDOWS else None

pytestmark = pytest.mark.skipif(
    not IS_WINDOWS or POWERSHELL_EXE is None,
    reason="requires Windows PowerShell 5.1",
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "local" / "wechat-health-watchdog.ps1"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _verdict(
    decision: str,
    reason: str,
    *,
    title: str = "测试标题",
    message: str = "测试消息",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "decision": decision,
        "reason": reason,
        "title": title,
        "message": message,
        "active_feed_count": 1,
        "stale_feed_count": 0,
        "latest_success_epoch": 1,
        "checked_at": "2026-07-19T00:00:00Z",
    }


def _prepare(tmp_path: Path, *, response_status: int = 200, nickname: str = "测试昵称猫") -> dict[str, Path]:
    fixture = tmp_path / "probe.json"
    secret = tmp_path / "meow.json"
    state = tmp_path / "incident-state.json"
    run_status = tmp_path / "run-status.json"
    sink = tmp_path / "push-sink.jsonl"
    log = tmp_path / "watchdog.log"
    _write_json(secret, {"nickname": nickname, "test_response_status": response_status})
    return {
        "fixture": fixture,
        "secret": secret,
        "state": state,
        "run_status": run_status,
        "sink": sink,
        "log": log,
    }


def _events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line]


def _run(
    paths: dict[str, Path],
    *,
    python_exe: str | None = None,
    db_path: Path | None = None,
    status_path: Path | None = None,
    include_radar_root: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [
        str(POWERSHELL_EXE),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        "-SecretFile",
        str(paths["secret"]),
        "-StateFile",
        str(paths["state"]),
        "-RunStatusFile",
        str(paths["run_status"]),
        "-LogFile",
        str(paths["log"]),
        "-PushSinkFile",
        str(paths["sink"]),
    ]
    if include_radar_root:
        command.extend(["-RadarRoot", str(ROOT)])
    if db_path is not None:
        command.extend(["-DbPath", str(db_path)])
    if status_path is not None:
        command.extend(["-CollectStatusFile", str(status_path)])
    if python_exe is None:
        command.extend(["-ProbeFixtureFile", str(paths["fixture"])])
    else:
        command.extend(["-PythonExe", python_exe])
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _run_hidden_start_process(
    paths: dict[str, Path],
    *,
    python_exe: str,
    db_path: Path,
    status_path: Path,
) -> subprocess.CompletedProcess[str]:
    """以任务计划程序的隐藏子进程形态运行，避免依赖父控制台。"""

    child_command = [
        str(POWERSHELL_EXE),
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        "-RadarRoot",
        str(ROOT),
        "-SecretFile",
        str(paths["secret"]),
        "-StateFile",
        str(paths["state"]),
        "-RunStatusFile",
        str(paths["run_status"]),
        "-LogFile",
        str(paths["log"]),
        "-PushSinkFile",
        str(paths["sink"]),
        "-PythonExe",
        python_exe,
        "-DbPath",
        str(db_path),
        "-CollectStatusFile",
        str(status_path),
    ]
    argument_text = subprocess.list2cmdline(child_command[1:])
    launcher = paths["fixture"].with_name("launch-hidden-watchdog.ps1")
    powershell_literal = str(POWERSHELL_EXE).replace("'", "''")
    arguments_literal = argument_text.replace("'", "''")
    launcher.write_text(
        "\n".join(
            [
                "$process = Start-Process "
                f"-FilePath '{powershell_literal}' "
                f"-ArgumentList '{arguments_literal}' "
                "-WorkingDirectory (Join-Path $env:SystemRoot 'System32') "
                "-WindowStyle Hidden -Wait -PassThru",
                "exit [int]$process.ExitCode",
            ]
        ),
        encoding="utf-8",
    )
    return subprocess.run(
        [
            str(POWERSHELL_EXE),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _set_verdict(paths: dict[str, Path], decision: str, reason: str) -> None:
    _write_json(paths["fixture"], _verdict(decision, reason))


def test_first_healthy_run_initializes_state_without_push(tmp_path: Path) -> None:
    paths = _prepare(tmp_path)
    _set_verdict(paths, "healthy", "ok")

    result = _run(paths)

    assert result.returncode == 0, result.stderr
    assert _events(paths["sink"]) == []
    assert _read_json(paths["state"])["status"] == "ok"
    assert _read_json(paths["run_status"])["state"] == "succeeded"


def test_default_radar_root_is_resolved_after_script_loads_in_ps51(tmp_path: Path) -> None:
    paths = _prepare(tmp_path)
    _set_verdict(paths, "healthy", "ok")

    result = _run(paths, include_radar_root=False)

    assert result.returncode == 0, result.stderr
    assert _read_json(paths["run_status"])["state"] == "succeeded"


def test_first_alert_is_sent_once_and_duplicate_is_suppressed(tmp_path: Path) -> None:
    paths = _prepare(tmp_path)
    _set_verdict(paths, "alert", "pipeline_failed")

    first = _run(paths)
    second = _run(paths)

    assert first.returncode == second.returncode == 0
    assert [event["kind"] for event in _events(paths["sink"])] == ["alert"]
    state = _read_json(paths["state"])
    assert state["status"] == "alerting"
    assert state["primary_reason"] == "pipeline_failed"
    assert state["latest_reason"] == "pipeline_failed"


def test_reason_change_updates_state_without_second_alert(tmp_path: Path) -> None:
    paths = _prepare(tmp_path)
    _set_verdict(paths, "alert", "pipeline_failed")
    assert _run(paths).returncode == 0
    _set_verdict(paths, "alert", "fetch_incomplete")

    result = _run(paths)

    assert result.returncode == 0
    assert len(_events(paths["sink"])) == 1
    state = _read_json(paths["state"])
    assert state["primary_reason"] == "pipeline_failed"
    assert state["latest_reason"] == "fetch_incomplete"


def test_recovery_is_sent_once_and_returns_to_ok(tmp_path: Path) -> None:
    paths = _prepare(tmp_path)
    _set_verdict(paths, "alert", "partial_stale")
    assert _run(paths).returncode == 0
    _set_verdict(paths, "healthy", "ok")

    recovered = _run(paths)
    repeat = _run(paths)

    assert recovered.returncode == repeat.returncode == 0
    assert [event["kind"] for event in _events(paths["sink"])] == ["alert", "recovery"]
    state = _read_json(paths["state"])
    assert state["status"] == "ok"
    assert state["recovery_pending"] is False


def test_failed_recovery_stays_alerting_and_is_retried(tmp_path: Path) -> None:
    paths = _prepare(tmp_path)
    _set_verdict(paths, "alert", "stale")
    assert _run(paths).returncode == 0
    _set_verdict(paths, "healthy", "ok")
    _write_json(paths["secret"], {"nickname": "测试昵称猫", "test_response_status": 500})

    failed = _run(paths)

    assert failed.returncode != 0
    state = _read_json(paths["state"])
    assert state["status"] == "alerting"
    assert state["recovery_pending"] is True
    _write_json(paths["secret"], {"nickname": "测试昵称猫", "test_response_status": 200})
    retried = _run(paths)
    assert retried.returncode == 0
    assert _read_json(paths["state"])["status"] == "ok"
    assert [event["kind"] for event in _events(paths["sink"])] == ["alert", "recovery", "recovery"]


def test_alert_response_status_not_200_is_a_failure_not_an_acknowledged_incident(tmp_path: Path) -> None:
    paths = _prepare(tmp_path, response_status=503)
    _set_verdict(paths, "alert", "pipeline_failed")

    result = _run(paths)

    assert result.returncode != 0
    assert _read_json(paths["run_status"])["state"] == "failed"
    if paths["state"].exists():
        assert _read_json(paths["state"])["status"] != "alerting"
    assert _events(paths["sink"])[0]["response_status"] == 503


def test_slash_in_nickname_is_rejected_without_attempting_a_push(tmp_path: Path) -> None:
    paths = _prepare(tmp_path)
    _write_json(paths["secret"], {"nickname": "not/allowed", "test_response_status": 200})
    _set_verdict(paths, "alert", "pipeline_failed")

    result = _run(paths)

    assert result.returncode != 0
    assert _read_json(paths["run_status"])["message_code"] == "secret_nickname_invalid"
    assert _events(paths["sink"]) == []
    assert not paths["state"].exists()


def test_real_python_probe_pipeline_failure_reaches_the_state_machine_without_writing_db(
    tmp_path: Path,
) -> None:
    paths = _prepare(tmp_path)
    db_path = tmp_path / "sidecar.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE feeds (id TEXT, mp_name TEXT, status INTEGER, sync_time INTEGER)"
        )
        now = int(time.time())
        connection.execute(
            "INSERT INTO feeds (id, mp_name, status, sync_time) VALUES (?, ?, ?, ?)",
            ("feed-a", "公众号A", 1, now - 3_600),
        )
        connection.commit()
    finally:
        connection.close()

    status_path = tmp_path / "wechat-status.json"
    iso = lambda epoch: datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    _write_json(
        status_path,
        {
            "state": "failed",
            "stage": "bridge_preflight",
            "started_at": iso(now - 120),
            "finished_at": iso(now - 30),
            "login_state": "not_applicable",
        },
    )
    before = db_path.read_bytes()

    result = _run(
        paths,
        python_exe=sys.executable,
        db_path=db_path,
        status_path=status_path,
    )

    assert result.returncode == 0, result.stderr
    assert db_path.read_bytes() == before
    assert _events(paths["sink"])[0]["reason"] == "pipeline_failed"
    state = _read_json(paths["state"])
    assert state["status"] == "alerting"
    assert state["primary_reason"] == "pipeline_failed"


def test_hidden_powershell_process_can_read_real_python_probe_output(tmp_path: Path) -> None:
    paths = _prepare(tmp_path)
    db_path = tmp_path / "sidecar.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE feeds (id TEXT, mp_name TEXT, status INTEGER, sync_time INTEGER)"
        )
        now = int(time.time())
        connection.execute(
            "INSERT INTO feeds (id, mp_name, status, sync_time) VALUES (?, ?, ?, ?)",
            ("feed-a", "公众号A", 1, now - 3_600),
        )
        connection.commit()
    finally:
        connection.close()

    status_path = tmp_path / "wechat-status.json"
    iso = lambda epoch: datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    _write_json(
        status_path,
        {
            "state": "failed",
            "stage": "bridge_preflight",
            "started_at": iso(now - 120),
            "finished_at": iso(now - 30),
            "login_state": "not_applicable",
        },
    )
    before = db_path.read_bytes()

    result = _run_hidden_start_process(
        paths,
        python_exe=sys.executable,
        db_path=db_path,
        status_path=status_path,
    )

    assert result.returncode == 0, result.stderr
    assert db_path.read_bytes() == before
    assert _events(paths["sink"])[0]["reason"] == "pipeline_failed"
    assert _read_json(paths["run_status"])["state"] == "succeeded"


def test_utf8_nickname_never_leaks_to_runtime_artifacts(tmp_path: Path) -> None:
    nickname = "隐私昵称猫测试"
    paths = _prepare(tmp_path, nickname=nickname)
    _set_verdict(paths, "alert", "login_expired")

    result = _run(paths)

    assert result.returncode == 0
    for path in (paths["state"], paths["run_status"], paths["sink"], paths["log"]):
        assert nickname not in path.read_text(encoding="utf-8-sig")


def test_missing_secret_marks_run_failed_and_does_not_fake_ok_state(tmp_path: Path) -> None:
    paths = _prepare(tmp_path)
    paths["secret"].unlink()
    _set_verdict(paths, "healthy", "ok")

    result = _run(paths)

    assert result.returncode != 0
    assert _read_json(paths["run_status"])["state"] == "failed"
    if paths["state"].exists():
        assert _read_json(paths["state"])["status"] != "ok"


@pytest.mark.parametrize(
    "mode",
    ["missing_python", "bad_fixture"],
)
def test_probe_failure_sends_watchdog_failed_when_secret_is_available(tmp_path: Path, mode: str) -> None:
    paths = _prepare(tmp_path)
    if mode == "missing_python":
        result = _run(paths, python_exe=str(tmp_path / "missing-python.exe"))
    else:
        paths["fixture"].write_text("{bad-json", encoding="utf-8")
        result = _run(paths)

    assert result.returncode != 0
    assert _read_json(paths["run_status"])["state"] == "failed"
    assert _events(paths["sink"])[0]["reason"] == "watchdog_failed"
    assert _read_json(paths["state"])["status"] == "alerting"


def test_defer_leaves_existing_incident_state_unchanged(tmp_path: Path) -> None:
    paths = _prepare(tmp_path)
    _set_verdict(paths, "alert", "stale")
    assert _run(paths).returncode == 0
    before = paths["state"].read_bytes()
    _set_verdict(paths, "defer", "collection_running")

    result = _run(paths)

    assert result.returncode == 0
    assert _read_json(paths["run_status"])["state"] == "deferred"
    assert paths["state"].read_bytes() == before


def test_second_concurrent_instance_is_safely_skipped(tmp_path: Path) -> None:
    paths = _prepare(tmp_path)
    _set_verdict(paths, "alert", "stale")
    holder = subprocess.Popen(
        [
            str(POWERSHELL_EXE),
            "-NoProfile",
            "-Command",
            (
                "$m=New-Object Threading.Mutex($false,'Local\\AI-News-Radar-WeChat-HealthWatchdog');"
                "if(-not $m.WaitOne(0)){exit 2};"
                "[Console]::Out.WriteLine('locked');"
                "Start-Sleep -Seconds 3;"
                "$m.ReleaseMutex();$m.Dispose()"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        result = _run(paths)
    finally:
        holder.wait(timeout=10)

    assert result.returncode == 0
    assert "busy" in result.stdout.lower()
    assert not paths["state"].exists()
    assert _events(paths["sink"]) == []
