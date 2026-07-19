from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPLOY = ROOT / "deploy" / "local"
if str(LOCAL_DEPLOY) not in sys.path:
    sys.path.insert(0, str(LOCAL_DEPLOY))

import wechat_health_probe as probe  # noqa: E402


NOW = 1_800_000_000


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _status(
    *,
    state: str = "succeeded",
    stage: str = "completed_no_change",
    started_at: float | None = None,
    finished_at: float | None = None,
    login_state: str = "not_applicable",
) -> dict[str, object]:
    if started_at is None:
        started_at = NOW - 120
    if finished_at is None and state != "running":
        finished_at = NOW - 60
    return {
        "state": state,
        "stage": stage,
        "started_at": _iso(started_at),
        "finished_at": _iso(finished_at) if finished_at is not None else None,
        "login_state": login_state,
    }


def _write_status(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _make_db(path: Path, rows: list[tuple[str, str, int | float]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE feeds (
                id TEXT NOT NULL,
                mp_name TEXT NOT NULL,
                status INTEGER NOT NULL,
                sync_time INTEGER NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO feeds (id, mp_name, status, sync_time) VALUES (?, ?, 1, ?)",
            rows,
        )
        connection.commit()
    finally:
        connection.close()
    return path


def _evaluate(
    tmp_path: Path,
    rows: list[tuple[str, str, int | float]],
    status: dict[str, object],
    *,
    stale_hours: float = 14,
) -> dict[str, object]:
    db_path = _make_db(tmp_path / "sidecar.db", rows)
    status_path = tmp_path / "wechat-status.json"
    _write_status(status_path, status)
    return probe.evaluate(
        probe.read_active_feed_syncs(db_path),
        probe.read_collect_status(status_path),
        now_epoch=NOW,
        stale_hours=stale_hours,
    )


def test_fresh_active_feeds_and_success_status_are_healthy(tmp_path: Path) -> None:
    verdict = _evaluate(
        tmp_path,
        [("feed-a", "公众号A", NOW - 60), ("feed-b", "公众号B", NOW - 120)],
        _status(),
    )

    assert verdict["decision"] == "healthy"
    assert verdict["reason"] == "ok"
    assert verdict["active_feed_count"] == 2
    assert verdict["stale_feed_count"] == 0
    assert verdict["latest_success_epoch"] == NOW - 60


def test_one_fresh_and_one_stale_feed_is_partial_stale(tmp_path: Path) -> None:
    verdict = _evaluate(
        tmp_path,
        [("feed-a", "公众号A", NOW - 60), ("feed-b", "公众号B", NOW - 15 * 3600)],
        _status(),
    )

    assert (verdict["decision"], verdict["reason"]) == ("alert", "partial_stale")
    assert verdict["stale_feed_count"] == 1


def test_all_active_feeds_stale_is_an_alert(tmp_path: Path) -> None:
    verdict = _evaluate(
        tmp_path,
        [("feed-a", "公众号A", NOW - 15 * 3600), ("feed-b", "公众号B", NOW - 16 * 3600)],
        _status(),
    )

    assert (verdict["decision"], verdict["reason"]) == ("alert", "stale")
    assert verdict["stale_feed_count"] == 2


def test_expired_login_has_priority_over_warning(tmp_path: Path) -> None:
    verdict = _evaluate(
        tmp_path,
        [("feed-a", "公众号A", NOW - 3_600)],
        _status(
            state="warning",
            stage="fetch_warning",
            finished_at=NOW - 30,
            login_state="expired",
        ),
    )

    assert (verdict["decision"], verdict["reason"]) == ("alert", "login_expired")


def test_non_login_warning_is_fetch_incomplete(tmp_path: Path) -> None:
    verdict = _evaluate(
        tmp_path,
        [("feed-a", "公众号A", NOW - 3_600)],
        _status(state="warning", stage="fetch_warning", finished_at=NOW - 30),
    )

    assert (verdict["decision"], verdict["reason"]) == ("alert", "fetch_incomplete")


def test_newer_bridge_preflight_failure_is_not_hidden_by_fresh_database(tmp_path: Path) -> None:
    verdict = _evaluate(
        tmp_path,
        [("feed-a", "公众号A", NOW - 3_600)],
        _status(state="failed", stage="bridge_preflight", finished_at=NOW - 30),
    )

    assert (verdict["decision"], verdict["reason"]) == ("alert", "pipeline_failed")
    assert "bridge_preflight" in str(verdict["message"])


def test_old_terminal_failure_before_new_database_success_does_not_alert(tmp_path: Path) -> None:
    verdict = _evaluate(
        tmp_path,
        [("feed-a", "公众号A", NOW - 60)],
        _status(state="failed", stage="bridge_preflight", finished_at=NOW - 3_600),
    )

    assert (verdict["decision"], verdict["reason"]) == ("healthy", "ok")


@pytest.mark.parametrize(
    ("started_at", "expected"),
    [
        (NOW - 30 * 60, ("defer", "collection_running")),
        (NOW - 91 * 60, ("alert", "collector_stuck")),
    ],
)
def test_running_collection_is_deferred_then_escalates(
    tmp_path: Path,
    started_at: float,
    expected: tuple[str, str],
) -> None:
    verdict = _evaluate(
        tmp_path,
        [("feed-a", "公众号A", NOW - 60)],
        _status(state="running", stage="fetching", started_at=started_at, finished_at=None),
    )

    assert (verdict["decision"], verdict["reason"]) == expected


@pytest.mark.parametrize(
    "status_value",
    [
        None,
        "{not-json",
        {
            "state": "succeeded",
            "stage": "completed_no_change",
            "started_at": "not-a-time",
            "finished_at": "not-a-time",
            "login_state": "not_applicable",
        },
    ],
)
def test_missing_bad_or_illegal_status_is_a_probe_error(tmp_path: Path, status_value: object) -> None:
    db_path = _make_db(tmp_path / "sidecar.db", [("feed-a", "公众号A", NOW - 60)])
    status_path = tmp_path / "wechat-status.json"
    if status_value is not None:
        if isinstance(status_value, str):
            status_path.write_text(status_value, encoding="utf-8")
        else:
            _write_status(status_path, status_value)

    verdict = probe.evaluate(
        probe.read_active_feed_syncs(db_path),
        probe.read_collect_status(status_path),
        now_epoch=NOW,
        stale_hours=14,
    )

    assert (verdict["decision"], verdict["reason"]) == ("alert", "probe_error")


def test_missing_bad_schema_and_unicode_space_database_paths_are_handled(tmp_path: Path) -> None:
    missing = probe.read_active_feed_syncs(tmp_path / "not-found.db")
    assert missing["ok"] is False

    bad_schema = tmp_path / "bad-schema.db"
    sqlite3.connect(bad_schema).close()
    assert probe.read_active_feed_syncs(bad_schema)["ok"] is False

    unicode_db = _make_db(
        tmp_path / "含 中文 空格" / "sidecar db.db",
        [("feed-a", "公众号A", NOW - 60)],
    )
    result = probe.read_active_feed_syncs(unicode_db)
    assert result["ok"] is True
    assert result["feeds"][0]["id"] == "feed-a"


@pytest.mark.parametrize(
    ("rows", "stale_hours", "expected_reason"),
    [
        ([("future", "未来公众号", NOW + 11 * 60)], 14, "probe_error"),
        ([], 14, "no_active_feeds"),
        ([("feed-a", "公众号A", NOW - 60)], 0, "probe_error"),
        ([("feed-a", "公众号A", NOW - 60)], float("nan"), "probe_error"),
        ([("feed-a", "公众号A", NOW - 60)], float("inf"), "probe_error"),
    ],
)
def test_future_times_empty_feeds_and_bad_threshold_are_not_healthy(
    tmp_path: Path,
    rows: list[tuple[str, str, int | float]],
    stale_hours: float,
    expected_reason: str,
) -> None:
    verdict = _evaluate(tmp_path, rows, _status(), stale_hours=stale_hours)

    assert verdict["decision"] == "alert"
    assert verdict["reason"] == expected_reason


def test_read_only_probe_does_not_modify_sqlite_file(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path / "sidecar.db", [("feed-a", "公众号A", NOW - 60)])
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    before_mtime = db_path.stat().st_mtime_ns

    result = probe.read_active_feed_syncs(db_path)

    assert result["ok"] is True
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
    assert db_path.stat().st_mtime_ns == before_mtime


def test_cli_prints_one_machine_readable_verdict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = _make_db(tmp_path / "sidecar.db", [("feed-a", "公众号A", NOW - 60)])
    status_path = tmp_path / "wechat-status.json"
    _write_status(status_path, _status())

    exit_code = probe.main(
        [
            "--db-path",
            str(db_path),
            "--status-path",
            str(status_path),
            "--stale-hours",
            "14",
            "--now-epoch",
            str(NOW),
        ]
    )

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["decision"], printed["reason"]) == ("healthy", "ok")
