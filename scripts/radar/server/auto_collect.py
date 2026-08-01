"""新增桥接类信源后立即触发一次本机采集。

背景：抖音（mediacrawler_jsonl）与微信公众号（we_mp_rss_jsonl）两类信源，云端
Actions 抓不了（需要登录态与浏览器），只能读取本机采集后推送到桥接仓库的 JSONL。
本机采集是计划任务，每天只跑 3 次，因此用户新增这两类信源后最坏要等 12 小时才能
看到内容。本模块在「保存线上信源配置」成功后检测新增源并立即触发一次采集。

## 为什么是触发计划任务，而不是自己起采集进程

采集必须以**用户交互身份**运行，而本服务是 SYSTEM：

- `RadarAdminServer`（本服务）：UserId=SYSTEM、LogonType=ServiceAccount
- `DouyinCollectAndPush`（采集任务）：UserId=beelink-pc、LogonType=Interactive

抖音采集要连用户会话里那个带登录态的专用 Chrome（CDP 9333），SYSTEM 因会话隔离
拿不到；推送桥接仓库用的也是用户自己的 git 凭证，而 SYSTEM 侧的 PAT 只对
ai-news-radar 仓库有 Contents 权限，够不着 douyin-bridge。

计划任务里已经配好了正确的身份与全部路径参数（CrawlerRoot 实际是
`MediaCrawler-local-test`，并非脚本默认推导的 `MediaCrawler`），因此触发它是唯一
既不需要改采集脚本、也不需要额外部署的可行路径。

该计划任务包含**两个动作**（抖音 + 微信），触发一次即可覆盖两类信源，所以本模块
不区分派发目标，只在状态里记录本次是因为哪些新增源触发的。

## 设计边界（改动前必读 CLAUDE.md 对应禁区）

- 只在「新增」时触发。删除、停用、改名一律不触发，避免与历史清理逻辑产生任何交集。
- 本模块**绝不触碰** data/archive.json 或任何历史清理路径。
- 触发是异步的（schtasks /run 只负责启动，立即返回）：请求经 Cloudflare 隧道，
  读超时 120 秒，同步等待采集完成必然 524。
- 代价：计划任务是全量采集，无法只采新增的那个号。要做定向单号，需要让采集脚本
  支持读取一份「本次要采谁」的请求文件，那是另一件事。
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from scripts.radar.server import actions_refresh as _actions_refresh

# 桥接类信源：这两种 type 的内容不由云端 Actions 采集，只能读本机推送的 JSONL。
DOUYIN_SOURCE_TYPE = "mediacrawler_jsonl"
WECHAT_SOURCE_TYPE = "we_mp_rss_jsonl"

# 本机采集计划任务（含抖音、微信两个动作），可用环境变量覆盖以便迁移或改名。
COLLECT_TASK_ENV = "RADAR_AUTO_COLLECT_TASK"
DEFAULT_COLLECT_TASK = "DouyinCollectAndPush"

# 触发只是启动任务，正常在毫秒级返回；给一个上限避免任何形式的挂起。
TRIGGER_TIMEOUT_SECONDS = 15

# 状态文件放 logs/：data/ 会被 Actions 提交，且被 workflow 的 paths-ignore 覆盖。
STATUS_RELATIVE_PATH = Path("logs") / "auto-collect-status.json"

STATUS_HISTORY_LIMIT = 20


def _sources_of(config: Any) -> list[dict[str, Any]]:
    """从配置中安全取出信源列表；结构异常时返回空列表而不是抛异常。"""
    if not isinstance(config, dict):
        return []
    sources = config.get("sources")
    if not isinstance(sources, list):
        return []
    return [item for item in sources if isinstance(item, dict)]


def _is_enabled(source: dict[str, Any]) -> bool:
    """enabled 缺省视为启用，只有显式 false 才算停用（与线上配置口径一致）。"""
    return source.get("enabled") is not False


def _source_id(source: dict[str, Any]) -> str:
    return str(source.get("id") or "").strip()


def parse_douyin_sec_uid(locator: Any) -> str:
    """从抖音主页链接里取 sec_uid（仅用于状态记录，便于事后核对触发原因）。

    线上配置的 locator 形如 https://www.douyin.com/user/<sec_uid>。
    取不出来时返回空串，由调用方跳过——不要抛异常，否则会牵连保存流程。
    """
    text = str(locator or "").strip()
    if not text:
        return ""
    try:
        path = urlparse(text).path
    except ValueError:
        return ""
    marker = "/user/"
    index = path.find(marker)
    if index < 0:
        return ""
    return path[index + len(marker):].strip("/").split("/")[0].strip()


def detect_added_bridge_sources(
    previous_config: Any,
    current_config: Any,
) -> dict[str, Any]:
    """比对新旧配置，找出本次**新增**的桥接类信源。

    「新增」的判定：id 在 current 里处于启用态，且在 previous 里不存在或处于停用态。
    把「停用改回启用」也算新增，因为它的历史可能已在停用时被清理，需要重新采一次。

    删除、停用、改名、改备注一律不算新增，返回结果里不会出现。
    previous_config 缺失（首次写入等）时一律返回空结果，避免把存量源全当成新增。
    """
    empty: dict[str, Any] = {"douyin_sec_uids": [], "wechat_added": False, "added_names": []}
    if not isinstance(previous_config, dict):
        return empty

    previous_enabled_ids = {
        _source_id(source)
        for source in _sources_of(previous_config)
        if _is_enabled(source) and _source_id(source)
    }

    sec_uids: list[str] = []
    added_names: list[str] = []
    wechat_added = False

    for source in _sources_of(current_config):
        source_id = _source_id(source)
        if not source_id or not _is_enabled(source):
            continue
        if source_id in previous_enabled_ids:
            continue

        source_type = str(source.get("type") or "").strip()
        name = str(source.get("name") or source.get("target") or source_id).strip()

        if source_type == DOUYIN_SOURCE_TYPE:
            sec_uid = parse_douyin_sec_uid(source.get("locator"))
            if not sec_uid:
                # 解析不出 sec_uid 只是少一条状态记录，不影响触发，也不影响保存。
                continue
            if sec_uid not in sec_uids:
                sec_uids.append(sec_uid)
                added_names.append(name)
        elif source_type == WECHAT_SOURCE_TYPE:
            wechat_added = True
            added_names.append(name)

    return {
        "douyin_sec_uids": sec_uids,
        "wechat_added": wechat_added,
        "added_names": added_names,
    }


def has_pending_work(detected: dict[str, Any]) -> bool:
    """是否有需要触发采集的新增源。"""
    if not isinstance(detected, dict):
        return False
    return bool(detected.get("douyin_sec_uids")) or bool(detected.get("wechat_added"))


def collect_task_name() -> str:
    return (os.environ.get(COLLECT_TASK_ENV) or "").strip() or DEFAULT_COLLECT_TASK


def build_collect_task_command(task_name: str) -> list[str]:
    """触发计划任务。schtasks 只负责启动，任务本身在自己的身份下异步运行。"""
    return ["schtasks", "/run", "/tn", task_name]


def _trigger(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=TRIGGER_TIMEOUT_SECONDS,
        check=False,
    )


def status_path(root_dir: Path) -> Path:
    return root_dir / STATUS_RELATIVE_PATH


def read_status(root_dir: Path) -> dict[str, Any]:
    path = status_path(root_dir)
    if not path.exists():
        return {"runs": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"runs": []}
    if not isinstance(payload, dict):
        return {"runs": []}
    if not isinstance(payload.get("runs"), list):
        payload["runs"] = []
    return payload


def append_status(root_dir: Path, entry: dict[str, Any]) -> None:
    """追加一条触发记录；状态文件损坏或不可写都不得影响调用方。"""
    try:
        payload = read_status(root_dir)
        runs = payload.get("runs", [])
        runs.append(entry)
        payload["runs"] = runs[-STATUS_HISTORY_LIMIT:]
        payload["updated_at"] = entry.get("started_at")
        path = status_path(root_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return


def start_refresh_watcher(root_dir: Path, reason: dict[str, Any]) -> threading.Thread:
    """起守护线程：等采集真正结束后，触发一次云端 Actions 刷新。

    必须是后台线程——采集要跑几分钟，而本函数处在 HTTP 保存请求的调用栈上。
    守护线程随服务退出而消失；那种情况下放弃刷新即可，下一轮定时 Actions 兜底。
    """
    thread = threading.Thread(
        target=_actions_refresh.wait_then_refresh,
        args=(root_dir, datetime.now(timezone.utc), reason),
        name="bridge-refresh-watcher",
        daemon=True,
    )
    thread.start()
    return thread


def dispatch_bridge_collect(
    root_dir: Path,
    detected: dict[str, Any],
    *,
    execute: bool = True,
    watch: bool = True,
) -> dict[str, Any]:
    """按检测结果触发一次本机采集计划任务。

    execute=False 时只返回将要执行的命令，不真正触发（供单测与人工核对使用）。

    计划任务若正在运行，schtasks 会返回非零（任务已在运行中）：这是**预期行为**，
    记录状态后正常返回，不重试、不等待——反正正在跑的那轮同样会采到新源。
    """
    task_name = collect_task_name()
    result: dict[str, Any] = {
        "triggered": False,
        "task": task_name,
        "command": build_collect_task_command(task_name),
        "reason": {
            "douyin_sec_uids": list(detected.get("douyin_sec_uids") or []),
            "wechat_added": bool(detected.get("wechat_added")),
            "added_names": list(detected.get("added_names") or []),
        },
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if not has_pending_work(detected):
        return result
    if not execute:
        result["executed"] = False
        return result

    try:
        completed = _trigger(result["command"])
    except (OSError, subprocess.SubprocessError) as exc:
        result["error"] = str(exc)
        append_status(root_dir, {**result, "ok": False})
        return result

    result["executed"] = True
    result["returncode"] = completed.returncode
    result["triggered"] = completed.returncode == 0
    if completed.returncode != 0:
        # 常见于任务已在运行；保留原始输出便于排查，但不作为错误上抛。
        result["error"] = (completed.stderr or completed.stdout or "").strip()[:500]
    if result["triggered"] and watch:
        # 采集异步进行，结束后才有新数据可推；看门人负责那一刻的云端刷新。
        try:
            start_refresh_watcher(root_dir, result["reason"])
            result["watching"] = True
        except Exception as exc:  # noqa: BLE001 - 刷新是锦上添花，不能影响采集
            result["watching"] = False
            result["watch_error"] = str(exc)[:200]
    append_status(root_dir, {**result, "ok": result["triggered"]})
    return result


# 「保存」与「同步」是两个独立的 HTTP 请求，前端保存成功后紧接着发同步请求。
# 采集一旦启动会拉起浏览器和 MediaCrawler 抢占资源，若在保存阶段就触发，紧随其后的
# 同步（git push）会被拖慢到超过 Cloudflare 的 120 秒读超时，前端表现为
# 「推送失败: Failed to fetch」——尽管后端其实已经推送成功（2026-08-01 真实踩过）。
# 因此保存阶段只登记，等同步确认推送成功后再真正触发。
_PENDING_LOCK = threading.Lock()
_PENDING_COLLECT: dict[str, Any] | None = None


def queue_pending_collect(detected: dict[str, Any]) -> dict[str, Any]:
    """登记一次待触发的采集；同一批次内多次保存以最后一次为准并合并。"""
    global _PENDING_COLLECT
    with _PENDING_LOCK:
        if _PENDING_COLLECT is None:
            _PENDING_COLLECT = {"douyin_sec_uids": [], "wechat_added": False, "added_names": []}
        for sec_uid in detected.get("douyin_sec_uids") or []:
            if sec_uid not in _PENDING_COLLECT["douyin_sec_uids"]:
                _PENDING_COLLECT["douyin_sec_uids"].append(sec_uid)
        for name in detected.get("added_names") or []:
            if name not in _PENDING_COLLECT["added_names"]:
                _PENDING_COLLECT["added_names"].append(name)
        _PENDING_COLLECT["wechat_added"] = bool(
            _PENDING_COLLECT["wechat_added"] or detected.get("wechat_added")
        )
        return dict(_PENDING_COLLECT)


def take_pending_collect() -> dict[str, Any] | None:
    """取出并清空待触发的采集登记。"""
    global _PENDING_COLLECT
    with _PENDING_LOCK:
        pending = _PENDING_COLLECT
        _PENDING_COLLECT = None
        return pending


def handle_saved_config(
    root_dir: Path,
    previous_config: Any,
    current_config: Any,
) -> dict[str, Any]:
    """保存成功后的入口：只检测并登记，**不触发采集**。

    调用方必须把本函数包在 try/except 里——它已尽量不抛异常，但任何意外都
    绝不允许影响信源配置的保存结果。
    """
    detected = detect_added_bridge_sources(previous_config, current_config)
    if not has_pending_work(detected):
        return {"pending": False, "reason": None}
    queue_pending_collect(detected)
    return {"pending": True, "reason": detected}


def flush_pending_collect(
    root_dir: Path,
    *,
    execute: bool = True,
    watch: bool = True,
) -> dict[str, Any]:
    """同步确认推送成功后调用：把登记的采集真正派发出去。

    此时 git push 已经完成，采集抢占资源不会再拖慢任何请求。
    """
    pending = take_pending_collect()
    if not pending or not has_pending_work(pending):
        return {"triggered": False, "reason": None}
    return dispatch_bridge_collect(root_dir, pending, execute=execute, watch=watch)
