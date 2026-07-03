#!/usr/bin/env python3
"""Launch MediaCrawler creator crawling through an isolated local Chrome profile."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DOUYIN_HOME_URL = "https://www.douyin.com/"
XIAOHONGSHU_HOME_URL = "https://www.xiaohongshu.com/explore"
DEFAULT_CDP_PORT = 9333
CDP_WAIT_SECONDS = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start MediaCrawler creator mode with a dedicated CDP browser.")
    parser.add_argument("--crawler-root", required=True)
    parser.add_argument("--platform", choices=("douyin", "xhs"), default=os.environ.get("MEDIACRAWLER_PLATFORM") or "douyin")
    parser.add_argument("--creator-id", default=os.environ.get("MEDIACRAWLER_CREATOR_ID") or "")
    parser.add_argument("--max-notes", type=int, default=0)
    parser.add_argument("--cdp-port", type=int, default=0)
    parser.add_argument("--chrome-path", default=os.environ.get("MEDIACRAWLER_CHROME_PATH") or "")
    parser.add_argument("--profile-dir", default=os.environ.get("MEDIACRAWLER_PROFILE_DIR") or "")
    return parser.parse_args()


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
    if platform == "xhs":
        if not creator_id:
            raise RuntimeError("Xiaohongshu creator id or profile URL is required")
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
    return run_mediacrawler(crawler_root, cdp_port, args.platform, args.creator_id, max_notes)


if __name__ == "__main__":
    raise SystemExit(main())
