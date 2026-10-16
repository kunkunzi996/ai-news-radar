"""家里电脑每半小时看一眼云端快照任务。

GitHub 的定时是尽力而为，忙的时候会整次不排队，页面上没有失败记录。
正在跑，或新鲜窗口内已经成功过，就不要再按。工作流开了 cancel-in-progress，
新的一班会把还在跑的那班挤掉。

钥匙只读仓库外的文件或环境变量，不要写进仓库、日志或命令行参数。
GitHub 把整份 Actions 关掉时记 event=alert reason=actions_disabled。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = os.environ.get("RADAR_DISPATCH_REPO", "kunkunzi996/ai-news-radar")
WORKFLOW_ID = os.environ.get("RADAR_DISPATCH_WORKFLOW_ID", "305966643")
FRESH_MINUTES = int(os.environ.get("RADAR_DISPATCH_FRESH_MINUTES", "40"))
REF = os.environ.get("RADAR_DISPATCH_REF", "master")
TOKEN_FILE = os.environ.get(
    "RADAR_DISPATCH_TOKEN_FILE",
    r"C:\AI-news-reader\secrets\snapshot-dispatch.token",
)
ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "pending", "requested"}


def repo_root() -> Path:
    override = os.environ.get("RADAR_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2]


def log_path() -> Path:
    override = os.environ.get("RADAR_NUDGE_LOG")
    if override:
        return Path(override)
    return repo_root() / "logs" / "nudge-snapshot.log"


def parse_time(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def decide(runs: list[dict], now: datetime, fresh_minutes: int) -> tuple[str, str, int | None]:
    """返回 action、reason、最近一次成功距现在的分钟数。"""
    if any(run.get("status") in ACTIVE_STATUSES for run in runs):
        return "skip", "already_running", None
    successes = []
    for run in runs:
        created = run.get("created_at") or ""
        if run.get("conclusion") == "success" and created:
            successes.append(parse_time(created))
    if not successes:
        return "dispatch", "no_success", None
    age = int((now - max(successes)).total_seconds() // 60)
    if age < fresh_minutes:
        return "skip", "fresh", age
    return "dispatch", "stale", age


def read_token(path: str) -> str:
    env_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if env_token.strip():
        return env_token.strip()
    file_path = Path(path)
    if not file_path.is_file():
        return ""
    return file_path.read_text(encoding="utf-8").strip()


def redact(text: str) -> str:
    cleaned = " ".join(text.split())
    for marker in ("ghp_", "gho_", "github_pat_", "Bearer "):
        while marker in cleaned:
            start = cleaned.find(marker)
            end = start + len(marker)
            while end < len(cleaned) and cleaned[end] not in " \t":
                end += 1
            cleaned = cleaned[:start] + "<redacted>" + cleaned[end:]
    return cleaned[:300]


def is_actions_disabled(status: int, body: str) -> bool:
    return status == 422 and "Actions has been disabled" in body


def github_request(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, str]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "radar-snapshot-nudge")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def write_log(event: str, reason: str, age: int | None, detail: str = "") -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    age_text = "" if age is None else str(age)
    line = (
        f"{now} event={event} reason={reason} age_minutes={age_text} "
        f"detail={redact(detail)}\n"
    )
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)


def runs_url() -> str:
    return (
        f"https://api.github.com/repos/{REPO}/actions/workflows/"
        f"{WORKFLOW_ID}/runs?per_page=5"
    )


def dispatch_url() -> str:
    return (
        f"https://api.github.com/repos/{REPO}/actions/workflows/"
        f"{WORKFLOW_ID}/dispatches"
    )


def nudge(now: datetime, token: str, request) -> tuple[str, str]:
    if not token:
        write_log("failed", "token_missing", None, TOKEN_FILE)
        return "failed", "token_missing"
    status, body = request("GET", runs_url(), token, None)
    if status != 200:
        if is_actions_disabled(status, body):
            write_log("alert", "actions_disabled", None, body)
            return "alert", "actions_disabled"
        write_log("failed", "list_runs", None, f"http_{status}")
        return "failed", "list_runs"
    payload = json.loads(body) if body else {}
    runs = payload.get("workflow_runs") or []
    action, reason, age = decide(runs, now, FRESH_MINUTES)
    if action == "skip":
        write_log("skip", reason, age)
        return "skip", reason
    status, body = request("POST", dispatch_url(), token, {"ref": REF})
    if status in {200, 204}:
        write_log("dispatched", reason, age)
        return "dispatched", reason
    if is_actions_disabled(status, body):
        write_log("alert", "actions_disabled", age, body)
        return "alert", "actions_disabled"
    write_log("failed", "dispatch", age, f"http_{status}")
    return "failed", "dispatch"


def main() -> int:
    now = datetime.now(timezone.utc)
    token = read_token(TOKEN_FILE)
    nudge(now, token, github_request)
    return 0


if __name__ == "__main__":
    sys.exit(main())
