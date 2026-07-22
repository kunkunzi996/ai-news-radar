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
from scripts.radar.server import github_stars as _github_stars_api  # noqa: E402
from scripts.radar.server import online_sources as _online_api  # noqa: E402
from scripts.radar.server import refresh as _refresh_api  # noqa: E402
from scripts.radar.server import subscriptions_store as _store_api  # noqa: E402

BILIBILI_DEFAULT_COOKIE_FILE = _server_api.BILIBILI_DEFAULT_COOKIE_FILE
BILIBILI_PROFILE_DIR = _server_api.BILIBILI_PROFILE_DIR
PURGE_TRACKED_SITE_IDS = _store_api.PURGE_TRACKED_SITE_IDS
alive_source_names_by_site = _store_api.alive_source_names_by_site
deleted_source_names_by_site = _store_api.deleted_source_names_by_site
flush_pending_purge = _store_api.flush_pending_purge
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
orphan_history_preview = _store_api.orphan_history_preview
purge_selected_sources = _store_api.purge_selected_sources
queue_pending_purge = _store_api.queue_pending_purge
read_online_source_config = _online_api.read_online_source_config
apply_github_star_sync = _github_stars_api.apply_github_star_sync
preview_github_star_sync = _github_stars_api.preview_github_star_sync
unbind_github_star_sync = _github_stars_api.unbind_github_star_sync
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
start_we_mp_rss_sidecar = _collectors_api.start_we_mp_rss_sidecar
sync_online_source_config = _online_api.sync_online_source_config
sync_saved_online_source_config = _online_api.sync_saved_online_source_config
sync_bilibili_cookie = _cdp_api.sync_bilibili_cookie
validate_source_config = _store_api.validate_source_config
write_online_source_config = _online_api.write_online_source_config
write_youtube_subscriptions = _store_api.write_youtube_subscriptions


def purge_or_defer_source_config(
    root_dir: Path,
    config: dict[str, Any],
    previous_config: dict[str, Any] | None,
) -> dict[str, Any]:
    deleted_names = (
        deleted_source_names_by_site(config, previous_config)
        if isinstance(previous_config, dict)
        else {}
    )
    deferred = queue_pending_purge(root_dir, deleted_names, config)
    if not REFRESH_LOCK.acquire(blocking=False):
        return {"deferred": deferred}

    try:
        summary = purge_deleted_source_data(
            root_dir,
            config,
            previous_config=previous_config if isinstance(previous_config, dict) else None,
        )
        pending_summary = flush_pending_purge(root_dir)
        for filename, removed in pending_summary.items():
            summary[filename] = summary.get(filename, 0) + removed
        return summary
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        REFRESH_LOCK.release()


def read_online_source_config_state(root_dir: Path) -> dict[str, Any]:
    with _online_api.online_sources_guard():
        recovery = _online_api.audit_online_source_operation(root_dir)
        result = read_online_source_config(root_dir)
        result["recovery"] = recovery
        return result


def save_online_source_config(
    root_dir: Path,
    payload: dict[str, Any],
    *,
    if_match: Any = None,
) -> dict[str, Any]:
    with _online_api.online_sources_guard():
        previous_config = read_online_source_config(root_dir).get("config")
        if if_match is None:
            result = write_online_source_config(root_dir, payload)
        else:
            if not isinstance(previous_config, dict):
                raise _online_api.OnlineSourcesError(
                    "online_sources_config_stale",
                    status_code=409,
                )
            current_digest = _online_api.online_config_digest(previous_config)
            _online_api.require_online_config_match(if_match, current_digest)
            _current, candidate, _sources, _changed = _online_api.prepare_manual_online_config(
                root_dir,
                payload,
                current_config=previous_config,
            )
            deleted_names = deleted_source_names_by_site(candidate, previous_config)
            if deleted_names:
                queue_pending_purge(root_dir, deleted_names, candidate)
            try:
                result = _online_api.save_online_source_config_transaction(
                    root_dir,
                    payload,
                    if_match=if_match,
                )
            except Exception:
                if deleted_names:
                    queue_pending_purge(root_dir, {}, previous_config)
                raise
        result["purged_items"] = purge_or_defer_source_config(
            root_dir,
            result["config"],
            previous_config if isinstance(previous_config, dict) else None,
        )
        return result


def save_and_sync_online_source_config(
    root_dir: Path,
    payload: dict[str, Any],
    *,
    if_match: Any = None,
) -> dict[str, Any]:
    with _online_api.online_sources_guard():
        save_result = (
            save_online_source_config(root_dir, payload)
            if if_match is None
            else save_online_source_config(root_dir, payload, if_match=if_match)
        )
        sync_result = (
            sync_saved_online_source_config(root_dir, if_match=save_result["etag"])
            if if_match is not None
            else sync_online_source_config(root_dir, None)
        )
        sync_result["purged_items"] = save_result.get("purged_items", {})
        return sync_result


def _safe_merge_conflicts(raw_conflicts: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_conflicts, list):
        return []
    allowed_kinds = {"top_level", "binding", "added_both", "field_diff", "delete_vs_modify"}
    safe_conflicts: list[dict[str, Any]] = []
    for raw_conflict in raw_conflicts[:20]:
        if not isinstance(raw_conflict, dict):
            continue
        kind = raw_conflict.get("kind")
        if not isinstance(kind, str) or kind not in allowed_kinds:
            continue
        conflict: dict[str, Any] = {"kind": kind}
        for key in ("source_id", "source_name", "field"):
            value = raw_conflict.get(key, "")
            if not isinstance(value, str) or len(value) > 80:
                conflict[key] = ""
                continue
            try:
                _online_api.check_public_text_safe(value, f"details.conflicts.{key}")
            except ValueError:
                conflict[key] = ""
            else:
                conflict[key] = value
        for key in ("local_value", "remote_value"):
            value = raw_conflict.get(key)
            if isinstance(value, bool):
                conflict[key] = value
                continue
            if not isinstance(value, str) or len(value) > 80:
                conflict[key] = None
                continue
            try:
                _online_api.check_public_text_safe(value, f"details.conflicts.{key}")
            except ValueError:
                conflict[key] = None
            else:
                conflict[key] = value
        safe_conflicts.append(conflict)
    return safe_conflicts


def api_error_payload(exc: Exception) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, (_online_api.OnlineSourcesError, _github_stars_api.GitHubStarsError)):
        payload: dict[str, Any] = {"ok": False, "error": exc.code}
        safe_details = {
            key: value
            for key, value in exc.details.items()
            if key in {"reason", "retry_after", "rate_limit_remaining", "rate_limit_reset"}
            and isinstance(value, (str, int, float, bool))
        }
        conflicts = _safe_merge_conflicts(exc.details.get("conflicts"))
        if conflicts:
            safe_details["conflicts"] = conflicts
        if safe_details:
            payload["details"] = safe_details
        return exc.status_code, payload
    if isinstance(exc, ValueError):
        code = str(exc).split(":", 1)[0]
        status_by_code = {
            "github_star_managed_fields_readonly": HTTPStatus.CONFLICT,
            "online_source_id_migration_required": HTTPStatus.CONFLICT,
            "online_source_id_conflict": HTTPStatus.CONFLICT,
            "online_sources_bulk_delete_blocked": HTTPStatus.UNPROCESSABLE_ENTITY,
        }
        if code in status_by_code:
            return status_by_code[code], {"ok": False, "error": code}
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_request"}
    return HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "internal_error"}

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

    def read_json_body(self, max_bytes: int) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > max_bytes:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_content_length"})
            return None
        media_type = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().casefold()
        if media_type != "application/json":
            json_response(self, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "json_required"})
            return None
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
            return payload
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return None

    def send_api_error(self, exc: Exception) -> None:
        status, payload = api_error_payload(exc)
        json_response(self, status, payload)

    def require_fields(
        self,
        payload: dict[str, Any],
        *,
        allowed: set[str],
        required: set[str],
    ) -> bool:
        if not required.issubset(payload) or not set(payload).issubset(allowed):
            json_response(
                self,
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_request_fields"},
            )
            return False
        return True

    def require_if_match(self) -> str | None:
        value = self.headers.get("If-Match")
        if not isinstance(value, str) or not value:
            json_response(
                self,
                HTTPStatus.CONFLICT,
                {"ok": False, "error": "online_sources_config_stale"},
            )
            return None
        return value

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
        if route == "/api/online-source-config":
            if self.reject_nonlocal_origin():
                return
            try:
                result = read_online_source_config_state(self.root_dir)
                json_response(
                    self,
                    HTTPStatus.OK,
                    result,
                    headers={"ETag": result["etag"]},
                )
            except Exception as exc:
                self.send_api_error(exc)
            return
        if route == "/api/archive/orphans":
            if self.reject_nonlocal_origin():
                return
            try:
                config = read_online_source_config(self.root_dir).get("config") or {}
                orphans = orphan_history_preview(self.root_dir, config)
                json_response(self, HTTPStatus.OK, {"ok": True, "orphans": orphans})
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
        if route == "/api/online-source-config":
            self.handle_online_source_config()
            return
        if route == "/api/sync-online-source-config":
            self.handle_sync_online_source_config()
            return
        if route == "/api/github-stars/preview":
            self.handle_github_stars_preview()
            return
        if route == "/api/github-stars/apply":
            self.handle_github_stars_apply()
            return
        if route == "/api/github-stars/unbind":
            self.handle_github_stars_unbind()
            return
        if route == "/api/online-source-config/recovery":
            self.handle_online_source_recovery()
            return
        if route == "/api/archive/purge-selected":
            self.handle_purge_selected()
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
        purged_items = purge_or_defer_source_config(self.root_dir, payload, previous_config)
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

    def handle_purge_selected(self) -> None:
        if self.reject_nonlocal_origin():
            return
        payload = self.read_json_body(MAX_CONFIG_BYTES)
        if payload is None:
            return
        try:
            result = purge_selected_sources(self.root_dir, payload.get("pairs"))
        except Exception as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        json_response(self, HTTPStatus.OK, {"ok": True, **result})

    def handle_online_source_config(self) -> None:
        if self.reject_nonlocal_origin():
            return
        payload = self.read_json_body(MAX_CONFIG_BYTES)
        if payload is None:
            return
        if_match = self.require_if_match()
        if if_match is None:
            return
        try:
            result = save_online_source_config(
                self.root_dir,
                payload,
                if_match=if_match,
            )
        except Exception as exc:
            self.send_api_error(exc)
            return
        json_response(self, HTTPStatus.OK, result, headers={"ETag": result["etag"]})

    def handle_sync_online_source_config(self) -> None:
        if self.reject_nonlocal_origin():
            return
        payload = self.read_json_body(MAX_CONFIG_BYTES)
        if payload is None:
            return
        if not self.require_fields(payload, allowed=set(), required=set()):
            return
        if_match = self.require_if_match()
        if if_match is None:
            return
        try:
            result = sync_saved_online_source_config(
                self.root_dir,
                if_match=if_match,
            )
        except Exception as exc:
            self.send_api_error(exc)
            return
        json_response(self, HTTPStatus.OK, result, headers={"ETag": result["etag"]})

    def handle_github_stars_preview(self) -> None:
        if self.reject_nonlocal_origin():
            return
        payload = self.read_json_body(MAX_ACTION_BYTES)
        if payload is None:
            return
        if not self.require_fields(payload, allowed={"username"}, required=set()):
            return
        try:
            result = preview_github_star_sync(self.root_dir, payload)
        except Exception as exc:
            self.send_api_error(exc)
            return
        json_response(self, HTTPStatus.OK, result)

    def handle_github_stars_apply(self) -> None:
        if self.reject_nonlocal_origin():
            return
        payload = self.read_json_body(MAX_ACTION_BYTES)
        if payload is None:
            return
        if not self.require_fields(
            payload,
            allowed={"account_id", "preview_hash"},
            required={"account_id", "preview_hash"},
        ):
            return
        try:
            result = apply_github_star_sync(self.root_dir, payload)
        except Exception as exc:
            self.send_api_error(exc)
            return
        json_response(self, HTTPStatus.OK, result, headers={"ETag": result["etag"]})

    def handle_github_stars_unbind(self) -> None:
        if self.reject_nonlocal_origin():
            return
        payload = self.read_json_body(MAX_ACTION_BYTES)
        if payload is None:
            return
        if not self.require_fields(
            payload,
            allowed={"account_id", "confirmed"},
            required={"account_id", "confirmed"},
        ):
            return
        if_match = self.require_if_match()
        if if_match is None:
            return
        try:
            result = unbind_github_star_sync(
                self.root_dir,
                payload,
                if_match=if_match,
            )
        except Exception as exc:
            self.send_api_error(exc)
            return
        json_response(self, HTTPStatus.OK, result, headers={"ETag": result["etag"]})

    def handle_online_source_recovery(self) -> None:
        if self.reject_nonlocal_origin():
            return
        payload = self.read_json_body(MAX_ACTION_BYTES)
        if payload is None:
            return
        allowed = {"action", "operation_id", "manifest_digest", "confirmed"}
        required = {"action", "operation_id", "manifest_digest"}
        if not self.require_fields(payload, allowed=allowed, required=required):
            return
        try:
            result = _online_api.recover_online_source_operation(
                self.root_dir,
                action=payload.get("action"),
                operation_id=payload.get("operation_id"),
                manifest_digest=payload.get("manifest_digest"),
                confirmed=payload.get("confirmed") is True,
            )
        except Exception as exc:
            self.send_api_error(exc)
            return
        json_response(self, HTTPStatus.OK, result, headers={"ETag": result["etag"]})

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
