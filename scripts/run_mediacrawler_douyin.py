#!/usr/bin/env python3
"""Launch MediaCrawler creator crawling through an isolated local Chrome profile."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

DOUYIN_HOME_URL = "https://www.douyin.com/"
XIAOHONGSHU_HOME_URL = "https://www.xiaohongshu.com/explore"
DEFAULT_CDP_PORT = 9333
CDP_WAIT_SECONDS = 30
JSONL_FUTURE_SKEW_SECONDS = 300
COLLECTION_LOCK_PATH = Path(tempfile.gettempdir()) / "ai-news-radar-mediacrawler.pipeline.lock"
COLLECTION_OWNER_PATH = Path(tempfile.gettempdir()) / "ai-news-radar-mediacrawler.pipeline.owner.json"
COLLECTION_LOCK_TOKEN_ENV = "AI_NEWS_RADAR_COLLECTION_LOCK_TOKEN"
PUBLISH_TIME_FIELDS = (
    "create_time",
    "create_timestamp",
    "publish_time",
    "time",
    "last_update_time",
    "published_at",
)


def protect_local_cdp_from_proxy() -> None:
    local_hosts = ("localhost", "127.0.0.1", "::1")
    for key in ("NO_PROXY", "no_proxy"):
        existing = [part.strip() for part in os.environ.get(key, "").split(",") if part.strip()]
        lowered = {part.lower() for part in existing}
        for host in local_hosts:
            if host.lower() not in lowered:
                existing.append(host)
        os.environ[key] = ",".join(existing)

    for key in ("ALL_PROXY", "all_proxy"):
        value = os.environ.get(key, "")
        if value.lower().startswith("socks"):
            os.environ.pop(key, None)


def collection_window_summary_path(crawler_root: Path, platform: str) -> Path:
    return crawler_root / f"mediacrawler-{platform}-collection-window.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start MediaCrawler creator mode with a dedicated CDP browser.")
    parser.add_argument("--crawler-root", required=True)
    parser.add_argument("--platform", choices=("douyin", "xhs"), default=os.environ.get("MEDIACRAWLER_PLATFORM") or "douyin")
    parser.add_argument("--creator-id", default=os.environ.get("MEDIACRAWLER_CREATOR_ID") or "")
    parser.add_argument("--max-notes", type=int, default=0)
    parser.add_argument("--collect-window-hours", type=int, default=0)
    parser.add_argument("--cdp-port", type=int, default=0)
    parser.add_argument("--chrome-path", default=os.environ.get("MEDIACRAWLER_CHROME_PATH") or "")
    parser.add_argument("--profile-dir", default=os.environ.get("MEDIACRAWLER_PROFILE_DIR") or "")
    parser.add_argument("--offscreen", action="store_true", help="把采集专用浏览器移到屏幕外；计划任务专用")
    parser.add_argument("--browser-only", action="store_true", help="只启动/切换采集专用浏览器，不执行采集或推送")
    parser.add_argument("--run-id", default="", help=argparse.SUPPRESS)
    parser.add_argument("--result-file", default="", help=argparse.SUPPRESS)
    parser.add_argument("--parent-holds-collection-lock", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def parse_jsonl_publish_time(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp <= 0:
            return None
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_jsonl_publish_time(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def row_publish_time(row: dict[str, object]) -> datetime | None:
    for field in PUBLISH_TIME_FIELDS:
        parsed = parse_jsonl_publish_time(row.get(field))
        if parsed:
            return parsed
    return None


def newest_creator_jsonl(crawler_root: Path, platform: str) -> Path | None:
    jsonl_dir = crawler_root / "output" / platform / "jsonl"
    if not jsonl_dir.exists():
        return None
    files = list(jsonl_dir.glob("creator_contents_*.jsonl"))
    if not files:
        return None
    return max(files, key=lambda path: (path.stat().st_mtime, path.name))


def summarize_creator_jsonl_by_window(
    crawler_root: Path,
    platform: str,
    window_hours: int,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    if window_hours <= 0:
        return {"ok": True, "skipped": True, "reason": "window_disabled"}
    path = newest_creator_jsonl(crawler_root, platform)
    if not path:
        return {"ok": False, "error": "creator_jsonl_not_found"}

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = now - timedelta(hours=window_hours)
    end = now + timedelta(seconds=JSONL_FUTURE_SKEW_SECONDS)
    total = 0
    kept = 0
    skipped = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            raw_line = line.strip()
            if not raw_line:
                continue
            total += 1
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(row, dict):
                skipped += 1
                continue
            published = row_publish_time(row)
            if not published or published < start or published > end:
                skipped += 1
                continue
            kept += 1

    summary = {
        "ok": True,
        "path": str(path),
        "file": path.name,
        "generated_at": now.isoformat(),
        "window_hours": window_hours,
        "total": total,
        "kept": kept,
        "skipped": skipped,
    }
    summary_path = collection_window_summary_path(crawler_root, platform)
    tmp_path = summary_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, summary_path)
    summary["summary_path"] = str(summary_path)
    return summary


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def cdp_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.0) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def find_chrome(chrome_path: str) -> str:
    if chrome_path and Path(chrome_path).is_file():
        return chrome_path
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError("Chrome/Edge executable not found")


def dedicated_browser_args(
    chrome_path: str,
    port: int,
    profile_dir: Path,
    start_url: str,
    offscreen: bool,
) -> list[str]:
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-crash-restore-bubble",
        "--disable-sync",
        "--disable-features=TranslateUI",
        "--disable-blink-features=AutomationControlled",
    ]
    if offscreen:
        args += ["--window-position=-32000,-32000", "--window-size=1600,900"]
    else:
        args.append("--start-maximized")
    args.append(start_url)
    return args


def launch_dedicated_browser(
    chrome_path: str,
    port: int,
    profile_dir: Path,
    start_url: str,
    offscreen: bool = False,
) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = dedicated_browser_args(chrome_path, port, profile_dir, start_url, offscreen)
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, close_fds=True, creationflags=creationflags)


def virtual_screen_bounds(metric_getter: Callable[[int], int] | None = None) -> dict[str, int]:
    if metric_getter is None:
        if os.name != "nt":
            raise RuntimeError("virtual_screen_metrics_unavailable")
        import ctypes

        metric_getter = ctypes.windll.user32.GetSystemMetrics
    left = int(metric_getter(76))
    top = int(metric_getter(77))
    width = int(metric_getter(78))
    height = int(metric_getter(79))
    if width <= 0 or height <= 0:
        raise RuntimeError("invalid_virtual_screen_bounds")
    return {"left": left, "top": top, "width": width, "height": height}


def rectangles_intersect(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_left = int(first.get("left", 0))
    first_top = int(first.get("top", 0))
    first_right = first_left + int(first.get("width", 0))
    first_bottom = first_top + int(first.get("height", 0))
    second_left = int(second.get("left", 0))
    second_top = int(second.get("top", 0))
    second_right = second_left + int(second.get("width", 0))
    second_bottom = second_top + int(second.get("height", 0))
    return first_left < second_right and first_right > second_left and first_top < second_bottom and first_bottom > second_top


def browser_window_commands(offscreen: bool, screen: dict[str, int]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = [{"windowState": "normal"}]
    if offscreen:
        commands.append(
            {
                "left": int(screen["left"]) - 1700,
                "top": int(screen["top"]),
                "width": 1600,
                "height": 900,
            }
        )
    else:
        commands.extend(
            [
                {"left": 80, "top": 80, "width": 1600, "height": 900},
                {"windowState": "maximized"},
            ]
        )
    return commands


def assert_window_mode_result(actual: dict[str, Any], screen: dict[str, Any], offscreen: bool) -> None:
    intersects = rectangles_intersect(actual, screen)
    if offscreen and intersects:
        raise RuntimeError(f"offscreen_window_still_intersects_virtual_screen:{actual}")
    if not offscreen and not intersects:
        raise RuntimeError(f"visible_window_does_not_intersect_virtual_screen:{actual}")


def window_bounds_match_request(actual: dict[str, Any], requested: dict[str, Any]) -> bool:
    if "windowState" in requested and actual.get("windowState") != requested["windowState"]:
        return False
    for key in ("left", "top", "width", "height"):
        if key in requested and int(actual.get(key, -1)) != int(requested[key]):
            return False
    return True


async def set_window_bounds_with_retry(
    session: Any,
    window_id: int,
    requested: dict[str, Any],
    *,
    attempts: int = 20,
    delay_seconds: float = 0.1,
) -> dict[str, Any]:
    actual: dict[str, Any] = {}
    for attempt in range(attempts):
        await session.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": requested})
        actual = (await session.send("Browser.getWindowBounds", {"windowId": window_id})).get("bounds") or {}
        if window_bounds_match_request(actual, requested):
            return actual
        if attempt + 1 < attempts:
            await asyncio.sleep(delay_seconds)
    raise RuntimeError(f"browser_window_bounds_not_applied:requested={requested}:actual={actual}")


async def set_dedicated_browser_window_mode(
    port: int,
    offscreen: bool,
    *,
    virtual_bounds_getter: Callable[[], dict[str, int]] = virtual_screen_bounds,
) -> None:
    from playwright.async_api import async_playwright

    screen = virtual_bounds_getter()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        try:
            if not browser.contexts:
                raise RuntimeError("dedicated_browser_has_no_context")
            context = browser.contexts[0]
            if not context.pages:
                raise RuntimeError("dedicated_browser_has_no_page")
            page = context.pages[0]
            session = await context.new_cdp_session(page)
            target = await session.send("Browser.getWindowForTarget")
            window_id = target.get("windowId")
            if window_id is None:
                raise RuntimeError("dedicated_browser_window_id_missing")
            actual: dict[str, Any] = {}
            for bounds in browser_window_commands(offscreen, screen):
                actual = await set_window_bounds_with_retry(session, window_id, bounds)
            assert_window_mode_result(actual, screen, offscreen)
        finally:
            await browser.close()


def apply_dedicated_browser_window_mode(port: int, offscreen: bool) -> None:
    asyncio.run(set_dedicated_browser_window_mode(port, offscreen))


async def douyin_login_state(port: int) -> str:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        try:
            if not browser.contexts:
                return "unknown"
            context = browser.contexts[0]
            storage_value: object = None
            for page in context.pages:
                if "douyin.com" not in page.url:
                    continue
                try:
                    storage_value = await page.evaluate("() => localStorage.getItem('HasUserLogin')")
                except Exception:
                    storage_value = None
                if str(storage_value or "").strip().lower() not in {"", "0", "false", "none", "null"}:
                    return "logged_in"
            cookies = await context.cookies("https://www.douyin.com")
            if any(cookie.get("name") == "LOGIN_STATUS" and str(cookie.get("value") or "").strip() for cookie in cookies):
                return "logged_in"
            return "login_required"
        finally:
            await browser.close()


def check_douyin_login_state(port: int) -> str:
    return asyncio.run(douyin_login_state(port))


def listener_processes_windows(port: int) -> list[dict[str, Any]]:
    if os.name != "nt":
        raise RuntimeError("cdp_port_conflict: listener identity lookup is Windows-only")
    script = (
        "$ErrorActionPreference='Stop';"
        f"$connections=@(Get-NetTCPConnection -State Listen -LocalPort {int(port)} -ErrorAction SilentlyContinue);"
        "$ownerPids=@($connections|Select-Object -ExpandProperty OwningProcess -Unique);"
        "$rows=@($ownerPids|ForEach-Object{$ownerPid=$_;$process=Get-CimInstance Win32_Process -Filter \"ProcessId=$ownerPid\";"
        "if($process){[pscustomobject]@{pid=[int]$ownerPid;command_line=[string]$process.CommandLine}}});"
        "$rows|ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError("cdp_port_conflict: listener command line is unreadable")
    raw = completed.stdout.strip()
    if not raw:
        return []
    value = json.loads(raw)
    return value if isinstance(value, list) else [value]


def normalized_path_text(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).expanduser().resolve(strict=False))).rstrip("\\/")


def assert_dedicated_browser_process(
    port: int,
    profile_dir: Path,
    process_lookup: Callable[[int], list[dict[str, Any]]] = listener_processes_windows,
) -> int:
    rows = process_lookup(port)
    unique = {int(row.get("pid", 0)): row for row in rows if int(row.get("pid", 0)) > 0}
    if len(unique) != 1:
        raise RuntimeError("cdp_port_conflict: listener PID is not unique")
    pid, row = next(iter(unique.items()))
    command_line = str(row.get("command_line") or "")
    if not command_line:
        raise RuntimeError("cdp_port_conflict: listener command line is unreadable")
    if not re.search(rf"(?:^|\s|\")--remote-debugging-port={int(port)}(?:\s|\"|$)", command_line, re.IGNORECASE):
        raise RuntimeError("cdp_port_conflict: listener is not the expected CDP browser")
    match = re.search(
        r"--user-data-dir=(?:\"([^\"]+)\"|([^\"\r\n]+?))(?=(?:\"(?:\s|$)|\s--|$))",
        command_line,
        re.IGNORECASE,
    )
    actual_profile = (match.group(1) or match.group(2)).strip().strip('"') if match else ""
    if not actual_profile or normalized_path_text(actual_profile) != normalized_path_text(profile_dir):
        raise RuntimeError("cdp_port_conflict: listener uses a different browser profile")
    return pid


async def limited_douyin_creator_posts(client: object, sec_user_id: str, max_notes: int, callback: object = None) -> list[dict]:
    posts_has_more = 1
    max_cursor = ""
    result: list[dict] = []
    while posts_has_more == 1 and len(result) < max_notes:
        aweme_post_res = await client.get_user_aweme_posts(sec_user_id, max_cursor)  # type: ignore[attr-defined]
        posts_has_more = aweme_post_res.get("has_more", 0)
        max_cursor = aweme_post_res.get("max_cursor")
        aweme_list = aweme_post_res.get("aweme_list") if aweme_post_res.get("aweme_list") else []
        if not aweme_list:
            break
        remaining = max_notes - len(result)
        limited_list = aweme_list[:remaining]
        if callback and limited_list:
            await callback(limited_list)  # type: ignore[misc]
        result.extend(limited_list)
    return result


def ensure_dedicated_browser(
    crawler_root: Path,
    start_port: int,
    chrome_path: str,
    profile_dir_raw: str,
    start_url: str,
    offscreen: bool = False,
    *,
    process_lookup: Callable[[int], list[dict[str, Any]]] = listener_processes_windows,
    window_mode_applier: Callable[[int, bool], None] = apply_dedicated_browser_window_mode,
) -> int:
    profile_dir = (Path(profile_dir_raw).expanduser() if profile_dir_raw else crawler_root / "chrome-profile").resolve()
    if is_port_open(start_port):
        if not cdp_ready(start_port):
            raise RuntimeError(f"cdp_port_conflict: port {start_port} is not a CDP endpoint")
        assert_dedicated_browser_process(start_port, profile_dir, process_lookup)
        window_mode_applier(start_port, offscreen)
        return start_port

    launch_dedicated_browser(find_chrome(chrome_path), start_port, profile_dir, start_url, offscreen)
    deadline = time.time() + CDP_WAIT_SECONDS
    while time.time() < deadline:
        if cdp_ready(start_port):
            assert_dedicated_browser_process(start_port, profile_dir, process_lookup)
            window_mode_applier(start_port, offscreen)
            return start_port
        time.sleep(0.5)
    raise RuntimeError(f"dedicated Chrome did not expose CDP on port {start_port}")


class PipelineFileLock:
    def __init__(self, path: Path = COLLECTION_LOCK_PATH):
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "PipelineFileLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = self.path.open("a+b")
            self.handle.seek(0, os.SEEK_END)
            if self.handle.tell() == 0:
                self.handle.write(b"\0")
                self.handle.flush()
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self
        except (OSError, PermissionError) as exc:
            if self.handle:
                self.handle.close()
                self.handle = None
            raise RuntimeError("busy: collection pipeline lock is already held") from exc

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self.handle:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def start_parent_death_monitor(pid: int) -> None:
    if os.name == "nt":
        import ctypes

        synchronize = 0x00100000
        infinite = 0xFFFFFFFF
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            raise RuntimeError("parent_lock_owner_process_unavailable")

        def wait_for_parent() -> None:
            try:
                ctypes.windll.kernel32.WaitForSingleObject(handle, infinite)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
            os._exit(1)

    else:
        def wait_for_parent() -> None:
            while process_is_alive(pid):
                time.sleep(0.5)
            os._exit(1)

    threading.Thread(target=wait_for_parent, name="collection-parent-monitor", daemon=True).start()


def validate_parent_lock_owner(
    run_id: str,
    token: str,
    *,
    owner_data: dict[str, Any] | None = None,
    alive_checker: Callable[[int], bool] = process_is_alive,
    start_monitor: bool = True,
) -> bool:
    if not run_id or not token:
        return False
    try:
        if owner_data is None:
            owner_data = json.loads(COLLECTION_OWNER_PATH.read_text(encoding="utf-8-sig"))
        owner_pid = int(owner_data.get("owner_pid", 0))
        expected_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if str(owner_data.get("run_id") or "") != run_id:
            return False
        if str(owner_data.get("token_sha256") or "").lower() != expected_hash.lower():
            return False
        if not alive_checker(owner_pid):
            return False
        if start_monitor:
            start_parent_death_monitor(owner_pid)
        return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def collection_lock_context(args: argparse.Namespace, run_id: str) -> contextlib.AbstractContextManager[Any]:
    token = os.environ.get(COLLECTION_LOCK_TOKEN_ENV, "")
    if args.parent_holds_collection_lock and validate_parent_lock_owner(run_id, token):
        return contextlib.nullcontext()
    return PipelineFileLock()


def atomic_write_json(path: Path, payload: dict[str, Any], run_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{run_id}.tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def snapshot_creator_jsonl(crawler_root: Path, platform: str) -> dict[str, bytes]:
    jsonl_dir = crawler_root / "output" / platform / "jsonl"
    if not jsonl_dir.exists():
        return {}
    return {str(path.resolve()): path.read_bytes() for path in sorted(jsonl_dir.glob("creator_contents_*.jsonl")) if path.is_file()}


def valid_aweme_id(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def parse_jsonl_bytes(data: bytes, label: str) -> tuple[list[dict[str, Any]], set[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label}: invalid UTF-8") from exc
    rows: list[dict[str, Any]] = []
    ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label}:{line_number}: row is not an object")
        aweme_id = valid_aweme_id(value.get("aweme_id"))
        if aweme_id is None:
            raise ValueError(f"{label}:{line_number}: invalid aweme_id")
        rows.append(value)
        ids.add(aweme_id)
    return rows, ids


def creator_output_delta(before: dict[str, bytes], after: dict[str, bytes]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_file": "",
        "changed_files": [],
        "source_last_write_time": None,
        "source_sha256": "",
        "output_rows": 0,
        "crawl_output_rows": 0,
        "new_unique_items": 0,
        "ambiguous": False,
        "warnings": [],
    }
    all_paths = sorted(set(before) | set(after))
    historical_ids: set[str] = set()
    changed: list[str] = []
    try:
        for path, data in before.items():
            _, ids = parse_jsonl_bytes(data, f"history:{path}")
            historical_ids.update(ids)
        for path in all_paths:
            old = before.get(path, b"")
            new = after.get(path)
            if new is None:
                raise ValueError(f"output file disappeared:{path}")
            if new == old:
                continue
            changed.append(path)
            if old and not new.startswith(old):
                raise ValueError(f"output file was truncated or rewritten:{path}")
        result["changed_files"] = changed
        if not changed:
            return result
        if len(changed) != 1:
            raise ValueError("multiple creator JSONL files changed in one run")
        path = changed[0]
        old = before.get(path, b"")
        new = after[path]
        appended = new[len(old):]
        if old and appended and not old.endswith((b"\n", b"\r")) and not appended.startswith((b"\n", b"\r")):
            raise ValueError(f"append boundary is not a complete JSONL line:{path}")
        all_rows, _ = parse_jsonl_bytes(new, f"candidate:{path}")
        appended_rows, appended_ids = parse_jsonl_bytes(appended, f"append:{path}")
        source = Path(path)
        result.update(
            {
                "source_file": path,
                "source_last_write_time": datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc).isoformat(),
                "source_sha256": hashlib.sha256(new).hexdigest(),
                "output_rows": len(all_rows),
                "crawl_output_rows": len(appended_rows),
                "new_unique_items": len(appended_ids - historical_ids),
            }
        )
        return result
    except (OSError, ValueError) as exc:
        result.update(
            {
                "source_file": "",
                "source_last_write_time": None,
                "source_sha256": "",
                "output_rows": None,
                "crawl_output_rows": None,
                "new_unique_items": None,
                "ambiguous": True,
                "warnings": [str(exc)],
                "changed_files": changed,
            }
        )
        return result


def normalize_douyin_creator_ids(raw: str) -> list[str]:
    values: list[str] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        match = re.search(r"douyin\.com/user/([^/?#]+)", item, re.IGNORECASE)
        value = match.group(1) if match else item
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError(f"invalid douyin creator id:{item}")
        if value not in values:
            values.append(value)
    if raw.strip() and not values:
        raise ValueError("douyin creator id list is empty")
    return values


class DouyinRunObserver:
    def __init__(self, requested_ids: list[str]):
        self.requested_ids = requested_ids
        self.records: dict[str, dict[str, Any]] = {creator_id: self._new_record(creator_id) for creator_id in requested_ids}

    @staticmethod
    def _new_record(creator_id: str) -> dict[str, Any]:
        return {
            "sec_uid": creator_id,
            "state": "pending",
            "profile_valid": False,
            "api_pages_valid": False,
            "listed_count": 0,
            "written_rows": 0,
            "error": "",
        }

    def record(self, creator_id: str) -> dict[str, Any]:
        return self.records.setdefault(creator_id, self._new_record(creator_id))

    def fail(self, creator_id: str, message: str) -> None:
        record = self.record(creator_id)
        record["state"] = "failed"
        record["error"] = message

    def finalize(self) -> None:
        for creator_id in self.requested_ids:
            record = self.record(creator_id)
            if record["error"]:
                record["state"] = "failed"
            elif record["profile_valid"] and record["api_pages_valid"] and record["written_rows"] == record["listed_count"]:
                record["state"] = "completed"
            else:
                record["state"] = "failed"
                record["error"] = record["error"] or "creator receipt is incomplete"

    def summary(self) -> dict[str, Any]:
        ordered = [self.record(creator_id).copy() for creator_id in self.requested_ids]
        return {
            "requested_creator_count": len(self.requested_ids),
            "completed_creator_count": sum(record["state"] == "completed" for record in ordered),
            "failed_creator_count": sum(record["state"] != "completed" for record in ordered),
            "creator_results": ordered,
        }


def validate_douyin_profile_response(response: object, sec_user_id: str) -> dict[str, Any]:
    if not isinstance(response, dict) or response.get("status_code") != 0:
        raise RuntimeError("profile response status_code is not 0")
    user = response.get("user")
    if not isinstance(user, dict) or str(user.get("sec_uid") or "").strip() != sec_user_id:
        raise RuntimeError("profile response does not match requested sec_uid")
    return response


def validate_douyin_aweme_page(response: object, max_cursor: str = "") -> dict[str, Any]:
    if not isinstance(response, dict) or response.get("status_code") != 0:
        raise RuntimeError("aweme page status_code is not 0")
    aweme_list = response.get("aweme_list")
    if not isinstance(aweme_list, list):
        raise RuntimeError("aweme page is missing aweme_list")
    has_more = response.get("has_more")
    if has_more not in (0, 1, False, True):
        raise RuntimeError("aweme page has invalid has_more")
    next_cursor = str(response.get("max_cursor") or "")
    if int(bool(has_more)) == 1 and not aweme_list:
        raise RuntimeError("aweme page is empty while has_more=1")
    if int(bool(has_more)) == 1 and (not next_cursor or next_cursor == str(max_cursor or "")):
        raise RuntimeError("aweme page cursor did not advance")
    return response


def install_douyin_observer(observer: DouyinRunObserver, max_notes: int) -> None:
    from media_platform.douyin.client import DouYinClient  # type: ignore
    import store.douyin as douyin_store  # type: ignore

    original_get_user_info = DouYinClient.get_user_info
    original_get_user_aweme_posts = DouYinClient.get_user_aweme_posts
    original_store_aweme = douyin_store.update_douyin_aweme

    async def get_user_info(self: object, sec_user_id: str) -> dict[str, Any]:
        try:
            response = await original_get_user_info(self, sec_user_id)
            response = validate_douyin_profile_response(response, sec_user_id)
            observer.record(sec_user_id)["profile_valid"] = True
            return response
        except Exception as exc:
            observer.fail(sec_user_id, str(exc))
            raise

    async def get_user_aweme_posts(self: object, sec_user_id: str, max_cursor: str = "") -> dict[str, Any]:
        try:
            response = await original_get_user_aweme_posts(self, sec_user_id, max_cursor)
            response = validate_douyin_aweme_page(response, max_cursor)
            observer.record(sec_user_id)["api_pages_valid"] = True
            return response
        except Exception as exc:
            observer.fail(sec_user_id, str(exc))
            raise

    async def get_all_user_aweme_posts(self: object, sec_user_id: str, callback: object = None) -> list[dict[str, Any]]:
        has_more = 1
        cursor = ""
        rows: list[dict[str, Any]] = []
        limit = max_notes if max_notes > 0 else sys.maxsize
        while has_more == 1 and len(rows) < limit:
            response = await self.get_user_aweme_posts(sec_user_id, cursor)  # type: ignore[attr-defined]
            page_rows = response["aweme_list"]
            remaining = limit - len(rows)
            selected = page_rows[:remaining]
            observer.record(sec_user_id)["listed_count"] += len(selected)
            if callback and selected:
                await callback(selected)  # type: ignore[misc]
            rows.extend(selected)
            has_more = int(bool(response.get("has_more")))
            cursor = str(response.get("max_cursor") or "")
        return rows

    async def update_douyin_aweme(aweme_item: dict[str, Any]) -> None:
        await original_store_aweme(aweme_item)
        author = aweme_item.get("author")
        creator_id = str(author.get("sec_uid") or "") if isinstance(author, dict) else ""
        if creator_id:
            observer.record(creator_id)["written_rows"] += 1

    DouYinClient.get_user_info = get_user_info  # type: ignore[method-assign]
    DouYinClient.get_user_aweme_posts = get_user_aweme_posts  # type: ignore[method-assign]
    DouYinClient.get_all_user_aweme_posts = get_all_user_aweme_posts  # type: ignore[method-assign]
    douyin_store.update_douyin_aweme = update_douyin_aweme


def run_mediacrawler(
    crawler_root: Path,
    cdp_port: int,
    platform: str,
    creator_id: str,
    max_notes: int,
    observer: DouyinRunObserver | None = None,
) -> int:
    os.chdir(crawler_root)
    sys.path.insert(0, str(crawler_root))

    import config  # type: ignore
    from tools.app_runner import run  # type: ignore
    import main as mediacrawler_main  # type: ignore

    config.ENABLE_CDP_MODE = True
    config.CDP_CONNECT_EXISTING = True
    config.CDP_DEBUG_PORT = cdp_port
    config.CDP_HEADLESS = False
    config.HEADLESS = False
    config.SAVE_LOGIN_STATE = True
    if platform == "douyin" and observer is not None:
        install_douyin_observer(observer, max_notes)

    media_platform = "dy" if platform == "douyin" else "xhs"
    sys.argv = [
        str(crawler_root / "main.py"),
        "--platform",
        media_platform,
        "--lt",
        "qrcode",
        "--type",
        "creator",
        "--save_data_option",
        "jsonl",
        "--save_data_path",
        str(crawler_root / "output"),
        "--crawler_max_notes_count",
        str(max_notes),
        "--max_concurrency_num",
        "1",
        "--headless",
        "false",
        "--get_comment",
        "false",
        "--get_sub_comment",
        "false",
    ]
    if creator_id:
        sys.argv.extend(["--creator_id", creator_id])

    run(mediacrawler_main.main, mediacrawler_main.async_cleanup, cleanup_timeout_seconds=15.0)
    return 0


def runner_result_payload(
    run_id: str,
    login_state: str,
    delta: dict[str, Any] | None,
    observer: DouyinRunObserver | None,
    *,
    ok: bool,
    error: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "ok": ok,
        "login_state": login_state,
        "source_file": "",
        "changed_files": [],
        "source_last_write_time": None,
        "source_sha256": "",
        "output_rows": 0,
        "crawl_output_rows": 0,
        "new_unique_items": 0,
        "requested_creator_count": 0,
        "completed_creator_count": 0,
        "failed_creator_count": 0,
        "creator_results": [],
        "ambiguous": False,
        "warnings": [],
        "error": error,
    }
    if delta:
        payload.update(delta)
    if observer:
        payload.update(observer.summary())
    if error and error not in payload["warnings"]:
        payload["warnings"] = [*payload["warnings"], error]
    return payload


def main() -> int:
    protect_local_cdp_from_proxy()
    args = parse_args()
    run_id = args.run_id.strip() or uuid.uuid4().hex
    result_path = Path(args.result_file).expanduser().resolve() if args.result_file else None
    crawler_root = Path(args.crawler_root).expanduser().resolve()
    login_state = "not_applicable"
    observer: DouyinRunObserver | None = None
    before_snapshot: dict[str, bytes] = {}
    delta: dict[str, Any] | None = None
    if args.platform == "douyin":
        start_url = DOUYIN_HOME_URL
        start_port = args.cdp_port or int(os.environ.get("MEDIACRAWLER_DOUYIN_CDP_PORT") or DEFAULT_CDP_PORT)
        max_notes = args.max_notes or int(os.environ.get("MEDIACRAWLER_DOUYIN_MAX_NOTES") or 20)
        login_state = "unknown"
        requested_ids = normalize_douyin_creator_ids(args.creator_id)
        observer = DouyinRunObserver(requested_ids) if requested_ids else None
    else:
        start_url = XIAOHONGSHU_HOME_URL
        start_port = args.cdp_port or int(os.environ.get("MEDIACRAWLER_XHS_CDP_PORT") or DEFAULT_CDP_PORT)
        max_notes = args.max_notes or int(os.environ.get("MEDIACRAWLER_XHS_MAX_NOTES") or 500)
    try:
        if not (crawler_root / "main.py").exists():
            raise RuntimeError(f"MediaCrawler main.py not found: {crawler_root}")
        if args.platform == "douyin" and result_path and not args.browser_only and observer is None:
            raise RuntimeError("observable douyin run requires explicit creator ids")
        with collection_lock_context(args, run_id):
            cdp_port = ensure_dedicated_browser(
                crawler_root,
                start_port,
                args.chrome_path,
                args.profile_dir,
                start_url,
                args.offscreen,
            )
            if args.platform == "douyin":
                login_state = check_douyin_login_state(cdp_port)
                if args.offscreen and login_state != "logged_in":
                    raise RuntimeError("login_required: use visible --browser-only to restore Douyin login")
            if args.browser_only:
                print(f"browser_port={cdp_port} mode={'offscreen' if args.offscreen else 'visible'} login_state={login_state}")
                return 0
            if args.platform == "douyin" and result_path:
                before_snapshot = snapshot_creator_jsonl(crawler_root, args.platform)
            exit_code = run_mediacrawler(
                crawler_root,
                cdp_port,
                args.platform,
                args.creator_id,
                max_notes,
                observer,
            )
            if exit_code != 0:
                raise RuntimeError(f"MediaCrawler exited with {exit_code}")
            if observer:
                observer.finalize()
            if args.platform == "douyin" and result_path:
                delta = creator_output_delta(before_snapshot, snapshot_creator_jsonl(crawler_root, args.platform))
                if observer and observer.summary()["failed_creator_count"]:
                    raise RuntimeError("partial_creator_failure: creator receipt is incomplete")
            if result_path:
                payload = runner_result_payload(
                    run_id,
                    login_state,
                    delta,
                    observer,
                    ok=not bool(delta and delta.get("ambiguous")),
                )
                atomic_write_json(result_path, payload, run_id)
            if args.collect_window_hours > 0:
                result = summarize_creator_jsonl_by_window(crawler_root, args.platform, args.collect_window_hours)
                if result.get("ok"):
                    print(
                        "[MediaCrawlerWindow] "
                        f"found {result.get('kept', 0)}/{result.get('total', 0)} rows "
                        f"within {args.collect_window_hours}h in {result.get('path')}; "
                        "raw JSONL preserved"
                    )
                else:
                    print(f"[MediaCrawlerWindow] skipped window summary: {result.get('error')}", file=sys.stderr)
            return 0
    except Exception as exc:
        message = str(exc)
        if "login_required" in message:
            login_state = "login_required"
        if observer:
            observer.finalize()
        if result_path:
            if args.platform == "douyin" and before_snapshot:
                delta = creator_output_delta(before_snapshot, snapshot_creator_jsonl(crawler_root, args.platform))
            payload = runner_result_payload(run_id, login_state, delta, observer, ok=False, error=message)
            try:
                atomic_write_json(result_path, payload, run_id)
            except Exception as result_exc:
                print(f"failed to write result file: {result_exc}", file=sys.stderr)
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
