"""Shared utility helpers for local server modules."""

from __future__ import annotations

import json
import os
import urllib.parse
from pathlib import Path
from typing import Any

from scripts.radar.server import (
    BILIBILI_DEFAULT_COOKIE_FILE,
    CONFIG_FILENAME,
    DOUYIN_HOME_URL,
    MEDIACRAWLER_LOCAL_DIR_NAME,
    WEWE_RSS_BASE_URL_DEFAULT,
    XIAOHONGSHU_HOME_URL,
)


def validate_source_config(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("config root must be a JSON object")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise ValueError("config must contain a sources array")
    if len(sources) > 500:
        raise ValueError("too many sources")
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"sources[{index}] must be an object")
        source_id = str(source.get("id") or "").strip()
        name = str(source.get("name") or "").strip()
        if not source_id:
            raise ValueError(f"sources[{index}].id is required")
        if not name:
            raise ValueError(f"sources[{index}].name is required")
    return payload


def read_source_config(root_dir: Path) -> dict[str, Any] | None:
    path = root_dir / CONFIG_FILENAME
    if not path.exists():
        return None
    return validate_source_config(json.loads(path.read_text(encoding="utf-8")))


def source_config_runtime_ids(source: dict[str, Any]) -> set[str]:
    raw_id = str(source.get("id") or "").strip().lower()
    raw_type = str(source.get("type") or "").strip().lower()
    channel = str(source.get("channel") or "").lower()
    target = str(source.get("target") or "").lower()
    locator = str(source.get("locator") or "").lower()
    haystack = f"{raw_id} {raw_type} {channel} {target} {locator}"
    runtime_ids: set[str] = set()
    if raw_type == "wewe_rss" or raw_id.startswith("wewe_rss") or "wewe_rss" in haystack or "wewe rss" in haystack:
        runtime_ids.add("wewe_rss")
    if "we_mp_rss_jsonl" not in haystack and (raw_type == "we_mp_rss" or raw_id.startswith("we_mp_rss") or "we_mp_rss" in haystack):
        runtime_ids.add("we_mp_rss")
    if raw_type == "we_mp_rss_jsonl" or raw_id.startswith("we_mp_rss_jsonl") or "we_mp_rss_jsonl" in haystack:
        runtime_ids.add("we_mp_rss_jsonl")
    if raw_type == "bilibili_dynamic" or "bilibili" in haystack or "b站" in haystack:
        runtime_ids.add("bilibili_dynamic")
    if raw_type in {"rss", "opml"} or "youtube.com/feeds/videos.xml" in haystack or "youtube" in haystack or "油管" in haystack:
        runtime_ids.add("opmlrss")
    if "github" in haystack and ("release" in haystack or "releases" in haystack):
        runtime_ids.add("github_foundation_sunshine_releases")
    if raw_type == "mediacrawler_jsonl":
        if "xhs" in haystack or "xiaohongshu" in haystack or "小红书" in haystack:
            runtime_ids.add("mediacrawler_xhs")
        if "douyin" in haystack or "抖音" in haystack:
            runtime_ids.add("mediacrawler_douyin")
    return runtime_ids


def enabled_source_config_records(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not config:
        return []
    sources = config.get("sources")
    if not isinstance(sources, list):
        return []
    return [source for source in sources if isinstance(source, dict) and source.get("enabled") is not False]


def resolve_config_path(root_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = root_dir / path
    return path


def is_url_like(value: str) -> bool:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def mediacrawler_local_root(root_dir: Path) -> Path:
    configured = str(os.environ.get("MEDIACRAWLER_LOCAL_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (root_dir.parent / MEDIACRAWLER_LOCAL_DIR_NAME).resolve()


def default_mediacrawler_jsonl_dir(root_dir: Path, runtime_id: str) -> Path:
    folder = "xhs" if runtime_id == "mediacrawler_xhs" else "douyin"
    return mediacrawler_local_root(root_dir) / "output" / folder / "jsonl"


def resolve_mediacrawler_locator(root_dir: Path, runtime_id: str, locator: str) -> Path:
    raw = str(locator or "").strip()
    if not raw or is_url_like(raw):
        return default_mediacrawler_jsonl_dir(root_dir, runtime_id)
    return resolve_config_path(root_dir, raw)


def add_maintenance_issue(
    issues: list[dict[str, Any]],
    issue_id: str,
    severity: str,
    source_id: str,
    title: str,
    detail: str,
    action: str,
    fix_actions: list[dict[str, Any]] | None = None,
) -> None:
    issue = {
        "id": issue_id,
        "severity": severity,
        "source_id": source_id,
        "title": title,
        "detail": detail,
        "action": action,
    }
    if fix_actions:
        issue["fix_actions"] = fix_actions
    issues.append(issue)


def open_url_action(action_id: str, label: str, url: str) -> dict[str, Any]:
    return {"id": action_id, "kind": "open_url", "label": label, "url": url}


def open_path_action(action_id: str, label: str, path: Path) -> dict[str, Any]:
    return {"id": action_id, "kind": "open_path", "label": label, "path": str(path)}


def start_service_action(action_id: str, label: str) -> dict[str, Any]:
    return {"id": action_id, "kind": "start_service", "label": label}


def wewe_dashboard_url() -> str:
    base_url = (os.environ.get("WEWE_RSS_BASE_URL") or WEWE_RSS_BASE_URL_DEFAULT).strip().rstrip("/")
    return base_url + "/dash"


def wewe_fix_actions(include_start: bool = False) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if include_start:
        actions.append(start_service_action("start_wewe_rss_sidecar", "启动后台/扫码"))
    actions.append(open_url_action("open_wewe_rss_dashboard", "打开后台/扫码", wewe_dashboard_url()))
    return actions


def bilibili_fix_actions(root_dir: Path | None = None) -> list[dict[str, Any]]:
    cookie_folder = (root_dir / BILIBILI_DEFAULT_COOKIE_FILE.parent) if root_dir else BILIBILI_DEFAULT_COOKIE_FILE.parent
    return [
        start_service_action("open_bilibili_login", "打开B站小号登录"),
        start_service_action("sync_bilibili_cookie", "同步cookie"),
        open_path_action("open_bilibili_cookie_folder", "打开cookie文件夹", cookie_folder),
    ]


def bilibili_cookie_file_path(root_dir: Path) -> Path:
    configured = str(os.environ.get("BILIBILI_COOKIE_FILE") or os.environ.get("BILIBILI_DYNAMIC_COOKIE_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return root_dir / BILIBILI_DEFAULT_COOKIE_FILE


def bilibili_cookie_status(root_dir: Path) -> dict[str, Any]:
    has_env_cookie = bool(str(os.environ.get("BILIBILI_COOKIE") or os.environ.get("BILIBILI_DYNAMIC_COOKIE") or "").strip())
    cookie_file = bilibili_cookie_file_path(root_dir)
    file_exists = cookie_file.exists() and cookie_file.is_file() and cookie_file.stat().st_size > 0
    return {
        "configured": has_env_cookie or file_exists,
        "env_cookie_present": has_env_cookie,
        "cookie_file": str(cookie_file),
        "cookie_file_exists": file_exists,
        "recommended_cookie_file": str(root_dir / BILIBILI_DEFAULT_COOKIE_FILE),
    }


def platform_url_for_runtime_id(runtime_id: str) -> str:
    if runtime_id == "mediacrawler_xhs":
        return XIAOHONGSHU_HOME_URL
    if runtime_id == "mediacrawler_douyin":
        return DOUYIN_HOME_URL
    return ""


def platform_label_for_runtime_id(runtime_id: str) -> str:
    if runtime_id == "mediacrawler_xhs":
        return "打开小红书"
    if runtime_id == "mediacrawler_douyin":
        return "打开抖音"
    return "打开平台"


def existing_open_target(path: Path) -> Path | None:
    if path.exists():
        return path.parent if path.is_file() else path
    candidate = path.parent
    while candidate != candidate.parent:
        if candidate.exists():
            return candidate
        candidate = candidate.parent
    return candidate if candidate.exists() else None


def resolve_latest_mediacrawler_jsonl(raw_path: Path) -> Path:
    path = raw_path.expanduser()
    if path.is_dir():
        candidates = sorted(
            path.glob("creator_contents_*.jsonl"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        non_empty_candidates = [candidate for candidate in candidates if candidate.stat().st_size > 0]
        if non_empty_candidates:
            return non_empty_candidates[0]
        return candidates[0] if candidates else path
    if path.parent.exists() and (not path.exists() or path.name.startswith("creator_contents_")):
        candidates = sorted(
            path.parent.glob("creator_contents_*.jsonl"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        non_empty_candidates = [candidate for candidate in candidates if candidate.stat().st_size > 0]
        if non_empty_candidates and (not path.exists() or path.stat().st_size <= 0 or non_empty_candidates[0].stat().st_mtime >= path.stat().st_mtime):
            return non_empty_candidates[0]
        if candidates and (not path.exists() or candidates[0].stat().st_mtime >= path.stat().st_mtime):
            return candidates[0]
    return path


def mediacrawler_fix_actions(root_dir: Path, runtime_id: str, raw_path: str = "") -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if runtime_id == "mediacrawler_douyin":
        actions.append(start_service_action("start_mediacrawler_douyin", "启动抖音采集"))
    if runtime_id == "mediacrawler_xhs":
        actions.append(start_service_action("start_mediacrawler_xhs", "启动小红书采集"))
    target = existing_open_target(resolve_mediacrawler_locator(root_dir, runtime_id, raw_path))
    if target:
        actions.append(open_path_action(f"open_{runtime_id}_jsonl_folder", "打开JSONL文件夹", target))
    platform_url = platform_url_for_runtime_id(runtime_id)
    if platform_url:
        actions.append(open_url_action(f"open_{runtime_id}_platform", platform_label_for_runtime_id(runtime_id), platform_url))
    return actions


def maintenance_action_for_error(site_id: str, error: str) -> str:
    text = str(error or "")
    if site_id == "wewe_rss":
        if "no_feeds" in text:
            return "打开 WeWe RSS 后台，确认公众号已订阅，并检查 WEWE_RSS_FEEDS 或 /feeds 输出。"
        if "base_url" in text or "Connection" in text or "HTTPConnection" in text:
            return "先启动 wewe-rss-sidecar，再确认 http://127.0.0.1:4000 可以访问。"
        return "先看 WeWe RSS 后台是否需要重新扫码或重新添加公众号。"
    if site_id in {"mediacrawler_douyin", "mediacrawler_xhs"}:
        if "not_found" in text or "missing" in text:
            return "先运行对应平台的 MediaCrawler，生成新的 creator_contents_*.jsonl，或修正 sources.config.json 里的 JSONL 路径。"
        return "先检查 MediaCrawler 是否能单独抓取，再让本看板读取新导出的 JSONL。"
    if site_id == "bilibili_dynamic":
        return "重新导出 B站 cookie，或接受当前公开接口兜底结果。不要把 cookie 写进仓库。"
    return "检查该源的地址、网络、接口返回和 sources.config.json 配置。"


def is_no_new_in_collection_window(site: dict[str, Any]) -> bool:
    collection_window_hours = int(site.get("collection_window_hours") or 0)
    raw_item_count = int(site.get("raw_item_count") or 0)
    window_item_count = int(site.get("window_item_count") or site.get("item_count") or 0)
    return collection_window_hours > 0 and raw_item_count > 0 and window_item_count == 0


def maintenance_issues_from_status(payload: dict[str, Any], root_dir: Path | None = None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    sites = [site for site in payload.get("sites", []) if isinstance(site, dict)]
    for site in sites:
        site_id = str(site.get("site_id") or "")
        name = str(site.get("site_name") or site.get("source_name") or site.get("site_id") or "未知来源")
        error = str(site.get("error") or "")
        has_failed_wewe_feed = site_id == "wewe_rss" and any(
            isinstance(feed, dict) and feed.get("ok") is False
            for feed in site.get("feeds") or []
        )
        if site.get("ok") is False and not has_failed_wewe_feed:
            add_maintenance_issue(
                issues,
                f"{site_id or 'source'}_failed",
                "bad",
                site_id,
                f"{name} 抓取失败",
                error or "本轮没有成功返回数据。",
                maintenance_action_for_error(site_id, error),
                wewe_fix_actions(include_start=True) if site_id == "wewe_rss" else bilibili_fix_actions(root_dir) if site_id == "bilibili_dynamic" else [],
            )
        elif site.get("ok") is True and int(site.get("item_count") or 0) == 0 and not is_no_new_in_collection_window(site):
            add_maintenance_issue(
                issues,
                f"{site_id or 'source'}_zero_items",
                "warn",
                site_id,
                f"{name} 本轮 0 条",
                "接口能访问，但没有抓到可入池内容。",
                "先确认订阅对象最近是否更新；如果确认有更新，再检查源地址、时间窗口和过滤规则。",
            )

        if site_id == "bilibili_dynamic":
            if site.get("cookie_present") is False:
                add_maintenance_issue(
                    issues,
                    "bilibili_cookie_missing",
                    "warn",
                    site_id,
                    "B站 cookie 未配置",
                    "当前走公开接口兜底，可能拿不到完整动态。",
                    "如需完整动态，重新导出 B站 cookie 并通过环境变量或本地 cookie 文件配置；不要提交 cookie。",
                    bilibili_fix_actions(root_dir),
                )
            for account in site.get("accounts") or []:
                if isinstance(account, dict) and account.get("ok") is False:
                    add_maintenance_issue(
                        issues,
                        f"bilibili_account_{account.get('uid')}_failed",
                        "bad",
                        site_id,
                        f"B站账号 {account.get('source_name') or account.get('uid')} 抓取失败",
                        str(account.get("error") or "账号级抓取失败。"),
                        "检查 UID 是否正确；如果 cookie 模式失败，重新导出 B站 cookie。",
                        bilibili_fix_actions(root_dir),
                    )

        if site_id == "wewe_rss":
            for feed in site.get("feeds") or []:
                if isinstance(feed, dict) and feed.get("ok") is False:
                    add_maintenance_issue(
                        issues,
                        f"wewe_feed_{feed.get('id')}_failed",
                        "bad",
                        site_id,
                        f"公众号 {feed.get('name') or feed.get('id')} 读取失败",
                        str(feed.get("error") or "WeWe RSS feed 没有返回正常数据。"),
                        "打开 WeWe RSS 后台确认是否需要扫码、重新登录或重新订阅该公众号。",
                        wewe_fix_actions(include_start=True),
                    )

    source_config = payload.get("source_config")
    if isinstance(source_config, dict) and source_config.get("ok") is False:
        add_maintenance_issue(
            issues,
            "source_config_invalid",
            "bad",
            "source_config",
            "sources.config.json 读取失败",
            str(source_config.get("error") or "配置文件格式不正确。"),
            "在页面里重新写入配置，或检查 sources.config.json 是否是合法 JSON。",
        )
    return issues


def dedupe_maintenance_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in issues:
        issue_id = str(issue.get("id") or "")
        if issue_id and issue_id in seen:
            continue
        if issue_id:
            seen.add(issue_id)
        deduped.append(issue)
    return deduped


def read_source_status(root_dir: Path) -> dict[str, Any] | None:
    path = root_dir / "data" / "source-status.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
