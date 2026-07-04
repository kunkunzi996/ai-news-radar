#!/usr/bin/env python3
"""Launch MediaCrawler creator crawling through an isolated local Chrome profile."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DOUYIN_HOME_URL = "https://www.douyin.com/"
XIAOHONGSHU_HOME_URL = "https://www.xiaohongshu.com/explore"
DEFAULT_CDP_PORT = 9333
CDP_WAIT_SECONDS = 30
JSONL_FUTURE_SKEW_SECONDS = 300
PUBLISH_TIME_FIELDS = (
    "create_time",
    "create_timestamp",
    "publish_time",
    "time",
    "last_update_time",
    "published_at",
)


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


def find_port(start_port: int) -> int:
    for port in range(start_port, start_port + 100):
        if not is_port_open(port):
            return port
    raise RuntimeError(f"no available local CDP port from {start_port}")


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


def launch_dedicated_browser(chrome_path: str, port: int, profile_dir: Path, start_url: str) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-features=TranslateUI",
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
        start_url,
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, close_fds=True, creationflags=creationflags)


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


def install_douyin_creator_limit(max_notes: int) -> None:
    if max_notes <= 0:
        return
    from media_platform.douyin.client import DouYinClient  # type: ignore

    async def get_all_user_aweme_posts(self, sec_user_id: str, callback: object = None) -> list[dict]:
        return await limited_douyin_creator_posts(self, sec_user_id, max_notes, callback)

    DouYinClient.get_all_user_aweme_posts = get_all_user_aweme_posts  # type: ignore[method-assign]


def ensure_dedicated_browser(crawler_root: Path, start_port: int, chrome_path: str, profile_dir_raw: str, start_url: str) -> int:
    profile_dir = Path(profile_dir_raw).expanduser() if profile_dir_raw else crawler_root / "chrome-profile"
    if is_port_open(start_port) and cdp_ready(start_port):
        return start_port

    port = find_port(start_port)
    launch_dedicated_browser(find_chrome(chrome_path), port, profile_dir, start_url)
    deadline = time.time() + CDP_WAIT_SECONDS
    while time.time() < deadline:
        if cdp_ready(port):
            return port
        time.sleep(0.5)
    raise RuntimeError(f"dedicated Chrome did not expose CDP on port {port}")


def run_mediacrawler(crawler_root: Path, cdp_port: int, platform: str, creator_id: str, max_notes: int) -> int:
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
    if platform == "douyin":
        install_douyin_creator_limit(max_notes)

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


def main() -> int:
    args = parse_args()
    crawler_root = Path(args.crawler_root).expanduser().resolve()
    if not (crawler_root / "main.py").exists():
        raise RuntimeError(f"MediaCrawler main.py not found: {crawler_root}")
    if args.platform == "douyin":
        start_url = DOUYIN_HOME_URL
        start_port = args.cdp_port or int(os.environ.get("MEDIACRAWLER_DOUYIN_CDP_PORT") or DEFAULT_CDP_PORT)
        max_notes = args.max_notes or int(os.environ.get("MEDIACRAWLER_DOUYIN_MAX_NOTES") or 20)
    else:
        start_url = XIAOHONGSHU_HOME_URL
        start_port = args.cdp_port or int(os.environ.get("MEDIACRAWLER_XHS_CDP_PORT") or DEFAULT_CDP_PORT)
        max_notes = args.max_notes or int(os.environ.get("MEDIACRAWLER_XHS_MAX_NOTES") or 500)
    cdp_port = ensure_dedicated_browser(crawler_root, start_port, args.chrome_path, args.profile_dir, start_url)
    exit_code = run_mediacrawler(crawler_root, cdp_port, args.platform, args.creator_id, max_notes)
    if exit_code == 0 and args.collect_window_hours > 0:
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
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
