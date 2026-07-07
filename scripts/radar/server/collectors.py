from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.radar.server import (
    COLLECTION_SCOPE_24H,
    LOCAL_HTTP_TIMEOUT_SECONDS,
    MEDIACRAWLER_24H_WINDOW_HOURS,
    MEDIACRAWLER_DOUYIN_24H_MAX_NOTES,
    MEDIACRAWLER_DOUYIN_LOG_ERR,
    MEDIACRAWLER_DOUYIN_LOG_OUT,
    MEDIACRAWLER_DOUYIN_PID,
    MEDIACRAWLER_JSONL_STALE_HOURS,
    MEDIACRAWLER_XHS_24H_MAX_NOTES,
    MEDIACRAWLER_XHS_LOG_ERR,
    MEDIACRAWLER_XHS_LOG_OUT,
    MEDIACRAWLER_XHS_PID,
    WEWE_RSS_BASE_URL_DEFAULT,
    WEWE_RSS_SIDECAR_DIR_NAME,
    WEWE_RSS_SIDECAR_LOG_ERR,
    WEWE_RSS_SIDECAR_LOG_OUT,
    normalize_collection_scope,
)
from scripts.radar.server.common import (
    add_maintenance_issue,
    dedupe_maintenance_issues,
    enabled_source_config_records,
    is_url_like,
    mediacrawler_fix_actions,
    mediacrawler_local_root,
    open_url_action,
    read_source_config,
    resolve_mediacrawler_locator,
    resolve_latest_mediacrawler_jsonl,
    source_config_runtime_ids,
    wewe_fix_actions,
)

"""Local sidecar and MediaCrawler collector helpers."""

def add_mediacrawler_jsonl_issue(
    issues: list[dict[str, Any]],
    root_dir: Path,
    source: dict[str, Any],
    runtime_id: str,
    now: datetime,
    stale_after_hours: int,
) -> None:
    locator = str(source.get("locator") or "").strip()
    source_name = str(source.get("name") or source.get("target") or source.get("id") or "MediaCrawler")
    platform = "小红书" if runtime_id == "mediacrawler_xhs" else "抖音"
    if not locator:
        add_maintenance_issue(
            issues,
            f"{runtime_id}_jsonl_missing_path",
            "bad",
            runtime_id,
            f"{platform}主页链接未配置",
            f"{source_name} 已启用，但还没有填写创作者主页链接。",
            "在订阅成员里填写创作者名称和主页链接，再启动对应平台采集。",
            mediacrawler_fix_actions(root_dir, runtime_id),
        )
        return

    configured_path = resolve_mediacrawler_locator(root_dir, runtime_id, locator)
    jsonl_path = resolve_latest_mediacrawler_jsonl(configured_path)
    if not jsonl_path.exists():
        locator_hint = "主页链接已保存，但本地还没找到该平台的 creator_contents_*.jsonl。" if is_url_like(locator) else f"配置路径没有找到文件：{configured_path}"
        add_maintenance_issue(
            issues,
            f"{runtime_id}_jsonl_not_found",
            "bad",
            runtime_id,
            f"{platform} JSONL 文件不存在",
            locator_hint,
            "先运行对应平台的 MediaCrawler 生成 JSONL；之后系统会自动读取最新结果。",
            mediacrawler_fix_actions(root_dir, runtime_id, locator),
        )
        return
    if not jsonl_path.is_file():
        add_maintenance_issue(
            issues,
            f"{runtime_id}_jsonl_not_file",
            "bad",
            runtime_id,
            f"{platform} JSONL 路径不是文件",
            f"当前路径不是可读取的 JSONL 文件：{jsonl_path}",
            "把路径改成具体的 creator_contents_*.jsonl 文件。",
            mediacrawler_fix_actions(root_dir, runtime_id, locator),
        )
        return

    stat = jsonl_path.stat()
    if stat.st_size <= 0:
        add_maintenance_issue(
            issues,
            f"{runtime_id}_jsonl_empty",
            "bad",
            runtime_id,
            f"{platform} JSONL 文件为空",
            f"{jsonl_path.name} 当前大小为 0。",
            "重新运行 MediaCrawler，确认导出的 JSONL 里有内容。",
            mediacrawler_fix_actions(root_dir, runtime_id, locator),
        )
        return

    modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    age_hours = max(0, int((now - modified_at).total_seconds() // 3600))
    if age_hours >= stale_after_hours:
        add_maintenance_issue(
            issues,
            f"{runtime_id}_jsonl_stale",
            "warn",
            runtime_id,
            f"{platform} JSONL 可能过旧",
            f"{jsonl_path.name} 上次更新约 {age_hours} 小时前。",
            "如果想看最新动态，先点对应平台的启动采集，再点读取结果。",
            mediacrawler_fix_actions(root_dir, runtime_id, locator),
        )


def is_local_http_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(value)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def check_wewe_rss_sidecar(base_url: str) -> tuple[bool, str]:
    url = base_url.rstrip("/") + "/feeds"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=LOCAL_HTTP_TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                return False, f"HTTP {response.status}"
            return True, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def read_wewe_rss_feeds(base_url: str | None = None) -> dict[str, Any]:
    resolved_base_url = (base_url or os.environ.get("WEWE_RSS_BASE_URL") or WEWE_RSS_BASE_URL_DEFAULT).strip().rstrip("/")
    if not is_local_http_url(resolved_base_url):
        return {"ok": False, "error": "wewe_rss_base_url_not_local", "base_url": resolved_base_url, "feeds": []}

    url = resolved_base_url + "/feeds"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=LOCAL_HTTP_TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                return {"ok": False, "error": f"HTTP {response.status}", "base_url": resolved_base_url, "feeds": []}
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}", "base_url": resolved_base_url, "feeds": []}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": str(exc), "base_url": resolved_base_url, "feeds": []}

    if not isinstance(payload, list):
        return {"ok": False, "error": "invalid_wewe_rss_feeds_payload", "base_url": resolved_base_url, "feeds": []}

    feeds: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        feed_id = str(item.get("id") or "").strip()
        if not feed_id or feed_id in seen:
            continue
        seen.add(feed_id)
        name = str(item.get("name") or item.get("title") or feed_id).strip() or feed_id
        feeds.append(
            {
                "id": feed_id,
                "name": name,
                "intro": str(item.get("intro") or "").strip(),
                "updateTime": item.get("updateTime"),
                "syncTime": item.get("syncTime"),
            }
        )

    return {"ok": True, "base_url": resolved_base_url, "feeds": feeds, "feed_count": len(feeds)}


def wewe_rss_sidecar_root(root_dir: Path) -> Path:
    configured = str(os.environ.get("WEWE_RSS_SIDECAR_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (root_dir.parent / WEWE_RSS_SIDECAR_DIR_NAME).resolve()


def wewe_rss_server_dir(root_dir: Path) -> Path:
    return wewe_rss_sidecar_root(root_dir) / "apps" / "server"


def wewe_rss_service_running() -> bool:
    ok, _detail = check_wewe_rss_sidecar((os.environ.get("WEWE_RSS_BASE_URL") or WEWE_RSS_BASE_URL_DEFAULT).strip().rstrip("/"))
    return ok


def start_wewe_rss_sidecar(root_dir: Path, *, execute: bool = True) -> dict[str, Any]:
    base_url = (os.environ.get("WEWE_RSS_BASE_URL") or WEWE_RSS_BASE_URL_DEFAULT).strip().rstrip("/")
    if not is_local_http_url(base_url):
        return {"ok": False, "error": "wewe_rss_base_url_not_local", "base_url": base_url}
    if wewe_rss_service_running():
        return {"ok": True, "already_running": True, "url": base_url + "/dash", "executed": False}

    server_dir = wewe_rss_server_dir(root_dir)
    entry = server_dir / "dist" / "main.js"
    if not entry.exists():
        entry = server_dir / "dist" / "main"
    if not entry.exists():
        return {"ok": False, "error": "wewe_rss_dist_not_found", "path": str(server_dir / "dist")}

    node_exe = shutil.which("node")
    if not node_exe:
        return {"ok": False, "error": "node_not_found"}
    if not execute:
        return {"ok": True, "command": [node_exe, str(entry)], "cwd": str(server_dir), "url": base_url + "/dash", "executed": False}

    env = os.environ.copy()
    env.setdefault("HOST", "127.0.0.1")
    env.setdefault("PORT", "4000")
    env.setdefault("DATABASE_TYPE", "sqlite")
    env.setdefault("DATABASE_URL", "file:../data/wewe-rss.db")
    out_log = wewe_rss_sidecar_root(root_dir) / WEWE_RSS_SIDECAR_LOG_OUT
    err_log = wewe_rss_sidecar_root(root_dir) / WEWE_RSS_SIDECAR_LOG_ERR
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with out_log.open("a", encoding="utf-8", errors="ignore") as stdout_file, err_log.open("a", encoding="utf-8", errors="ignore") as stderr_file:
        process = subprocess.Popen(
            [node_exe, str(entry)],
            cwd=server_dir,
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    return {
        "ok": True,
        "kind": "start_service",
        "action_id": "start_wewe_rss_sidecar",
        "pid": process.pid,
        "url": base_url + "/dash",
        "executed": True,
    }


def mediacrawler_python_exe(crawler_root: Path) -> str | None:
    if os.name == "nt":
        local_python = crawler_root / "venv" / "Scripts" / "python.exe"
    else:
        local_python = crawler_root / "venv" / "bin" / "python"
    if local_python.exists():
        return str(local_python)
    return shutil.which("python") or shutil.which("python3") or sys.executable


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
                check=False,
            )
        except Exception:
            return False
        return f'"{pid}"' in result.stdout or f",{pid}," in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid_file(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except Exception:
        return None


def newest_file(folder: Path, pattern: str) -> Path | None:
    if not folder.exists():
        return None
    candidates = sorted(folder.glob(pattern), key=lambda candidate: candidate.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def mediacrawler_window_summary_path(crawler_root: Path, platform: str) -> Path:
    return crawler_root / f"mediacrawler-{platform}-collection-window.json"


def normalize_douyin_creator_locator(locator: str) -> str:
    text = str(locator or "").strip()
    if not text:
        return ""
    if not is_url_like(text):
        return text
    try:
        parsed = urllib.parse.urlparse(text)
    except Exception:
        return text
    host = (parsed.netloc or "").lower()
    if not host.endswith("douyin.com"):
        return text
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "user" and parts[1].strip():
        return parts[1].strip()
    return text


def read_mediacrawler_window_summary(crawler_root: Path, platform: str, jsonl: Path | None) -> dict[str, Any] | None:
    if not jsonl:
        return None
    summary_path = mediacrawler_window_summary_path(crawler_root, platform)
    if not summary_path.exists():
        return None
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(summary, dict):
        return None
    if Path(str(summary.get("path") or "")).resolve() != jsonl.resolve():
        return None
    try:
        if summary_path.stat().st_mtime < jsonl.stat().st_mtime:
            return None
    except OSError:
        return None
    return summary


def count_file_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return sum(1 for _line in handle)
    except Exception:
        return 0


def read_tail_lines(path: Path, limit: int = 80) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
    except Exception:
        return []


def last_meaningful_mediacrawler_log(lines: list[str], platform: str) -> str:
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        if platform == "douyin" and "Douyin Crawler finished" in text:
            return "采集完成"
        if platform == "xhs" and "Xhs Crawler finished" in text:
            return "采集完成"
        if platform == "douyin" and "update_douyin_aweme" in text and "title:" in text:
            return "正在写入作品：" + text.split("title:", 1)[-1].strip()[:80]
        if platform == "xhs" and "update_xhs_note" in text and "title" in text:
            return "正在写入笔记：" + text.split("title", 1)[-1].strip(" :,'{}")[:80]
        if platform == "douyin" and "get_all_user_aweme_posts" in text and "video len" in text:
            return text.split(" - ", 1)[-1].strip()
        if platform == "xhs" and "Finished getting notes for user" in text:
            return text.split(" - ", 1)[-1].strip()
        if "Sleeping for" in text:
            return "正在逐条读取作品详情"
    return ""


def mediacrawler_collector_status(root_dir: Path, runtime_id: str) -> dict[str, Any]:
    if runtime_id == "mediacrawler_xhs":
        platform = "xhs"
        platform_name = "小红书"
        output_folder = "xhs"
        pid_file = MEDIACRAWLER_XHS_PID
        err_log = MEDIACRAWLER_XHS_LOG_ERR
    else:
        platform = "douyin"
        platform_name = "抖音"
        output_folder = "douyin"
        pid_file = MEDIACRAWLER_DOUYIN_PID
        err_log = MEDIACRAWLER_DOUYIN_LOG_ERR

    crawler_root = mediacrawler_local_root(root_dir)
    pid_path = crawler_root / pid_file
    pid = read_pid_file(pid_path)
    running = process_is_running(pid or 0)
    jsonl_candidate = resolve_latest_mediacrawler_jsonl(crawler_root / "output" / output_folder / "jsonl")
    jsonl = jsonl_candidate if jsonl_candidate.exists() and jsonl_candidate.is_file() else None
    log_lines = read_tail_lines(crawler_root / err_log)
    last_log = last_meaningful_mediacrawler_log(log_lines, platform)
    finished_marker = "Xhs Crawler finished" if platform == "xhs" else "Douyin Crawler finished"
    raw_item_count = count_file_lines(jsonl) if jsonl else 0
    item_count = raw_item_count
    collection_window_hours: int | None = None
    skipped_collection_window_items: int | None = None
    window_summary = read_mediacrawler_window_summary(crawler_root, platform, jsonl)
    if window_summary:
        collection_window_hours = int(window_summary.get("window_hours") or 0) or None
        item_count = int(window_summary.get("kept") or 0)
        skipped_collection_window_items = int(window_summary.get("skipped") or 0)
    updated_at = datetime.fromtimestamp(jsonl.stat().st_mtime, timezone.utc).isoformat() if jsonl else None
    completed_by_log = any(finished_marker in line for line in log_lines[-80:])
    completed_by_output = (
        not running
        and bool(pid)
        and pid_path.exists()
        and jsonl is not None
        and raw_item_count > 0
        and jsonl.stat().st_mtime >= pid_path.stat().st_mtime
    )
    completed = completed_by_log or completed_by_output

    if running:
        phase = "running"
        title = f"{platform_name}采集中"
        next_action = "保持采集专用窗口打开；完成后这里会变成可关闭。"
        can_close_browser = False
    elif completed and jsonl:
        phase = "completed"
        title = f"{platform_name}采集已完成"
        next_action = "可以关闭采集专用窗口；回到本页点读取结果，让主站读取新 JSONL。"
        can_close_browser = True
    elif jsonl:
        phase = "idle"
        title = f"{platform_name}采集未运行"
        next_action = f"如需最新动态，点启动{platform_name}采集。"
        can_close_browser = True
    else:
        phase = "missing"
        title = f"{platform_name}还没有采集结果"
        next_action = f"点启动{platform_name}采集，完成扫码或登录后等待写出 JSONL。"
        can_close_browser = False

    return {
        "id": runtime_id,
        "platform": platform,
        "platform_name": platform_name,
        "title": title,
        "phase": phase,
        "running": running,
        "completed": completed,
        "can_close_browser": can_close_browser,
        "pid": pid,
        "item_count": item_count,
        "raw_item_count": raw_item_count,
        "collection_window_hours": collection_window_hours,
        "skipped_collection_window_items": skipped_collection_window_items,
        "latest_file": jsonl.name if jsonl else None,
        "latest_file_path": str(jsonl) if jsonl else None,
        "updated_at": updated_at,
        "last_log": last_log,
        "next_action": next_action,
    }


def mediacrawler_creator_id(root_dir: Path, crawler_root: Path, runtime_id: str) -> str:
    if runtime_id == "mediacrawler_xhs":
        configured = str(os.environ.get("MEDIACRAWLER_XHS_CREATOR_ID") or os.environ.get("MEDIACRAWLER_XIAOHONGSHU_CREATOR_ID") or "").strip()
    else:
        configured = str(os.environ.get("MEDIACRAWLER_DOUYIN_CREATOR_ID") or "").strip()
    if configured:
        return configured

    url_locators: list[str] = []
    candidates: list[Path] = []
    try:
        config = read_source_config(root_dir)
    except Exception:
        config = None
    for source in enabled_source_config_records(config):
        if runtime_id not in source_config_runtime_ids(source):
            continue
        locator = str(source.get("locator") or "").strip()
        if is_url_like(locator):
            if runtime_id == "mediacrawler_douyin":
                locator = normalize_douyin_creator_locator(locator)
            url_locators.append(locator)
            continue
        if locator:
            candidates.append(resolve_latest_mediacrawler_jsonl(resolve_mediacrawler_locator(root_dir, runtime_id, locator)))

    if url_locators:
        return ",".join(url_locators)

    if runtime_id != "mediacrawler_xhs":
        return ""

    newest = newest_file(crawler_root / "output" / "xhs" / "jsonl", "creator_contents_*.jsonl")
    if newest:
        candidates.append(newest)

    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    user_id = str(row.get("user_id") or "").strip()
                    if user_id:
                        return f"https://www.xiaohongshu.com/user/profile/{user_id}"
        except Exception:
            continue
    return ""


def mediacrawler_xhs_creator_id(root_dir: Path, crawler_root: Path) -> str:
    return mediacrawler_creator_id(root_dir, crawler_root, "mediacrawler_xhs")


def mediacrawler_start_max_notes(platform: str, collection_scope: str) -> int | None:
    if collection_scope == COLLECTION_SCOPE_24H:
        if platform == "xhs":
            return int(os.environ.get("MEDIACRAWLER_XHS_24H_MAX_NOTES") or MEDIACRAWLER_XHS_24H_MAX_NOTES)
        return int(os.environ.get("MEDIACRAWLER_DOUYIN_24H_MAX_NOTES") or MEDIACRAWLER_DOUYIN_24H_MAX_NOTES)
    if platform == "xhs":
        return int(os.environ.get("MEDIACRAWLER_XHS_MAX_NOTES") or 500)
    return None


def start_mediacrawler_platform(
    root_dir: Path,
    runtime_id: str,
    *,
    execute: bool = True,
    collection_scope: str = COLLECTION_SCOPE_24H,
) -> dict[str, Any]:
    scope = normalize_collection_scope(collection_scope)
    platform = "xhs" if runtime_id == "mediacrawler_xhs" else "douyin"
    action_id = "start_mediacrawler_xhs" if platform == "xhs" else "start_mediacrawler_douyin"
    out_log_name = MEDIACRAWLER_XHS_LOG_OUT if platform == "xhs" else MEDIACRAWLER_DOUYIN_LOG_OUT
    err_log_name = MEDIACRAWLER_XHS_LOG_ERR if platform == "xhs" else MEDIACRAWLER_DOUYIN_LOG_ERR
    pid_name = MEDIACRAWLER_XHS_PID if platform == "xhs" else MEDIACRAWLER_DOUYIN_PID
    crawler_root = mediacrawler_local_root(root_dir)
    crawler_entry = crawler_root / "main.py"
    if not crawler_entry.exists():
        return {"ok": False, "error": "mediacrawler_main_not_found", "path": str(crawler_entry)}
    entry = root_dir / "scripts" / "run_mediacrawler_douyin.py"
    if not entry.exists():
        return {"ok": False, "error": "mediacrawler_runner_not_found", "path": str(entry)}

    python_exe = mediacrawler_python_exe(crawler_root)
    if not python_exe:
        return {"ok": False, "error": "python_not_found"}

    command = [
        python_exe,
        str(entry),
        "--crawler-root",
        str(crawler_root),
        "--platform",
        platform,
    ]
    creator_id = mediacrawler_creator_id(root_dir, crawler_root, runtime_id)
    if creator_id:
        command.extend(["--creator-id", creator_id])
    if scope == COLLECTION_SCOPE_24H:
        command.extend(["--collect-window-hours", str(MEDIACRAWLER_24H_WINDOW_HOURS)])
    max_notes = mediacrawler_start_max_notes(platform, scope)
    if max_notes:
        command.extend(["--max-notes", str(max_notes)])
    if platform == "xhs":
        if not creator_id:
            return {"ok": False, "error": "mediacrawler_xhs_creator_id_missing"}
    if not execute:
        return {
            "ok": True,
            "kind": "start_service",
            "action_id": action_id,
            "collection_scope": scope,
            "command": command,
            "cwd": str(crawler_root),
            "executed": False,
        }

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    out_log = crawler_root / out_log_name
    err_log = crawler_root / err_log_name
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with out_log.open("a", encoding="utf-8", errors="ignore") as stdout_file, err_log.open("a", encoding="utf-8", errors="ignore") as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=crawler_root,
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    (crawler_root / pid_name).write_text(str(process.pid), encoding="utf-8")
    return {
        "ok": True,
        "kind": "start_service",
        "action_id": action_id,
        "collection_scope": scope,
        "pid": process.pid,
        "executed": True,
    }


def mediacrawler_douyin_collector_status(root_dir: Path) -> dict[str, Any]:
    return mediacrawler_collector_status(root_dir, "mediacrawler_douyin")


def mediacrawler_xhs_collector_status(root_dir: Path) -> dict[str, Any]:
    return mediacrawler_collector_status(root_dir, "mediacrawler_xhs")


def start_mediacrawler_douyin(
    root_dir: Path,
    *,
    execute: bool = True,
    collection_scope: str = COLLECTION_SCOPE_24H,
) -> dict[str, Any]:
    return start_mediacrawler_platform(
        root_dir,
        "mediacrawler_douyin",
        execute=execute,
        collection_scope=collection_scope,
    )


def start_mediacrawler_xhs(
    root_dir: Path,
    *,
    execute: bool = True,
    collection_scope: str = COLLECTION_SCOPE_24H,
) -> dict[str, Any]:
    return start_mediacrawler_platform(
        root_dir,
        "mediacrawler_xhs",
        execute=execute,
        collection_scope=collection_scope,
    )


def add_wewe_rss_config_issues(
    issues: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    probe_network: bool,
) -> None:
    wewe_sources = [source for source in sources if "wewe_rss" in source_config_runtime_ids(source)]
    if not wewe_sources:
        return

    missing_feed_sources = [
        str(source.get("name") or source.get("target") or source.get("id") or "未命名公众号")
        for source in wewe_sources
        if not str(source.get("locator") or "").strip()
    ]
    if missing_feed_sources:
        add_maintenance_issue(
            issues,
            "wewe_rss_feed_id_missing",
            "bad",
            "wewe_rss",
            "公众号 feed id 未配置",
            f"缺少 feed id：{'、'.join(missing_feed_sources[:3])}",
            "在 WeWe RSS 后台找到对应公众号 feed id，并填到该信源的地址 / ID / 路径。",
            wewe_fix_actions(),
        )

    base_url = (os.environ.get("WEWE_RSS_BASE_URL") or WEWE_RSS_BASE_URL_DEFAULT).strip().rstrip("/")
    if not is_local_http_url(base_url):
        add_maintenance_issue(
            issues,
            "wewe_rss_sidecar_probe_skipped",
            "warn",
            "wewe_rss",
            "WeWe RSS 不是本地地址",
            f"当前 WEWE_RSS_BASE_URL={base_url}，本地工具已跳过 HTTP 探测。",
            "如果这是你有意配置的远程服务，请手动确认它能访问；本地面板只自动探测 localhost/127.0.0.1。",
            [open_url_action("open_wewe_rss_dashboard", "打开后台", base_url + "/dash")] if base_url.startswith(("http://", "https://")) else [],
        )
        return
    if not probe_network:
        return

    ok, detail = check_wewe_rss_sidecar(base_url)
    if not ok:
        add_maintenance_issue(
            issues,
            "wewe_rss_sidecar_unreachable",
            "bad",
            "wewe_rss",
            "WeWe RSS 本地服务不可用",
            f"{base_url}/feeds 访问失败：{detail}",
            "先启动 wewe-rss-sidecar；如果后台要求重新扫码，先完成扫码登录，再回到本页面检查状态。",
            wewe_fix_actions(include_start=True),
        )


def local_config_maintenance_issues(
    root_dir: Path,
    config: dict[str, Any] | None,
    *,
    probe_network: bool = True,
    now: datetime | None = None,
    stale_after_hours: int = MEDIACRAWLER_JSONL_STALE_HOURS,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    current_time = now or datetime.now(timezone.utc)
    sources = enabled_source_config_records(config)
    for source in sources:
        runtime_ids = source_config_runtime_ids(source)
        for runtime_id in sorted(runtime_ids & {"mediacrawler_douyin", "mediacrawler_xhs"}):
            add_mediacrawler_jsonl_issue(issues, root_dir, source, runtime_id, current_time, stale_after_hours)
    add_wewe_rss_config_issues(issues, sources, probe_network)
    return dedupe_maintenance_issues(issues)



