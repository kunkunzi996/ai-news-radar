from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

"""Public online source-config persistence and git sync helpers."""

ONLINE_CONFIG_FILENAME = Path("config") / "online-sources.json"
ONLINE_OPML_FILENAME = Path("feeds") / "online-sources.opml"
ONLINE_OPML_SOURCE_ID = "online_opmlrss"
ONLINE_ALLOWED_TYPES = frozenset(
    {"bilibili_dynamic", "github_release", "mediacrawler_jsonl", "rss", "we_mp_rss_jsonl"}
)
ONLINE_COMMIT_MESSAGE = "配置：同步线上信源"

SENSITIVE_MARKERS = (
    "token",
    "cookie",
    "secret",
    "password",
    "authorization",
    "xsec_token",
    ".env",
)
PRIVATE_PATH_MARKERS = (
    "local-secrets",
    "chrome-profile",
    "mediacrawler-local-test",
    "creator_contents_",
    "feeds/follow.opml",
)
TYPE_ORDER = {
    "bilibili_dynamic": 0,
    "github_release": 1,
    "mediacrawler_jsonl": 2,
    "we_mp_rss_jsonl": 3,
    "rss": 4,
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def online_config_path(root_dir: Path) -> Path:
    return (root_dir / ONLINE_CONFIG_FILENAME).resolve()


def online_opml_path(root_dir: Path) -> Path:
    return (root_dir / ONLINE_OPML_FILENAME).resolve()


def ensure_public_online_paths(root_dir: Path) -> tuple[Path, Path]:
    config_path = online_config_path(root_dir)
    opml_path = online_opml_path(root_dir)
    if config_path != (root_dir / ONLINE_CONFIG_FILENAME).resolve():
        raise ValueError("invalid_online_config_path")
    if opml_path != (root_dir / ONLINE_OPML_FILENAME).resolve():
        raise ValueError("invalid_online_opml_path")
    return config_path, opml_path


def check_public_payload_safe(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            text = str(key).lower()
            if any(marker in text for marker in SENSITIVE_MARKERS):
                raise ValueError(f"{path}.{key} contains a sensitive field name")
            check_public_payload_safe(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            check_public_payload_safe(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        text = value.lower().replace("\\", "/")
        if any(marker in text for marker in SENSITIVE_MARKERS):
            raise ValueError(f"{path} contains sensitive text")
        if any(marker in text for marker in PRIVATE_PATH_MARKERS):
            raise ValueError(f"{path} contains a private local path")


def slug_token(value: str, fallback: str = "source") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return (text or fallback)[:64]


def feed_id_for_url(url: str) -> str:
    digest = hashlib.sha1(str(url or "").strip().encode("utf-8")).hexdigest()[:10]
    return f"online_feed_{digest}"


def normalize_online_type(raw_type: str) -> str:
    value = str(raw_type or "rss").strip().lower().replace("-", "_")
    aliases = {
        "bilibili": "bilibili_dynamic",
        "b站": "bilibili_dynamic",
        "github": "github_release",
        "github_releases": "github_release",
        "youtube": "rss",
        "feed": "rss",
        "atom": "rss",
        "douyin": "mediacrawler_jsonl",
        "抖音": "mediacrawler_jsonl",
        "mediacrawler_douyin": "mediacrawler_jsonl",
    }
    return aliases.get(value, value)


def normalize_http_url(value: str, index: int) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"sources[{index}].locator must be an http/https URL")
    clean = parsed._replace(fragment="")
    return urlunparse(clean)


def normalize_bilibili_uid(value: str, index: int) -> str:
    uid = str(value or "").strip()
    if not re.fullmatch(r"\d{2,20}", uid):
        raise ValueError(f"sources[{index}].locator must be a public Bilibili UID")
    return uid


def normalize_douyin_homepage(value: str, index: int) -> str:
    """只接受抖音创作者主页链接，清洗成 https://www.douyin.com/user/<sec_uid>。"""
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.lower() in {"www.douyin.com", "douyin.com"}
        and len(parts) >= 2
        and parts[0] == "user"
        and re.fullmatch(r"[A-Za-z0-9_=-]+", parts[1] or "")
    ):
        return f"https://www.douyin.com/user/{parts[1]}"
    raise ValueError(f"sources[{index}].locator must be a Douyin creator homepage URL (https://www.douyin.com/user/...)")


def normalize_github_repo(value: str, index: int) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.netloc.lower() == "api.github.com":
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 3 and parts[0] == "repos":
            raw = f"{parts[1]}/{parts[2]}"
    elif parsed.netloc.lower() in {"github.com", "www.github.com"}:
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            raw = f"{parts[0]}/{parts[1]}"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", raw):
        raise ValueError(f"sources[{index}].locator must be owner/repo or a GitHub repo URL")
    return raw


def normalize_online_source_record(source: dict[str, Any], index: int) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        raise ValueError(f"sources[{index}] must be an object")
    source_type = normalize_online_type(str(source.get("type") or "rss"))
    if source.get("id") == ONLINE_OPML_SOURCE_ID or source_type == "opmlrss":
        return None
    if source_type not in ONLINE_ALLOWED_TYPES:
        raise ValueError(f"sources[{index}].type is not supported for online sync")

    name = str(source.get("name") or source.get("target") or "").strip()
    locator = str(source.get("locator") or source.get("url") or source.get("feed_url") or "").strip()
    notes = str(source.get("notes") or "").strip()
    enabled = source.get("enabled") is not False

    if source_type == "bilibili_dynamic":
        locator = normalize_bilibili_uid(locator, index)
        if not name:
            raise ValueError(f"sources[{index}].name is required")
        return {
            "id": f"online_bilibili_{locator}",
            "name": name[:120],
            "type": source_type,
            "enabled": enabled,
            "channel": "B站动态",
            "target": name[:120],
            "locator": locator,
            "env": "",
            "notes": notes[:240] or "公开 UID",
        }

    if source_type == "mediacrawler_jsonl":
        homepage = normalize_douyin_homepage(locator, index)
        if not name:
            raise ValueError(f"sources[{index}].name is required")
        digest = hashlib.sha1(homepage.encode("utf-8")).hexdigest()[:10]
        return {
            "id": f"online_douyin_{digest}",
            "name": name[:120],
            "type": source_type,
            "enabled": enabled,
            "channel": "抖音订阅",
            "target": name[:120],
            "locator": homepage,
            "env": "",
            "notes": notes[:240] or "云电脑桥接采集",
        }

    if source_type == "we_mp_rss_jsonl":
        if not name:
            raise ValueError(f"sources[{index}].name is required")
        return {
            "id": str(source.get("id") or "").strip() or f"online_we_mp_rss_{slug_token(name)}",
            "name": name[:120],
            "type": source_type,
            "enabled": enabled,
            "channel": "微信公众号",
            "target": str(source.get("target") or name).strip()[:120],
            "locator": locator,
            "env": "",
            "notes": notes[:240] or "云电脑桥接采集",
        }

    if source_type == "github_release":
        repo = normalize_github_repo(locator or name, index)
        display_name = name or repo
        return {
            "id": f"online_github_{slug_token(repo.replace('/', '_'))}",
            "name": display_name[:120],
            "type": source_type,
            "enabled": enabled,
            "channel": "GitHub Release",
            "target": repo,
            "locator": repo,
            "env": "",
            "notes": notes[:240] or "只追踪 release",
        }

    feed_url = normalize_http_url(locator, index)
    if not name:
        raise ValueError(f"sources[{index}].name is required")
    return {
        "id": str(source.get("id") or "").strip() or feed_id_for_url(feed_url),
        "name": name[:120],
        "type": "rss",
        "enabled": enabled,
        "channel": str(source.get("channel") or "RSS/YouTube").strip()[:80],
        "target": str(source.get("target") or name).strip()[:120],
        "locator": feed_url,
        "env": "",
        "notes": notes[:240] or "公开 feed",
    }


def normalize_online_sources(raw_sources: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_sources, list):
        raise ValueError("sources must be an array")
    if len(raw_sources) > 300:
        raise ValueError("too many online sources")
    check_public_payload_safe(raw_sources, "sources")
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for index, source in enumerate(raw_sources):
        record = normalize_online_source_record(source, index)
        if not record:
            continue
        by_key[(record["type"], record["locator"])] = record
    return sorted(
        by_key.values(),
        key=lambda item: (TYPE_ORDER.get(item["type"], 99), item["id"]),
    )


def generated_opml_source(enabled: bool) -> dict[str, Any]:
    return {
        "id": ONLINE_OPML_SOURCE_ID,
        "name": "线上 RSS/YouTube 订阅包",
        "type": "opmlrss",
        "enabled": enabled,
        "channel": "RSS/OPML",
        "target": str(ONLINE_OPML_FILENAME).replace("\\", "/"),
        "locator": str(ONLINE_OPML_FILENAME).replace("\\", "/"),
        "env": "",
        "notes": "公开 feed 列表",
    }


def build_online_config(sources: list[dict[str, Any]], updated_at: str | None = None) -> dict[str, Any]:
    rss_sources = [source for source in sources if source["type"] == "rss"]
    config_sources = [dict(source) for source in sources]
    if rss_sources:
        config_sources.append(generated_opml_source(any(source.get("enabled") is not False for source in rss_sources)))
    return {
        "version": "1.0",
        "mode": "online-public-source-config",
        "updated_at": updated_at or utc_timestamp(),
        "sources": config_sources,
    }


def read_online_opml(root_dir: Path) -> list[dict[str, Any]]:
    _, path = ensure_public_online_paths(root_dir)
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for outline in root.findall(".//outline"):
        xml_url = str(outline.attrib.get("xmlUrl") or "").strip()
        if not xml_url or xml_url in seen:
            continue
        try:
            feed_url = normalize_http_url(xml_url, len(sources))
        except ValueError:
            continue
        seen.add(feed_url)
        title = str(outline.attrib.get("title") or outline.attrib.get("text") or feed_url).strip()
        sources.append(
            {
                "id": feed_id_for_url(feed_url),
                "name": title[:120],
                "type": "rss",
                "enabled": True,
                "channel": "RSS/YouTube",
                "target": title[:120],
                "locator": feed_url,
                "env": "",
                "notes": "公开 feed",
            }
        )
    return sources


def write_online_opml(root_dir: Path, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _, path = ensure_public_online_paths(root_dir)
    feeds = [source for source in sources if source["type"] == "rss" and source.get("enabled") is not False]
    path.parent.mkdir(parents=True, exist_ok=True)
    opml = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(opml, "head")
    title = ET.SubElement(head, "title")
    title.text = "AI News Radar Online Sources"
    body = ET.SubElement(opml, "body")
    for feed in feeds:
        ET.SubElement(
            body,
            "outline",
            {
                "text": feed["name"],
                "title": feed["name"],
                "type": "rss",
                "xmlUrl": feed["locator"],
                "htmlUrl": "",
            },
        )
    tree = ET.ElementTree(opml)
    ET.indent(tree, space="  ")
    tmp_path = path.with_suffix(".opml.tmp")
    tree.write(tmp_path, encoding="utf-8", xml_declaration=True)
    os.replace(tmp_path, path)
    return feeds


def online_user_sources_from_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sources = config.get("sources") if isinstance(config, dict) else []
    normalized = normalize_online_sources(raw_sources)
    return normalized


def read_online_source_config(root_dir: Path) -> dict[str, Any]:
    config_path, opml_path = ensure_public_online_paths(root_dir)
    config: dict[str, Any]
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        check_public_payload_safe(config, "config")
        if not isinstance(config.get("sources"), list):
            raise ValueError("online config must contain a sources array")
        sources = online_user_sources_from_config(config)
    else:
        sources = []
        config = build_online_config(sources)
    opml_sources = read_online_opml(root_dir)
    existing_feed_urls = {source["locator"] for source in sources if source["type"] == "rss"}
    sources.extend(source for source in opml_sources if source["locator"] not in existing_feed_urls)
    sources = normalize_online_sources(sources)
    if not config_path.exists() or sources != online_user_sources_from_config(config):
        config = build_online_config(sources, updated_at=config.get("updated_at") if isinstance(config, dict) else None)
    return {
        "ok": True,
        "path": str(ONLINE_CONFIG_FILENAME).replace("\\", "/"),
        "opml_path": str(ONLINE_OPML_FILENAME).replace("\\", "/"),
        "exists": config_path.exists(),
        "opml_exists": opml_path.exists(),
        "source_count": len(sources),
        "enabled_source_count": sum(1 for source in sources if source.get("enabled") is not False),
        "config": config,
        "sources": sources,
    }


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def write_online_source_config(root_dir: Path, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    raw_sources = payload.get("sources")
    sources = normalize_online_sources(raw_sources)
    config = build_online_config(sources)
    config_path, _ = ensure_public_online_paths(root_dir)
    existing_count = 0
    if config_path.exists():
        existing_payload = json.loads(config_path.read_text(encoding="utf-8"))
        existing_sources = existing_payload.get("sources") if isinstance(existing_payload, dict) else []
        existing_count = len(existing_sources) if isinstance(existing_sources, list) else 0
    new_count = len(sources)
    confirm_bulk_delete = payload.get("confirm_bulk_delete") is True
    if existing_count >= 3 and new_count * 2 < existing_count and not confirm_bulk_delete:
        raise ValueError(
            "online_sources_bulk_delete_blocked: "
            f"本次写入会把 {existing_count} 个线上信源删到 {new_count} 个，已阻止；"
            "如确实要批量删除，请带 confirm_bulk_delete"
        )
    write_json_atomic(config_path, config)
    written_feeds = write_online_opml(root_dir, sources)
    return {
        "ok": True,
        "path": str(ONLINE_CONFIG_FILENAME).replace("\\", "/"),
        "opml_path": str(ONLINE_OPML_FILENAME).replace("\\", "/"),
        "source_count": len(sources),
        "enabled_source_count": sum(1 for source in sources if source.get("enabled") is not False),
        "opml_feed_count": len(written_feeds),
        "config": config,
        "sources": sources,
    }


def git_run(root_dir: Path, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root_dir),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def git_checked(root_dir: Path, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    completed = git_run(root_dir, args, timeout=timeout)
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "git command failed").strip()
        raise RuntimeError(message)
    return completed


def git_name_list(root_dir: Path, args: list[str]) -> list[str]:
    completed = git_checked(root_dir, args)
    return [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]


def sync_online_source_config(root_dir: Path, payload: Any | None = None, *, push: bool = True) -> dict[str, Any]:
    write_result = write_online_source_config(root_dir, payload) if payload is not None else read_online_source_config(root_dir)
    allowed_paths = [
        str(ONLINE_CONFIG_FILENAME).replace("\\", "/"),
        str(ONLINE_OPML_FILENAME).replace("\\", "/"),
    ]
    top = git_checked(root_dir, ["rev-parse", "--show-toplevel"]).stdout.strip()
    if Path(top).resolve() != root_dir.resolve():
        raise ValueError("online sync must run from the repo root")

    pre_staged = git_name_list(root_dir, ["diff", "--cached", "--name-only"])
    blocked_staged = [path for path in pre_staged if path not in allowed_paths]
    if blocked_staged:
        raise ValueError("unrelated_files_already_staged:" + ",".join(blocked_staged))

    git_checked(root_dir, ["add", "--", *allowed_paths])
    staged = git_name_list(root_dir, ["diff", "--cached", "--name-only"])
    blocked_after_add = [path for path in staged if path not in allowed_paths]
    if blocked_after_add:
        raise ValueError("blocked_staged_files:" + ",".join(blocked_after_add))

    staged_allowed = git_name_list(root_dir, ["diff", "--cached", "--name-only", "--", *allowed_paths])
    if not staged_allowed:
        return {
            **write_result,
            "synced": False,
            "no_changes": True,
            "staged_paths": [],
            "commit": "",
            "pushed": False,
        }

    git_checked(root_dir, ["commit", "-m", ONLINE_COMMIT_MESSAGE, "--", *allowed_paths], timeout=60)
    pushed = False
    push_stdout = ""
    if push:
        branch = git_checked(root_dir, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        try:
            git_checked(root_dir, ["pull", "--rebase", "origin", branch], timeout=120)
        except RuntimeError as exc:
            git_run(root_dir, ["rebase", "--abort"], timeout=60)
            raise ValueError(f"online_sources_rebase_failed: git pull --rebase 失败，已中止推送：{exc}") from exc
        pushed_result = git_checked(root_dir, ["push"], timeout=120)
        pushed = True
        push_stdout = (pushed_result.stdout or pushed_result.stderr or "").strip()
    commit = git_checked(root_dir, ["rev-parse", "--short", "HEAD"]).stdout.strip()
    return {
        **write_result,
        "synced": True,
        "no_changes": False,
        "staged_paths": staged_allowed,
        "commit": commit,
        "pushed": pushed,
        "push_output": push_stdout,
    }
