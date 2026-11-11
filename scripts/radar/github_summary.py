"""GitHub release 中文小结。

按 release_id 缓存到 data/github-summary-cache.json；只对缓存里没有的发布调用本机 grok CLI。
每轮有总时间预算和单条超时；失败或超时只是本轮不显示小结，下一轮再补，绝不抛错中断采集。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

GROK_BIN = os.environ.get("RADAR_GROK_BIN") or r"C:\Users\beelink-pc\.grok\bin\grok.exe"
GROK_MODEL = os.environ.get("RADAR_GROK_MODEL") or "grok-4.7-build-fast"
GROK_EFFORT = os.environ.get("RADAR_GROK_EFFORT") or "xhigh"
TOTAL_BUDGET_SECONDS = float(os.environ.get("RADAR_GITHUB_SUMMARY_BUDGET") or 90)
PER_CALL_TIMEOUT_SECONDS = float(os.environ.get("RADAR_GITHUB_SUMMARY_TIMEOUT") or 75)
MAX_PARALLEL = 4
MAX_NEW_PER_RUN = 12
MAX_SUMMARY_CHARS = 140
BODY_MAX_CHARS = 4000
PRIVATE_META_KEYS = ("release_body", "repo_description")

PROMPT_TEMPLATE = """你是 AI 新闻雷达的编辑。根据下面的 GitHub 发布信息写中文小结。
要求：
- 严格两句中文，合计约 80 字，不超过 110 字。
- 第一句：这次发布改了什么，挑最重要的 1-3 点，结论先行。
- 第二句：这个项目是做什么的。
- 只输出这两句正文；不要标题、列表、引号、Markdown、表情或任何解释。
- 不要编造发布说明里没有的内容。
- 不要调用任何工具、不要运行命令或数字数，直接输出答案。

仓库：{repo}
仓库简介：{description}
版本：{name}（{tag}）
发布说明（可能截断）：
{body}
"""

_print_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cache(path: Path, cache: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _is_release_record(record: dict[str, Any]) -> bool:
    return str(record.get("github_source_kind") or "") == "release" and bool(str(record.get("release_id") or "").strip())


def clean_summary(text: str) -> str:
    text = str(text or "").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    text = "".join(lines)
    text = re.sub(r"[*`#>]+", "", text)
    text = text.strip(" \"'“”「」")
    if not re.search(r"[\u4e00-\u9fff]", text):
        return ""
    if len(text) > MAX_SUMMARY_CHARS:
        cut = text[:MAX_SUMMARY_CHARS]
        idx = max(cut.rfind("。"), cut.rfind("；"))
        text = cut[: idx + 1] if idx >= 40 else cut.rstrip() + "…"
    return text


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def call_grok(prompt: str, timeout: float) -> str:
    """单轮 headless 调用；prompt 写临时文件传入，避免命令行引号问题。失败返回空串。"""
    if timeout < 5 or not Path(GROK_BIN).is_file():
        return ""
    with tempfile.TemporaryDirectory(prefix="radar-grok-") as tmp:
        prompt_path = Path(tmp) / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        cmd = [
            GROK_BIN,
            "--prompt-file", str(prompt_path),
            "-m", GROK_MODEL,
            "--reasoning-effort", GROK_EFFORT,
            "--max-turns", "1",
            "--cwd", tmp,
            "--disable-web-search",
            "--no-subagents",
            "--output-format", "plain",
            "--permission-mode", "dontAsk",
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            return ""
        if proc.returncode != 0:
            return ""
        return _decode(proc.stdout or b"")


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "AI-News-Radar/0.7 github-summary"}
    token = str(os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    return headers


def _fetch_release_body(session: Any, repo: str, release_id: str) -> tuple[str, str, str]:
    """归档里的旧条目没有正文时，按 release id 补抓一次。返回 (body, name, tag)。"""
    if not re.fullmatch(r"\d+", release_id) or "/" not in repo:
        return "", "", ""
    try:
        resp = session.get(
            f"https://api.github.com/repos/{repo}/releases/{release_id}",
            headers=_github_headers(),
            timeout=15,
        )
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            return "", "", ""
        data = resp.json()
        return (
            str(data.get("body") or "").strip()[:BODY_MAX_CHARS],
            str(data.get("name") or ""),
            str(data.get("tag_name") or ""),
        )
    except Exception:
        return "", "", ""


def _repo_description(session: Any, repo: str) -> str:
    try:
        from scripts.radar.fetchers.subscriptions import github_repo_description

        return github_repo_description(session, repo, headers=_github_headers(), deadline=None)
    except Exception:
        return ""


def apply_github_summaries(
    records: Iterable[dict[str, Any]],
    raw_items: Iterable[Any],
    session: Any,
    cache_path: Path,
    *,
    budget_seconds: float = TOTAL_BUDGET_SECONDS,
    max_new: int = MAX_NEW_PER_RUN,
) -> dict[str, Any]:
    """给 GitHub release 记录写 summary_zh（原地修改），并去掉私有正文字段。永不抛错。"""
    started = time.monotonic()
    stats: dict[str, Any] = {"releases": 0, "cache_hits": 0, "generated": 0, "failed": 0, "deferred": 0, "grok_calls": 0}
    try:
        cache = load_cache(cache_path)
        sources: dict[str, dict[str, Any]] = {}
        for raw in raw_items or []:
            meta = getattr(raw, "meta", None)
            if not isinstance(meta, dict):
                continue
            rid = str(meta.get("release_id") or "").strip()
            if rid and str(meta.get("github_source_kind") or "") == "release":
                sources[rid] = {
                    "body": str(meta.get("release_body") or "")[:BODY_MAX_CHARS],
                    "description": str(meta.get("repo_description") or ""),
                }
        targets: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            for key in PRIVATE_META_KEYS:
                record.pop(key, None)
            if not _is_release_record(record):
                continue
            rid = str(record.get("release_id")).strip()
            targets.setdefault(rid, []).append(record)
        stats["releases"] = len(targets)

        todo: list[str] = []
        for rid, recs in targets.items():
            cached = cache.get(rid)
            summary = str(cached.get("summary_zh") or "") if isinstance(cached, dict) else ""
            if summary:
                stats["cache_hits"] += 1
                for rec in recs:
                    rec["summary_zh"] = summary
            else:
                todo.append(rid)
        # 新发布优先
        todo.sort(key=lambda r: str(targets[r][0].get("published_at") or ""), reverse=True)
        stats["deferred"] = max(0, len(todo) - max_new)
        todo = todo[:max_new]

        def work(rid: str) -> tuple[str, str]:
            rec = targets[rid][0]
            remaining = budget_seconds - (time.monotonic() - started)
            if remaining < 40:  # 单次调用约 30-40 秒，剩余不够就留到下轮
                return rid, "__deferred__"
            repo = str(rec.get("repo") or "").strip()
            src = sources.get(rid) or {}
            body = src.get("body") or ""
            name = str(rec.get("release_name") or rec.get("tag_name") or "")
            tag = str(rec.get("tag_name") or "")
            if not body:
                body, fetched_name, fetched_tag = _fetch_release_body(session, repo, rid)
                name = name or fetched_name
                tag = tag or fetched_tag
            description = src.get("description") or _repo_description(session, repo)
            if not body and not description:
                return rid, ""
            prompt = PROMPT_TEMPLATE.format(
                repo=repo or "未知",
                description=description or "无",
                name=name or tag or "未知",
                tag=tag or "无",
                body=body or "（无发布说明）",
            )
            remaining = budget_seconds - (time.monotonic() - started)
            with _print_lock:
                stats["grok_calls"] += 1
            return rid, clean_summary(call_grok(prompt, min(PER_CALL_TIMEOUT_SECONDS, remaining)))

        if todo:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
                for rid, summary in pool.map(work, todo):
                    if summary == "__deferred__":
                        stats["deferred"] += 1
                        continue
                    if not summary:
                        stats["failed"] += 1
                        continue
                    stats["generated"] += 1
                    cache[rid] = {
                        "summary_zh": summary,
                        "repo": targets[rid][0].get("repo"),
                        "tag_name": targets[rid][0].get("tag_name"),
                        "model": GROK_MODEL,
                        "generated_at": _now_iso(),
                    }
                    for rec in targets[rid]:
                        rec["summary_zh"] = summary
            save_cache(cache_path, cache)
    except Exception as exc:  # 小结是增值功能，不能拖垮整轮采集
        stats["error"] = type(exc).__name__
    stats["elapsed_seconds"] = round(time.monotonic() - started, 1)
    return stats