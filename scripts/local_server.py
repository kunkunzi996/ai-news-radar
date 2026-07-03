#!/usr/bin/env python3
"""Local-only static server with a narrow source-config write endpoint."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MAX_CONFIG_BYTES = 1024 * 1024
CONFIG_FILENAME = "sources.config.json"
REFRESH_TIMEOUT_SECONDS = 600
REFRESH_LOCK = threading.Lock()


def site_display_name(site: dict[str, Any]) -> str:
    return str(site.get("site_name") or site.get("source_name") or site.get("site_id") or "未知来源")


def add_maintenance_issue(
    issues: list[dict[str, Any]],
    issue_id: str,
    severity: str,
    source_id: str,
    title: str,
    detail: str,
    action: str,
) -> None:
    issues.append(
        {
            "id": issue_id,
            "severity": severity,
            "source_id": source_id,
            "title": title,
            "detail": detail,
            "action": action,
        }
    )


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


def maintenance_issues_from_status(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    sites = [site for site in payload.get("sites", []) if isinstance(site, dict)]
    for site in sites:
        site_id = str(site.get("site_id") or "")
        name = site_display_name(site)
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
            )
        elif site.get("ok") is True and int(site.get("item_count") or 0) == 0:
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


def read_source_status(root_dir: Path) -> dict[str, Any] | None:
    path = root_dir / "data" / "source-status.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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


def json_response(handler: SimpleHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def is_local_origin(value: str) -> bool:
    if not value:
        return True
    return value.startswith("http://127.0.0.1:") or value.startswith("http://localhost:")


def refresh_command(root_dir: Path) -> list[str]:
    return [
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


def source_status_summary(root_dir: Path) -> dict[str, Any]:
    payload = read_source_status(root_dir)
    if not payload:
        return {
            "maintenance_issues": [
                {
                    "id": "source_status_missing",
                    "severity": "warn",
                    "source_id": "source_status",
                    "title": "还没有刷新状态",
                    "detail": "data/source-status.json 不存在或还没生成。",
                    "action": "先点一次执行采集，生成本地源状态。",
                }
            ],
            "issue_count": 1,
            "needs_attention": True,
        }
    issues = maintenance_issues_from_status(payload)
    ok_sites = sum(1 for site in payload.get("sites", []) if isinstance(site, dict) and site.get("ok") is True)
    return {
        "generated_at": payload.get("generated_at"),
        "source_scope": payload.get("source_scope"),
        "fetched_raw_items": payload.get("fetched_raw_items"),
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
                "source_name": site.get("source_name"),
                "error": site.get("error"),
                "cookie_present": site.get("cookie_present"),
                "fetch_mode": site.get("fetch_mode"),
            }
            for site in payload.get("sites", [])
            if isinstance(site, dict)
        ],
    }


def source_config_summary(root_dir: Path) -> dict[str, Any]:
    path = root_dir / CONFIG_FILENAME
    if not path.exists():
        return {"exists": False, "source_count": 0, "enabled_source_count": 0, "enabled_sources": []}
    payload = validate_source_config(json.loads(path.read_text(encoding="utf-8")))
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


def local_status_payload(root_dir: Path) -> dict[str, Any]:
    summary = source_status_summary(root_dir)
    try:
        config = source_config_summary(root_dir)
    except Exception as exc:
        config = {"exists": True, "ok": False, "error": str(exc), "source_count": 0, "enabled_source_count": 0, "enabled_sources": []}
    return {
        "ok": True,
        "source_config": config,
        "source_status": summary,
        "refresh_running": REFRESH_LOCK.locked(),
    }


class LocalRadarHandler(SimpleHTTPRequestHandler):
    server_version = "AIReadRadarLocal/0.1"

    @property
    def root_dir(self) -> Path:
        return Path(self.server.root_dir).resolve()  # type: ignore[attr-defined]

    @property
    def config_path(self) -> Path:
        return (self.root_dir / CONFIG_FILENAME).resolve()

    def reject_nonlocal_origin(self) -> bool:
        origin = self.headers.get("Origin", "")
        referer = self.headers.get("Referer", "")
        if is_local_origin(origin) and is_local_origin(referer):
            return False
        json_response(self, HTTPStatus.FORBIDDEN, {"ok": False, "error": "non_local_origin"})
        return True

    def do_GET(self) -> None:
        route = self.path.split("?", 1)[0]
        if route == "/api/local-status":
            try:
                json_response(self, HTTPStatus.OK, local_status_payload(self.root_dir))
            except Exception as exc:
                json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        if route != "/api/source-config":
            return super().do_GET()
        if self.config_path.parent != self.root_dir or self.config_path.name != CONFIG_FILENAME:
            json_response(self, HTTPStatus.FORBIDDEN, {"ok": False, "error": "invalid_config_path"})
            return
        if not self.config_path.exists():
            json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "source_config_not_found"})
            return
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            validate_source_config(payload)
        except Exception as exc:
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        json_response(self, HTTPStatus.OK, {"ok": True, "path": CONFIG_FILENAME, "config": payload})

    def do_POST(self) -> None:
        route = self.path.split("?", 1)[0]
        if route == "/api/refresh":
            self.handle_refresh()
            return
        if route != "/api/source-config":
            json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        if self.reject_nonlocal_origin():
            return
        if self.config_path.parent != self.root_dir or self.config_path.name != CONFIG_FILENAME:
            json_response(self, HTTPStatus.FORBIDDEN, {"ok": False, "error": "invalid_config_path"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_CONFIG_BYTES:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_content_length"})
            return
        if "application/json" not in str(self.headers.get("Content-Type") or ""):
            json_response(self, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "json_required"})
            return
        try:
            raw = self.rfile.read(length)
            payload = validate_source_config(json.loads(raw.decode("utf-8")))
            payload["updated_at"] = payload.get("updated_at") or ""
            body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            tmp_path = self.config_path.with_suffix(".json.tmp")
            tmp_path.write_text(body, encoding="utf-8")
            os.replace(tmp_path, self.config_path)
        except Exception as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        json_response(
            self,
            HTTPStatus.OK,
            {
                "ok": True,
                "path": CONFIG_FILENAME,
                "source_count": len(payload.get("sources") or []),
            },
        )

    def handle_refresh(self) -> None:
        if self.reject_nonlocal_origin():
            return
        if not self.config_path.exists():
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "source_config_not_found"})
            return
        if not REFRESH_LOCK.acquire(blocking=False):
            json_response(self, HTTPStatus.CONFLICT, {"ok": False, "error": "refresh_already_running"})
            return
        try:
            result = subprocess.run(
                refresh_command(self.root_dir),
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=REFRESH_TIMEOUT_SECONDS,
                check=False,
            )
            if result.returncode != 0:
                json_response(
                    self,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "refresh_failed",
                        "returncode": result.returncode,
                        "stderr_tail": result.stderr[-4000:],
                        "stdout_tail": result.stdout[-2000:],
                    },
                )
                return
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "summary": source_status_summary(self.root_dir),
                    "stdout_tail": result.stdout[-2000:],
                },
            )
        except subprocess.TimeoutExpired as exc:
            json_response(
                self,
                HTTPStatus.REQUEST_TIMEOUT,
                {
                    "ok": False,
                    "error": "refresh_timeout",
                    "timeout_seconds": REFRESH_TIMEOUT_SECONDS,
                    "stdout_tail": (exc.stdout or "")[-2000:],
                    "stderr_tail": (exc.stderr or "")[-4000:],
                },
            )
        except Exception as exc:
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
        finally:
            REFRESH_LOCK.release()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve AI News Radar locally and save sources.config.json")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host; keep 127.0.0.1 for local-only use")
    parser.add_argument("--port", type=int, default=8080, help="Bind port")
    parser.add_argument("--directory", default=".", help="Static site root")
    args = parser.parse_args()

    root_dir = Path(args.directory).resolve()
    if not root_dir.exists():
        print(f"Directory not found: {root_dir}", file=sys.stderr)
        return 2

    class Handler(LocalRadarHandler):
        def __init__(self, *handler_args: Any, **handler_kwargs: Any) -> None:
            super().__init__(*handler_args, directory=str(root_dir), **handler_kwargs)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.root_dir = root_dir  # type: ignore[attr-defined]
    print(f"Serving {root_dir} at http://{args.host}:{args.port}/")
    print(f"Config endpoint: http://{args.host}:{args.port}/api/source-config")
    print(f"Refresh endpoint: http://{args.host}:{args.port}/api/refresh")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
