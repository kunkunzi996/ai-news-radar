"""桥接采集完成后，立即触发一次云端 Actions 刷新。

背景：抖音/微信采集完成后只是把 JSONL 推到**桥接仓库**，主仓库没有任何变化，
因此不会触发主仓库的 workflow —— 新内容要等下一轮定时（每小时 7/37 分）才被读取。
本模块负责在采集真正结束后，往主仓库提交一个标记文件，把那一轮 Actions 立刻拉起来。

## 为什么用 GitHub Contents API 而不是本地 git

主仓库在 NUC 上的工作区常年有未提交的 data 产物，本地 commit/push 必须走
`sync_online_source_config` 那套「stash 隔离 → rebase → push → 覆盖恢复」编排，
而那正是 CLAUDE.md 写了整章禁区、历史上踩坑最多的地方。改用 Contents API 直接在
远端建提交，**完全不碰本地工作区和 git 状态**，风险面小得多。

用 PAT（非 GITHUB_TOKEN）推送的提交会正常触发 workflow；标记文件放在仓库根，
不在 `paths-ignore: data/**` 覆盖范围内，因此能真正拉起采集那一轮。

## 边界

- 只在采集**真正结束**后触发一次（靠采集脚本写的 `finished_at` 判定），
  不在派发瞬间触发——那时桥接仓库还没有新数据，白跑一轮。
- 任何环节失败都只记录状态，绝不抛出：它是锦上添花，不能影响采集或保存。
- 等待有硬超时；超时就放弃，反正下一轮定时 Actions 同样会读到桥接仓库的新数据。
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 采集状态文件由计划任务的 -StatusFile 参数指定，位于仓库的父目录。
DOUYIN_STATUS_FILENAME = "douyin-collect-status.json"
WECHAT_STATUS_FILENAME = "wechat-collect-status.json"

# SYSTEM 侧 PAT（细粒度，仅本仓库 Contents 读写），ACL 锁定为 SYSTEM/Administrators。
PAT_FILE_ENV = "RADAR_ADMIN_PAT_FILE"
DEFAULT_PAT_FILE = Path("C:/OMNIA/radar-admin/pat.txt")

REPO_SLUG_ENV = "RADAR_GITHUB_REPO"
DEFAULT_REPO_SLUG = "kunkunzi996/ai-news-radar"

# 标记文件必须落在仓库根：data/ 会被 workflow 的 paths-ignore 忽略，放那里触发不了。
REFRESH_MARKER_PATH = ".bridge-refresh.json"
REFRESH_COMMIT_MESSAGE = "数据：桥接采集完成，触发刷新"

STATUS_RELATIVE_PATH = Path("logs") / "actions-refresh-status.json"
STATUS_HISTORY_LIMIT = 20

# 抖音 5 个博主约数分钟；给足余量，超时即放弃并交回定时轮次。
DEFAULT_WAIT_TIMEOUT_SECONDS = 25 * 60
DEFAULT_POLL_INTERVAL_SECONDS = 20

GITHUB_API_ROOT = "https://api.github.com"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    """解析采集脚本写出的 ISO 8601 时间（PowerShell 的 "o" 格式，带 Z 或偏移）。"""
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def status_file_path(root_dir: Path, filename: str) -> Path:
    """采集状态文件在仓库的父目录（与计划任务 -StatusFile 参数一致）。"""
    return root_dir.parent / filename


def read_collect_status(root_dir: Path, filename: str) -> dict[str, Any]:
    path = status_file_path(root_dir, filename)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


# 判定「这份状态属于本轮」时往前放宽的容差，吸收派发与脚本启动之间的时间差。
START_TOLERANCE_SECONDS = 30


def wait_for_collect_finish(
    root_dir: Path,
    since: datetime,
    *,
    timeout_seconds: int = DEFAULT_WAIT_TIMEOUT_SECONDS,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    sleep=time.sleep,
) -> dict[str, Any]:
    """轮询采集状态文件，等本轮采集结束。

    计划任务顺序执行抖音、微信两个动作，因此只要有任一渠道在本轮跑过并结束，
    且没有渠道仍处于「本轮已开始但未结束」的状态，就认为整轮结束。
    """
    deadline = time.monotonic() + timeout_seconds
    threshold = since.timestamp() - START_TOLERANCE_SECONDS
    observed: dict[str, Any] = {}
    while True:
        finished_any = False
        pending = False
        for key, filename in (
            ("douyin", DOUYIN_STATUS_FILENAME),
            ("wechat", WECHAT_STATUS_FILENAME),
        ):
            status = read_collect_status(root_dir, filename)
            started = _parse_time(status.get("started_at"))
            finished = _parse_time(status.get("finished_at"))
            if started is None or started.timestamp() < threshold:
                continue  # 这份状态属于上一轮，忽略
            observed[key] = {
                "state": status.get("state"),
                "stage": status.get("stage"),
                "started_at": status.get("started_at"),
                "finished_at": status.get("finished_at"),
            }
            if finished is not None and finished >= started:
                finished_any = True
            else:
                pending = True

        if finished_any and not pending:
            return {"ok": True, "timed_out": False, "channels": observed}
        if time.monotonic() >= deadline:
            return {"ok": False, "timed_out": True, "channels": observed}
        sleep(poll_interval_seconds)


def read_pat() -> str:
    path = Path(os.environ.get(PAT_FILE_ENV) or DEFAULT_PAT_FILE)
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def repo_slug() -> str:
    return (os.environ.get(REPO_SLUG_ENV) or "").strip() or DEFAULT_REPO_SLUG


def build_marker_payload(reason: Any, collect: Any) -> dict[str, Any]:
    """标记文件内容：记录本轮因谁触发、采集结果如何，便于事后追溯。"""
    return {
        "refreshed_at": _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason if isinstance(reason, dict) else {},
        "collect": collect if isinstance(collect, dict) else {},
    }


def push_refresh_marker(payload: dict[str, Any], *, session=None) -> dict[str, Any]:
    """通过 Contents API 更新标记文件；提交由 PAT 完成，会正常触发 workflow。"""
    import requests  # 延迟导入：本模块在无网络的单测里也要可导入

    token = read_pat()
    if not token:
        return {"ok": False, "error": "pat_not_available"}

    http = session or requests
    url = f"{GITHUB_API_ROOT}/repos/{repo_slug()}/contents/{REFRESH_MARKER_PATH}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    try:
        # 已存在则必须带上当前 sha，否则 API 拒绝更新。
        current = http.get(url, headers=headers, timeout=30)
        sha = current.json().get("sha") if current.status_code == 200 else None
        request_body: dict[str, Any] = {
            "message": REFRESH_COMMIT_MESSAGE,
            "content": base64.b64encode(body.encode("utf-8")).decode("ascii"),
        }
        if sha:
            request_body["sha"] = sha
        response = http.put(url, headers=headers, json=request_body, timeout=30)
    except Exception as exc:  # noqa: BLE001 - 网络异常不得影响采集
        return {"ok": False, "error": str(exc)[:300]}

    if response.status_code not in (200, 201):
        return {
            "ok": False,
            "error": f"http_{response.status_code}",
            "detail": (response.text or "")[:300],
        }
    commit = {}
    try:
        commit = response.json().get("commit") or {}
    except ValueError:
        pass
    return {"ok": True, "commit": commit.get("sha", ""), "status_code": response.status_code}


def status_path(root_dir: Path) -> Path:
    return root_dir / STATUS_RELATIVE_PATH


def append_status(root_dir: Path, entry: dict[str, Any]) -> None:
    try:
        path = status_path(root_dir)
        payload: dict[str, Any] = {"runs": []}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("runs"), list):
                    payload = loaded
            except (OSError, ValueError):
                payload = {"runs": []}
        runs = payload.get("runs", [])
        runs.append(entry)
        payload["runs"] = runs[-STATUS_HISTORY_LIMIT:]
        payload["updated_at"] = entry.get("finished_at")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def wait_then_refresh(
    root_dir: Path,
    since: datetime,
    reason: Any,
    *,
    timeout_seconds: int = DEFAULT_WAIT_TIMEOUT_SECONDS,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    sleep=time.sleep,
) -> dict[str, Any]:
    """看门人主体：等采集结束 → 推标记文件 → 记录状态。全程不抛异常。"""
    entry: dict[str, Any] = {"started_at": since.strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        waited = wait_for_collect_finish(
            root_dir,
            since,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            sleep=sleep,
        )
        entry["collect"] = waited.get("channels", {})
        if not waited.get("ok"):
            entry["ok"] = False
            entry["error"] = "collect_wait_timeout"
            entry["finished_at"] = _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            append_status(root_dir, entry)
            return entry

        pushed = push_refresh_marker(build_marker_payload(reason, waited.get("channels")))
        entry["ok"] = bool(pushed.get("ok"))
        entry["push"] = pushed
    except Exception as exc:  # noqa: BLE001 - 后台线程绝不允许把异常抛给运行时
        entry["ok"] = False
        entry["error"] = str(exc)[:300]
    entry["finished_at"] = _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    append_status(root_dir, entry)
    return entry
