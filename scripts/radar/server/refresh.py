from __future__ import annotations

from scripts.radar.server import *  # noqa: F401,F403

"""Refresh orchestration and local maintenance actions."""

def json_response(handler: SimpleHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def restart_command() -> list[str]:
    return [sys.executable, *sys.argv]


def schedule_process_restart(command: list[str], cwd: Path, delay_seconds: float = RESTART_DELAY_SECONDS) -> None:
    def restart_worker() -> None:
        helper_code = (
            "import json, os, subprocess, sys, time\n"
            "command = json.loads(sys.argv[1])\n"
            "cwd = sys.argv[2]\n"
            "delay = float(sys.argv[3])\n"
            "time.sleep(delay)\n"
            "creationflags = 0\n"
            "if os.name == 'nt':\n"
            "    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS\n"
            "out = open(os.path.join(cwd, 'server.out.log'), 'a', encoding='utf-8')\n"
            "err = open(os.path.join(cwd, 'server.err.log'), 'a', encoding='utf-8')\n"
            "subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, close_fds=True, creationflags=creationflags)\n"
        )
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        try:
            subprocess.Popen(
                [sys.executable, "-c", helper_code, json.dumps(command), str(cwd), str(delay_seconds)],
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
            )
        finally:
            time.sleep(0.2)
            os._exit(0)

    threading.Thread(target=restart_worker).start()


def is_local_origin(value: str) -> bool:
    if not value:
        return True
    return value.startswith("http://127.0.0.1:") or value.startswith("http://localhost:")


def normalize_collection_scope(raw_scope: Any) -> str:
    scope = str(raw_scope or COLLECTION_SCOPE_24H).strip().lower()
    if scope in {"24h", "24", "last_24h", "last-24h", "rolling_window"}:
        return COLLECTION_SCOPE_24H
    if scope in {"all", "all_time", "all-time", "full"}:
        return COLLECTION_SCOPE_ALL
    raise ValueError("unsupported_collection_scope")


def last_collection_time(root_dir: Path) -> datetime | None:
    status = read_source_status(root_dir)
    if not isinstance(status, dict):
        return None
    raw = str(status.get("generated_at") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def resolve_collect_window_hours(
    scope: str,
    last_collected_at: datetime | None,
    now: datetime,
    *,
    default_hours: int = 24,
) -> int:
    if scope == COLLECTION_SCOPE_ALL:
        return 0
    if last_collected_at is None:
        return default_hours
    seconds = (now - last_collected_at).total_seconds()
    if seconds <= 0:
        return default_hours
    return max(1, math.ceil(seconds / 3600))


def collect_window_hours_for_scope(
    root_dir: Path,
    scope: str,
    *,
    now: datetime | None = None,
) -> int:
    current_time = now or datetime.now(timezone.utc)
    return resolve_collect_window_hours(scope, last_collection_time(root_dir), current_time)


def refresh_command(
    root_dir: Path,
    collection_scope: str = COLLECTION_SCOPE_24H,
    *,
    now: datetime | None = None,
) -> list[str]:
    scope = normalize_collection_scope(collection_scope)
    command = [
        sys.executable,
        str(root_dir / "scripts" / "update_news.py"),
        "--source-config",
        CONFIG_FILENAME,
        "--output-dir",
        "data",
        "--window-hours",
        "24",
        "--archive-days",
        "3650",
        "--all-time",
    ]
    window_hours = collect_window_hours_for_scope(root_dir, scope, now=now)
    if window_hours > 0:
        command.extend(["--collect-window-hours", str(window_hours)])
    return command


def refresh_env(root_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    cookie_status = bilibili_cookie_status(root_dir)
    if (
        cookie_status.get("cookie_file_exists")
        and not str(env.get("BILIBILI_COOKIE_FILE") or env.get("BILIBILI_DYNAMIC_COOKIE_FILE") or "").strip()
        and not str(env.get("BILIBILI_COOKIE") or env.get("BILIBILI_DYNAMIC_COOKIE") or "").strip()
    ):
        env["BILIBILI_COOKIE_FILE"] = str(cookie_status["cookie_file"])
    return env


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def refresh_progress_snapshot() -> dict[str, Any]:
    with REFRESH_PROGRESS_LOCK:
        snapshot = dict(REFRESH_PROGRESS)
        snapshot["log"] = list(REFRESH_PROGRESS.get("log") or [])
        snapshot["steps"] = list(REFRESH_PROGRESS.get("steps") or [])
        return snapshot


def update_refresh_progress(**updates: Any) -> dict[str, Any]:
    with REFRESH_PROGRESS_LOCK:
        REFRESH_PROGRESS.update(updates)
        REFRESH_PROGRESS["updated_at"] = now_iso()
        if "log" in REFRESH_PROGRESS:
            REFRESH_PROGRESS["log"] = list(REFRESH_PROGRESS.get("log") or [])[-12:]
        return dict(REFRESH_PROGRESS)


def append_refresh_progress(message: str, *, percent: int | None = None, current_step: str | None = None, status: str | None = None) -> None:
    with REFRESH_PROGRESS_LOCK:
        log = list(REFRESH_PROGRESS.get("log") or [])
        log.append({"time": now_iso(), "message": message})
        REFRESH_PROGRESS["log"] = log[-12:]
        if percent is not None:
            REFRESH_PROGRESS["percent"] = max(0, min(100, int(percent)))
        if current_step is not None:
            REFRESH_PROGRESS["current_step"] = current_step
        if status is not None:
            REFRESH_PROGRESS["status"] = status
        REFRESH_PROGRESS["updated_at"] = now_iso()


def refresh_step_plan(source_config: dict[str, Any] | None) -> list[str]:
    labels: list[str] = []
    site_ids: set[str] = set()
    for source in enabled_source_config_records(source_config):
        site_ids.update(source_config_runtime_ids(source))
    ordered = [
        ("opmlrss", "YouTube 订阅"),
        ("bilibili_dynamic", "B站动态订阅"),
        ("mediacrawler_douyin", "读取抖音采集结果"),
        ("mediacrawler_xhs", "读取小红书采集结果"),
        ("wewe_rss", "微信公众号订阅"),
        ("github_foundation_sunshine_releases", "GitHub Release"),
    ]
    for site_id, label in ordered:
        if site_id in site_ids:
            labels.append(label)
    if not labels:
        labels.append("订阅源")
    labels.append("合并并生成看板数据")
    return labels


def begin_refresh_progress(collection_scope: str, steps: list[str]) -> None:
    first_step = steps[0] if steps else "准备刷新"
    update_refresh_progress(
        running=True,
        status="running",
        percent=3,
        collection_scope=collection_scope,
        current_step=f"准备：{first_step}",
        steps=steps,
        log=[{"time": now_iso(), "message": f"开始刷新，准备处理 {first_step}"}],
        started_at=now_iso(),
        finished_at="",
        error="",
        returncode=None,
    )


def run_refresh_background(root_dir: Path, collection_scope: str, command: list[str], steps: list[str]) -> None:
    begin_refresh_progress(collection_scope, steps)
    started = time.monotonic()
    process: subprocess.Popen[str] | None = None
    last_step_index = -1
    stdout_tail = ""
    stderr_tail = ""
    try:
        process = subprocess.Popen(
            command,
            cwd=root_dir,
            env=refresh_env(root_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        estimated_seconds = max(45, len(steps) * 10)
        while process.poll() is None:
            elapsed = time.monotonic() - started
            if elapsed > REFRESH_TIMEOUT_SECONDS:
                process.kill()
                stdout, stderr = process.communicate()
                stdout_tail = (stdout or "")[-2000:]
                stderr_tail = (stderr or "")[-4000:]
                raise subprocess.TimeoutExpired(command, REFRESH_TIMEOUT_SECONDS, output=stdout_tail, stderr=stderr_tail)
            percent = min(92, 5 + int((elapsed / estimated_seconds) * 82))
            step_index = min(max(0, int((percent / 100) * max(1, len(steps)))), max(0, len(steps) - 1))
            if step_index != last_step_index:
                if last_step_index >= 0 and last_step_index < len(steps):
                    append_refresh_progress(f"{steps[last_step_index]}处理结束")
                current = steps[step_index] if steps else "刷新看板数据"
                append_refresh_progress(f"正在处理 {current}", percent=percent, current_step=current)
                last_step_index = step_index
            else:
                current = steps[step_index] if steps else "刷新看板数据"
                update_refresh_progress(percent=percent, current_step=current)
            time.sleep(2)
        stdout, stderr = process.communicate()
        stdout_tail = (stdout or "")[-2000:]
        stderr_tail = (stderr or "")[-4000:]
        if process.returncode != 0:
            update_refresh_progress(
                running=False,
                status="failed",
                percent=100,
                current_step="刷新失败",
                finished_at=now_iso(),
                error="refresh_failed",
                returncode=process.returncode,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )
            append_refresh_progress("刷新失败，请查看错误信息", status="failed")
            return
        append_refresh_progress("看板数据生成完成", percent=100, current_step="刷新完成", status="completed")
        update_refresh_progress(
            running=False,
            status="completed",
            percent=100,
            finished_at=now_iso(),
            error="",
            returncode=0,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )
    except subprocess.TimeoutExpired as exc:
        update_refresh_progress(
            running=False,
            status="failed",
            percent=100,
            current_step="刷新超时",
            finished_at=now_iso(),
            error="refresh_timeout",
            stdout_tail=(exc.stdout or "")[-2000:],
            stderr_tail=(exc.stderr or "")[-4000:],
        )
        append_refresh_progress("刷新超时", status="failed")
    except Exception as exc:
        update_refresh_progress(
            running=False,
            status="failed",
            percent=100,
            current_step="刷新失败",
            finished_at=now_iso(),
            error=str(exc),
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )
        append_refresh_progress(f"刷新失败：{exc}", status="failed")
    finally:
        REFRESH_LOCK.release()


def collector_no_new_in_collection_window(collector: dict[str, Any] | None) -> bool:
    if not isinstance(collector, dict):
        return False
    collection_window_hours = int(collector.get("collection_window_hours") or 0)
    raw_item_count = int(collector.get("raw_item_count") or 0)
    item_count = int(collector.get("item_count") or 0)
    return bool(collector.get("completed")) and collection_window_hours > 0 and raw_item_count > 0 and item_count == 0


def suppress_collector_window_no_new_issues(
    issues: list[dict[str, Any]],
    collectors: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not collectors:
        return issues
    filtered: list[dict[str, Any]] = []
    for issue in issues:
        source_id = str(issue.get("source_id") or "")
        detail = str(issue.get("detail") or "")
        if (
            source_id in collectors
            and issue.get("severity") == "bad"
            and "no_items" in detail
            and collector_no_new_in_collection_window(collectors.get(source_id))
        ):
            continue
        filtered.append(issue)
    return filtered


def source_status_summary(
    root_dir: Path,
    source_config: dict[str, Any] | None = None,
    collectors: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config_issues = local_config_maintenance_issues(root_dir, source_config) if source_config else []
    payload = read_source_status(root_dir)
    if not payload:
        issues = dedupe_maintenance_issues(
            [
                {
                    "id": "source_status_missing",
                    "severity": "warn",
                    "source_id": "source_status",
                    "title": "还没有刷新状态",
                    "detail": "data/source-status.json 不存在或还没生成。",
                    "action": "先点一次读取结果，生成本地源状态。",
                },
                *config_issues,
            ]
        )
        return {
            "maintenance_issues": issues,
            "issue_count": len(issues),
            "needs_attention": True,
        }
    issues = dedupe_maintenance_issues([*maintenance_issues_from_status(payload, root_dir), *config_issues])
    issues = suppress_collector_window_no_new_issues(issues, collectors)
    ok_sites = sum(1 for site in payload.get("sites", []) if isinstance(site, dict) and site.get("ok") is True)
    return {
        "generated_at": payload.get("generated_at"),
        "source_scope": payload.get("source_scope"),
        "fetched_raw_items": payload.get("fetched_raw_items"),
        "collection_window_hours": payload.get("collection_window_hours"),
        "raw_items_before_collection_window": payload.get("raw_items_before_collection_window"),
        "skipped_collection_window_items": payload.get("skipped_collection_window_items"),
        "successful_sites": payload.get("successful_sites", ok_sites),
        "site_count": len(payload.get("sites", [])),
        "issue_count": len(issues),
        "needs_attention": bool(issues),
        "maintenance_issues": issues,
        "sites": [
            {
                "site_id": site.get("site_id"),
                "site_name": site.get("site_name"),
                "ok": site.get("ok"),
                "item_count": site.get("item_count"),
                "raw_item_count": site.get("raw_item_count"),
                "window_item_count": site.get("window_item_count"),
                "collection_window_hours": site.get("collection_window_hours"),
                "max_items": site.get("max_items"),
                "max_items_per_feed": site.get("max_items_per_feed"),
                "max_items_per_account": site.get("max_items_per_account"),
                "source_name": site.get("source_name"),
                "error": site.get("error"),
                "cookie_present": site.get("cookie_present"),
                "fetch_mode": site.get("fetch_mode"),
            }
            for site in payload.get("sites", [])
            if isinstance(site, dict)
        ],
        "bilibili_cookie": bilibili_cookie_status(root_dir),
    }


def source_config_summary_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"exists": False, "source_count": 0, "enabled_source_count": 0, "enabled_sources": []}
    sources = [source for source in payload.get("sources", []) if isinstance(source, dict)]
    enabled = [source for source in sources if source.get("enabled") is not False]
    return {
        "exists": True,
        "source_count": len(sources),
        "enabled_source_count": len(enabled),
        "updated_at": payload.get("updated_at"),
        "enabled_sources": [
            {
                "id": source.get("id"),
                "name": source.get("name"),
                "type": source.get("type"),
                "channel": source.get("channel"),
                "target": source.get("target"),
            }
            for source in enabled[:50]
        ],
    }


def source_config_summary(root_dir: Path) -> dict[str, Any]:
    return source_config_summary_from_payload(read_source_config(root_dir))


def local_status_payload(root_dir: Path) -> dict[str, Any]:
    config_payload: dict[str, Any] | None = None
    try:
        config_payload = read_source_config(root_dir)
        config = source_config_summary_from_payload(config_payload)
    except Exception as exc:
        config = {"exists": True, "ok": False, "error": str(exc), "source_count": 0, "enabled_source_count": 0, "enabled_sources": []}
    collectors = {
        "mediacrawler_douyin": mediacrawler_douyin_collector_status(root_dir),
        "mediacrawler_xhs": mediacrawler_xhs_collector_status(root_dir),
    }
    summary = source_status_summary(root_dir, config_payload, collectors)
    if config.get("ok") is False:
        issues = dedupe_maintenance_issues(
            [
                *summary.get("maintenance_issues", []),
                {
                    "id": "source_config_invalid",
                    "severity": "bad",
                    "source_id": "source_config",
                    "title": "sources.config.json 读取失败",
                    "detail": str(config.get("error") or "配置文件格式不正确。"),
                    "action": "在页面里重新写入配置，或检查 sources.config.json 是否是合法 JSON。",
                },
            ]
        )
        summary["maintenance_issues"] = issues
        summary["issue_count"] = len(issues)
        summary["needs_attention"] = True
    return {
        "ok": True,
        "source_config": config,
        "source_status": summary,
        "collectors": collectors,
        "refresh_running": REFRESH_LOCK.locked(),
        "refresh_progress": refresh_progress_snapshot(),
    }


def maintenance_actions_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    issues = payload.get("source_status", {}).get("maintenance_issues", [])
    if not isinstance(issues, list):
        return actions
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        for action in issue.get("fix_actions") or []:
            if not isinstance(action, dict):
                continue
            action_id = str(action.get("id") or "")
            if not action_id or action_id in seen:
                continue
            seen.add(action_id)
            actions.append(action)
    return actions


def find_maintenance_action(root_dir: Path, action_id: str) -> dict[str, Any] | None:
    action_id = str(action_id or "").strip()
    if not action_id:
        return None
    for action in maintenance_actions_from_payload(local_status_payload(root_dir)):
        if action.get("id") == action_id:
            return action
    return None


def launch_open_path(target: Path) -> None:
    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def perform_maintenance_action(
    root_dir: Path,
    action_id: str,
    *,
    execute: bool = True,
    collection_scope: str = COLLECTION_SCOPE_24H,
) -> dict[str, Any]:
    scope = normalize_collection_scope(collection_scope)
    fixed_start_actions = {
        "start_mediacrawler_douyin": start_mediacrawler_douyin,
        "start_mediacrawler_xhs": start_mediacrawler_xhs,
    }
    direct_start_action = fixed_start_actions.get(str(action_id or "").strip())
    if direct_start_action:
        return direct_start_action(root_dir, execute=execute, collection_scope=scope)

    action = find_maintenance_action(root_dir, action_id)
    if not action:
        return {"ok": False, "error": "maintenance_action_not_found"}

    kind = str(action.get("kind") or "")
    if kind == "open_path":
        raw_path = str(action.get("path") or "").strip()
        if not raw_path:
            return {"ok": False, "error": "maintenance_action_path_missing"}
        if action.get("id") == "open_bilibili_cookie_folder":
            target = (root_dir / BILIBILI_DEFAULT_COOKIE_FILE.parent).resolve()
            target.mkdir(parents=True, exist_ok=True)
            if execute:
                launch_open_path(target)
            return {
                "ok": True,
                "kind": kind,
                "action_id": action.get("id"),
                "label": action.get("label"),
                "opened_path": str(target),
                "recommended_cookie_file": str(root_dir / BILIBILI_DEFAULT_COOKIE_FILE),
                "executed": execute,
            }
        target = existing_open_target(Path(raw_path))
        if not target:
            return {"ok": False, "error": "maintenance_action_path_not_found", "path": raw_path}
        if execute:
            launch_open_path(target)
        return {
            "ok": True,
            "kind": kind,
            "action_id": action.get("id"),
            "label": action.get("label"),
            "opened_path": str(target),
            "executed": execute,
        }
    if kind == "open_url":
        return {
            "ok": True,
            "kind": kind,
            "action_id": action.get("id"),
            "label": action.get("label"),
            "url": action.get("url"),
            "executed": False,
        }
    if kind == "start_service":
        action_id = str(action.get("id") or "")
        if action_id == "open_bilibili_login":
            return launch_bilibili_dedicated_browser(root_dir, execute=execute)
        if action_id == "sync_bilibili_cookie":
            return sync_bilibili_cookie(root_dir, execute=execute)
        if action_id == "start_wewe_rss_sidecar":
            return start_wewe_rss_sidecar(root_dir, execute=execute)
        if action_id == "start_mediacrawler_douyin":
            return start_mediacrawler_douyin(root_dir, execute=execute, collection_scope=scope)
        if action_id == "start_mediacrawler_xhs":
            return start_mediacrawler_xhs(root_dir, execute=execute, collection_scope=scope)
        return {"ok": False, "error": "unsupported_start_service", "action_id": action_id}
    return {"ok": False, "error": "unsupported_maintenance_action", "kind": kind}



