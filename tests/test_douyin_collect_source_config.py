"""抖音定时采集要读网页写进去的名单，而不是仓库里那份旧配置。"""
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
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "deploy" / "cloud-pc" / "collect-douyin-and-push.ps1"


def write_config(path: Path, locator: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "type": "mediacrawler_jsonl",
                        "enabled": True,
                        "name": "probe",
                        "locator": locator,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def prepare(tmp_path: Path) -> tuple[Path, Path, Path]:
    radar_root = tmp_path / "radar"
    crawler_root = tmp_path / "MediaCrawler"
    bridge_root = tmp_path / "douyin-bridge"
    (radar_root / "scripts").mkdir(parents=True)
    (radar_root / "scripts" / "run_mediacrawler_douyin.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).resolve().parents[1].joinpath('runner-invoked').write_text('yes', encoding='utf-8')\n"
        "raise SystemExit(9)\n",
        encoding="utf-8",
    )
    crawler_root.mkdir()
    (crawler_root / "main.py").write_text("# fake crawler\n", encoding="utf-8")
    bridge_root.mkdir()
    (bridge_root / ".git").mkdir()
    return radar_root, crawler_root, bridge_root


def run_collect(tmp_path: Path, radar_root: Path, crawler_root: Path, bridge_root: Path) -> dict:
    status_path = tmp_path / "status.json"
    result = subprocess.run(
        [
            POWERSHELL_EXE, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
            "-RadarRoot", str(radar_root), "-CrawlerRoot", str(crawler_root),
            "-BridgeRoot", str(bridge_root), "-PythonExe", sys.executable,
            "-SkipGitPull", "-StatusFile", str(status_path),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    status = json.loads(status_path.read_text(encoding="utf-8-sig"))
    status["_returncode"] = result.returncode
    status["_runner_invoked"] = (radar_root / "runner-invoked").exists()
    return status


def test_local_overlay_replaces_committed_douyin_roster(tmp_path: Path) -> None:
    radar_root, crawler_root, bridge_root = prepare(tmp_path)
    write_config(radar_root / ".local" / "online-sources.json", "https://www.douyin.com/user/BAD ID")
    write_config(radar_root / "config" / "online-sources.json", "https://www.douyin.com/user/GoodCreator")

    status = run_collect(tmp_path, radar_root, crawler_root, bridge_root)

    assert status["_returncode"] == 1
    assert status["stage"] == "creator_config"
    assert "Invalid Douyin creator id" in status["message"]
    assert status["_runner_invoked"] is False


def test_missing_overlay_falls_back_to_committed_config(tmp_path: Path) -> None:
    radar_root, crawler_root, bridge_root = prepare(tmp_path)
    write_config(radar_root / "config" / "online-sources.json", "https://www.douyin.com/user/BAD ID")

    status = run_collect(tmp_path, radar_root, crawler_root, bridge_root)

    assert status["_returncode"] == 1
    assert status["stage"] == "creator_config"
    assert "Invalid Douyin creator id" in status["message"]
    assert status["_runner_invoked"] is False


def test_overlay_without_douyin_does_not_read_committed_roster(tmp_path: Path) -> None:
    radar_root, crawler_root, bridge_root = prepare(tmp_path)
    overlay = radar_root / ".local" / "online-sources.json"
    overlay.parent.mkdir(parents=True)
    overlay.write_text(json.dumps({"sources": []}), encoding="utf-8")
    write_config(radar_root / "config" / "online-sources.json", "https://www.douyin.com/user/GoodCreator")

    status = run_collect(tmp_path, radar_root, crawler_root, bridge_root)

    assert status["_returncode"] == 0
    assert status["state"] == "succeeded"
    assert status["stage"] == "completed_no_sources"
    assert status["_runner_invoked"] is False
