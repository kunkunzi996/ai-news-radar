"""只读判断微信公众号采集健康度，不发送消息，也不写入业务数据。"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
RUNNING_TIMEOUT_SECONDS = 90 * 60
FUTURE_TIME_TOLERANCE_SECONDS = 10 * 60
VALID_COLLECTION_STATES = frozenset({"running", "succeeded", "warning", "failed"})
SAFE_STAGE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _read_error(code: str) -> dict[str, object]:
    return {"ok": False, "error_code": code}


def _iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _verdict(
    *,
    decision: str,
    reason: str,
    title: str,
    message: str,
    active_feed_count: int,
    stale_feed_count: int,
    latest_success_epoch: int | float | None,
    checked_at: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "decision": decision,
        "reason": reason,
        "title": title,
        "message": message,
        "active_feed_count": active_feed_count,
        "stale_feed_count": stale_feed_count,
        "latest_success_epoch": latest_success_epoch,
        "checked_at": checked_at,
    }


def _probe_error(
    *,
    checked_at: str,
    active_feed_count: int = 0,
    stale_feed_count: int = 0,
    latest_success_epoch: int | float | None = None,
) -> dict[str, object]:
    return _verdict(
        decision="alert",
        reason="probe_error",
        title="微信健康检查异常",
        message="微信健康检查无法可靠读取本机状态，请检查看门狗运行状态。",
        active_feed_count=active_feed_count,
        stale_feed_count=stale_feed_count,
        latest_success_epoch=latest_success_epoch,
        checked_at=checked_at,
    )


def read_active_feed_syncs(db_path: str | Path) -> dict[str, object]:
    """以 SQLite mode=ro 读取所有启用 Feed，绝不修改 sidecar 数据库。"""

    connection: sqlite3.Connection | None = None
    try:
        path = Path(db_path)
        if not path.is_file():
            return _read_error("database_missing")

        uri = path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        rows = connection.execute(
            "SELECT id, mp_name, sync_time FROM feeds WHERE status = ?",
            (1,),
        ).fetchall()
        feeds: list[dict[str, object]] = []
        for feed_id, mp_name, sync_time in rows:
            if not isinstance(feed_id, str) or not feed_id.strip():
                return _read_error("database_invalid")
            if not isinstance(mp_name, str) or not mp_name.strip():
                return _read_error("database_invalid")
            feeds.append(
                {
                    "id": feed_id,
                    "mp_name": mp_name,
                    "sync_time": sync_time,
                }
            )
        return {"ok": True, "feeds": feeds}
    except (OSError, ValueError, sqlite3.Error):
        return _read_error("database_unreadable")
    finally:
        if connection is not None:
            connection.close()


def read_collect_status(status_path: str | Path) -> dict[str, object]:
    """读取并做基础类型校验；不读取或转发原始 message 字段。"""

    try:
        path = Path(status_path)
        if not path.is_file():
            return _read_error("status_file_missing")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return _read_error("status_file_unreadable")
    except json.JSONDecodeError:
        return _read_error("status_file_invalid")

    if not isinstance(payload, dict):
        return _read_error("status_file_invalid")

    state = payload.get("state")
    stage = payload.get("stage")
    started_at = payload.get("started_at")
    finished_at = payload.get("finished_at")
    login_state = payload.get("login_state")
    if (
        not isinstance(state, str)
        or state not in VALID_COLLECTION_STATES
        or not isinstance(stage, str)
        or not SAFE_STAGE.fullmatch(stage)
        or not isinstance(started_at, str)
        or not started_at.strip()
        or not isinstance(login_state, str)
        or not login_state.strip()
        or (finished_at is not None and (not isinstance(finished_at, str) or not finished_at.strip()))
    ):
        return _read_error("status_file_invalid")

    return {
        "ok": True,
        "status": {
            "state": state,
            "stage": stage,
            "started_at": started_at,
            "finished_at": finished_at,
            "login_state": login_state,
        },
    }


def _parse_epoch(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid epoch")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("invalid epoch")
    return parsed


def _parse_iso_epoch(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid iso time")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timezone is required")
    return parsed.timestamp()


def _safe_result(
    *,
    decision: str,
    reason: str,
    title: str,
    message: str,
    active_feed_count: int,
    stale_feed_count: int,
    latest_success_epoch: float | None,
    checked_at: str,
) -> dict[str, object]:
    latest: int | float | None
    if latest_success_epoch is None:
        latest = None
    elif latest_success_epoch.is_integer():
        latest = int(latest_success_epoch)
    else:
        latest = latest_success_epoch
    return _verdict(
        decision=decision,
        reason=reason,
        title=title,
        message=message,
        active_feed_count=active_feed_count,
        stale_feed_count=stale_feed_count,
        latest_success_epoch=latest,
        checked_at=checked_at,
    )


def evaluate(
    feed_read: dict[str, object],
    status_read: dict[str, object],
    *,
    now_epoch: float | None = None,
    stale_hours: float = 14,
) -> dict[str, object]:
    """纯判定函数：同样的输入一定得到同样的 verdict。"""

    try:
        now = time.time() if now_epoch is None else float(now_epoch)
        stale_hours_value = float(stale_hours)
        if (
            isinstance(stale_hours, bool)
            or not math.isfinite(now)
            or not math.isfinite(stale_hours_value)
            or stale_hours_value <= 0
        ):
            raise ValueError("invalid time input")
        checked_at = _iso_utc(now)
    except (OverflowError, TypeError, ValueError):
        return _probe_error(checked_at=_iso_utc(time.time()))
    if feed_read.get("ok") is not True or status_read.get("ok") is not True:
        return _probe_error(checked_at=checked_at)

    feeds = feed_read.get("feeds")
    status = status_read.get("status")
    if not isinstance(feeds, list) or not isinstance(status, dict):
        return _probe_error(checked_at=checked_at)

    try:
        sync_epochs: list[float] = []
        for feed in feeds:
            if not isinstance(feed, dict):
                raise ValueError("invalid feed")
            sync_epoch = _parse_epoch(feed.get("sync_time"))
            if sync_epoch > now + FUTURE_TIME_TOLERANCE_SECONDS:
                raise ValueError("future sync time")
            sync_epochs.append(sync_epoch)

        state = status.get("state")
        stage = status.get("stage")
        started_epoch = _parse_iso_epoch(status.get("started_at"))
        finished_at = status.get("finished_at")
        login_state = status.get("login_state")
        if (
            not isinstance(state, str)
            or state not in VALID_COLLECTION_STATES
            or not isinstance(stage, str)
            or not SAFE_STAGE.fullmatch(stage)
            or not isinstance(login_state, str)
            or not login_state.strip()
            or started_epoch > now + FUTURE_TIME_TOLERANCE_SECONDS
        ):
            raise ValueError("invalid status")
        finished_epoch: float | None = None
        if finished_at is not None:
            finished_epoch = _parse_iso_epoch(finished_at)
            if finished_epoch > now + FUTURE_TIME_TOLERANCE_SECONDS:
                raise ValueError("future finished time")
        if state != "running" and finished_epoch is None:
            raise ValueError("terminal state missing finished_at")
    except (OverflowError, TypeError, ValueError):
        return _probe_error(checked_at=checked_at)

    active_count = len(sync_epochs)
    latest_success_epoch = max(sync_epochs) if sync_epochs else None
    if active_count == 0:
        return _safe_result(
            decision="alert",
            reason="no_active_feeds",
            title="没有启用公众号",
            message="健康检查没有读到启用的微信公众号，请确认是否仍需要微信采集。",
            active_feed_count=0,
            stale_feed_count=0,
            latest_success_epoch=None,
            checked_at=checked_at,
        )

    stale_seconds = stale_hours_value * 3600
    stale_count = sum(now - sync_epoch > stale_seconds for sync_epoch in sync_epochs)

    if state == "running":
        if now - started_epoch < RUNNING_TIMEOUT_SECONDS:
            return _safe_result(
                decision="defer",
                reason="collection_running",
                title="微信采集中",
                message="微信采集仍在正常运行，本轮不改变告警状态。",
                active_feed_count=active_count,
                stale_feed_count=stale_count,
                latest_success_epoch=latest_success_epoch,
                checked_at=checked_at,
            )
        return _safe_result(
            decision="alert",
            reason="collector_stuck",
            title="微信采集卡住",
            message="微信采集持续运行超过 90 分钟，请检查本机采集流程。",
            active_feed_count=active_count,
            stale_feed_count=stale_count,
            latest_success_epoch=latest_success_epoch,
            checked_at=checked_at,
        )

    terminal_after_success = bool(
        finished_epoch is not None and latest_success_epoch is not None and finished_epoch > latest_success_epoch
    )
    if terminal_after_success and login_state == "expired":
        return _safe_result(
            decision="alert",
            reason="login_expired",
            title="微信登录失效",
            message="微信采集登录状态已失效，请重新扫码登录。",
            active_feed_count=active_count,
            stale_feed_count=stale_count,
            latest_success_epoch=latest_success_epoch,
            checked_at=checked_at,
        )
    if terminal_after_success and state == "warning":
        return _safe_result(
            decision="alert",
            reason="fetch_incomplete",
            title="微信抓取不完整",
            message="最近一次微信抓取不完整，请检查采集日志和登录状态。",
            active_feed_count=active_count,
            stale_feed_count=stale_count,
            latest_success_epoch=latest_success_epoch,
            checked_at=checked_at,
        )
    if terminal_after_success and state == "failed":
        return _safe_result(
            decision="alert",
            reason="pipeline_failed",
            title="微信采集链路失败",
            message=f"最近一次微信采集在阶段 {stage} 失败。",
            active_feed_count=active_count,
            stale_feed_count=stale_count,
            latest_success_epoch=latest_success_epoch,
            checked_at=checked_at,
        )

    if 0 < stale_count < active_count:
        return _safe_result(
            decision="alert",
            reason="partial_stale",
            title="部分公众号停更",
            message=f"{stale_count}/{active_count} 个启用公众号超过 {stale_hours_value:g} 小时未同步。",
            active_feed_count=active_count,
            stale_feed_count=stale_count,
            latest_success_epoch=latest_success_epoch,
            checked_at=checked_at,
        )
    if stale_count == active_count:
        return _safe_result(
            decision="alert",
            reason="stale",
            title="全部公众号停更",
            message=f"全部 {active_count} 个启用公众号超过 {stale_hours_value:g} 小时未同步。",
            active_feed_count=active_count,
            stale_feed_count=stale_count,
            latest_success_epoch=latest_success_epoch,
            checked_at=checked_at,
        )
    return _safe_result(
        decision="healthy",
        reason="ok",
        title="微信采集正常",
        message="所有启用公众号新鲜，最近采集状态正常。",
        active_feed_count=active_count,
        stale_feed_count=stale_count,
        latest_success_epoch=latest_success_epoch,
        checked_at=checked_at,
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读判断微信公众号采集健康度")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--status-path", required=True)
    parser.add_argument("--stale-hours", type=float, default=14)
    parser.add_argument("--now-epoch", type=float, default=None, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        verdict = evaluate(
            read_active_feed_syncs(args.db_path),
            read_collect_status(args.status_path),
            now_epoch=args.now_epoch,
            stale_hours=args.stale_hours,
        )
    except Exception:
        # 意外代码错误交给编排脚本转成 watchdog_failed，避免把内部异常泄露进日志。
        return 2
    print(json.dumps(verdict, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
