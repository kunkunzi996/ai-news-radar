#!/usr/bin/env python3
"""Local-only static server with a narrow source-config write endpoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.radar import server as _server_api  # noqa: E402
from scripts.radar.server import (
    COLLECTION_SCOPES,
    CONFIG_FILENAME,
    MAX_ACTION_BYTES,
    MAX_CONFIG_BYTES,
    MAX_SUBSCRIPTION_BYTES,
    OPML_FILENAME,
    REFRESH_LOCK,
    RESTART_DELAY_SECONDS,
    normalize_collection_scope,
)  # noqa: E402
from scripts.radar.server import cdp as _cdp_api  # noqa: E402
from scripts.radar.server import common as _common_api  # noqa: E402
from scripts.radar.server import collectors as _collectors_api  # noqa: E402
from scripts.radar.server import refresh as _refresh_api  # noqa: E402
from scripts.radar.server import subscriptions_store as _store_api  # noqa: E402

BILIBILI_DEFAULT_COOKIE_FILE = _server_api.BILIBILI_DEFAULT_COOKIE_FILE
BILIBILI_PROFILE_DIR = _server_api.BILIBILI_PROFILE_DIR
PURGE_TRACKED_SITE_IDS = _store_api.PURGE_TRACKED_SITE_IDS
alive_source_names_by_site = _store_api.alive_source_names_by_site
bilibili_cookie_status = _common_api.bilibili_cookie_status
collect_window_hours_for_scope = _refresh_api.collect_window_hours_for_scope
is_item_orphaned = _store_api.is_item_orphaned
is_local_origin = _refresh_api.is_local_origin
json_response = _refresh_api.json_response
last_collection_time = _refresh_api.last_collection_time
launch_bilibili_dedicated_browser = _cdp_api.launch_bilibili_dedicated_browser
local_config_maintenance_issues = _collectors_api.local_config_maintenance_issues
local_status_payload = _refresh_api.local_status_payload
maintenance_issues_from_status = _common_api.maintenance_issues_from_status
mediacrawler_douyin_collector_status = _collectors_api.mediacrawler_douyin_collector_status
mediacrawler_xhs_collector_status = _collectors_api.mediacrawler_xhs_collector_status
perform_maintenance_action = _refresh_api.perform_maintenance_action
purge_deleted_source_data = _store_api.purge_deleted_source_data
read_source_config = _store_api.read_source_config
read_wewe_rss_feeds = _collectors_api.read_wewe_rss_feeds
read_youtube_subscriptions = _store_api.read_youtube_subscriptions
refresh_command = _refresh_api.refresh_command
refresh_env = _refresh_api.refresh_env
refresh_progress_snapshot = _refresh_api.refresh_progress_snapshot
refresh_step_plan = _refresh_api.refresh_step_plan
resolve_collect_window_hours = _refresh_api.resolve_collect_window_hours
restart_command = _refresh_api.restart_command
run_refresh_background = _refresh_api.run_refresh_background
schedule_process_restart = _refresh_api.schedule_process_restart
start_mediacrawler_douyin = _collectors_api.start_mediacrawler_douyin
start_mediacrawler_xhs = _collectors_api.start_mediacrawler_xhs
start_wewe_rss_sidecar = _collectors_api.start_wewe_rss_sidecar
sync_bilibili_cookie = _cdp_api.sync_bilibili_cookie
validate_source_config = _store_api.validate_source_config
write_youtube_subscriptions = _store_api.write_youtube_subscriptions

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
        if route == "/api/refresh-progress":
            json_response(self, HTTPStatus.OK, {"ok": True, "progress": refresh_progress_snapshot()})
            return
        if route == "/api/wewe-rss/feeds":
            payload = read_wewe_rss_feeds()
            status = HTTPStatus.OK if payload.get("ok") else HTTPStatus.BAD_GATEWAY
            if payload.get("error") == "wewe_rss_base_url_not_local":
                status = HTTPStatus.BAD_REQUEST
            json_response(self, status, payload)
            return
        if route == "/api/subscriptions/youtube":
            try:
                subscriptions = read_youtube_subscriptions(self.root_dir)
                json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "path": str(OPML_FILENAME).replace("\\", "/"),
                        "subscriptions": subscriptions,
                    },
                )
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
        if route == "/api/maintenance-action":
            self.handle_maintenance_action()
            return
        if route == "/api/refresh":
            self.handle_refresh()
            return
        if route == "/api/restart-local-server":
            self.handle_restart_local_server()
            return
        if route == "/api/subscriptions/youtube":
            self.handle_youtube_subscriptions()
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
            previous_config: dict[str, Any] | None = None
            if self.config_path.exists():
                try:
                    previous_config = json.loads(self.config_path.read_text(encoding="utf-8"))
                except Exception:
                    previous_config = None
            body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            tmp_path = self.config_path.with_suffix(".json.tmp")
            tmp_path.write_text(body, encoding="utf-8")
            os.replace(tmp_path, self.config_path)
        except Exception as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        purged_items: dict[str, Any]
        if REFRESH_LOCK.acquire(blocking=False):
            try:
                purged_items = purge_deleted_source_data(self.root_dir, payload, previous_config=previous_config)
            except Exception as exc:
                purged_items = {"error": str(exc)}
            finally:
                REFRESH_LOCK.release()
        else:
            purged_items = {"skipped": "refresh_in_progress"}
        json_response(
            self,
            HTTPStatus.OK,
            {
                "ok": True,
                "path": CONFIG_FILENAME,
                "source_count": len(payload.get("sources") or []),
                "purged_items": purged_items,
            },
        )

    def handle_youtube_subscriptions(self) -> None:
        if self.reject_nonlocal_origin():
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_SUBSCRIPTION_BYTES:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_content_length"})
            return
        if "application/json" not in str(self.headers.get("Content-Type") or ""):
            json_response(self, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "json_required"})
            return
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            subscriptions = write_youtube_subscriptions(self.root_dir, payload.get("subscriptions"))
        except Exception as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        json_response(
            self,
            HTTPStatus.OK,
            {
                "ok": True,
                "path": str(OPML_FILENAME).replace("\\", "/"),
                "subscription_count": len(subscriptions),
                "subscriptions": subscriptions,
            },
        )

    def handle_maintenance_action(self) -> None:
        if self.reject_nonlocal_origin():
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_ACTION_BYTES:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_content_length"})
            return
        if "application/json" not in str(self.headers.get("Content-Type") or ""):
            json_response(self, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "json_required"})
            return
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
            action_id = str(payload.get("action_id") or "").strip()
            try:
                collection_scope = normalize_collection_scope(payload.get("collection_scope"))
            except ValueError:
                json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "unsupported_collection_scope",
                        "allowed_scopes": sorted(COLLECTION_SCOPES),
                    },
                )
                return
            result = perform_maintenance_action(self.root_dir, action_id, collection_scope=collection_scope)
        except Exception as exc:
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
        json_response(self, status, result)

    def handle_refresh(self) -> None:
        if self.reject_nonlocal_origin():
            return
        if not self.config_path.exists():
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "source_config_not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length < 0 or length > MAX_ACTION_BYTES:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_content_length"})
            return
        payload: dict[str, Any] = {}
        if length:
            if "application/json" not in str(self.headers.get("Content-Type") or ""):
                json_response(self, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "json_required"})
                return
            try:
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("payload must be a JSON object")
            except Exception as exc:
                json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return
        try:
            collection_scope = normalize_collection_scope(payload.get("collection_scope"))
        except ValueError:
            json_response(
                self,
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "unsupported_collection_scope",
                    "allowed_scopes": sorted(COLLECTION_SCOPES),
                },
            )
            return
        if not REFRESH_LOCK.acquire(blocking=False):
            json_response(self, HTTPStatus.CONFLICT, {"ok": False, "error": "refresh_already_running"})
            return
        try:
            source_config = read_source_config(self.root_dir)
            steps = refresh_step_plan(source_config)
            command = refresh_command(self.root_dir, collection_scope)
            worker = threading.Thread(
                target=run_refresh_background,
                args=(self.root_dir, collection_scope, command, steps),
                daemon=True,
            )
            worker.start()
            json_response(
                self,
                HTTPStatus.ACCEPTED,
                {
                    "ok": True,
                    "started": True,
                    "collection_scope": collection_scope,
                    "progress": refresh_progress_snapshot(),
                },
            )
        except Exception as exc:
            REFRESH_LOCK.release()
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

    def handle_restart_local_server(self) -> None:
        if self.reject_nonlocal_origin():
            return
        if REFRESH_LOCK.locked():
            json_response(self, HTTPStatus.CONFLICT, {"ok": False, "error": "refresh_already_running"})
            return
        command = restart_command()
        schedule_process_restart(command, self.root_dir)
        json_response(
            self,
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "restarting": True,
                "delay_seconds": RESTART_DELAY_SECONDS,
                "command": [Path(command[0]).name, *command[1:]],
            },
        )


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
