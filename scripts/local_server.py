#!/usr/bin/env python3
"""Local-only static server with a narrow source-config write endpoint."""

from __future__ import annotations

import argparse
import json
import math
import os
import posixpath
import sys
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

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
from scripts.radar.server import auto_collect as _auto_collect_api  # noqa: E402
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
ADMIN_TOKEN_HEADER = _refresh_api.ADMIN_TOKEN_HEADER
admin_auth_block_remaining = _refresh_api.admin_auth_block_remaining
admin_token_required = _refresh_api.admin_token_required
alive_source_names_by_site = _store_api.alive_source_names_by_site
check_admin_token_value = _refresh_api.check_admin_token_value
deleted_source_names_by_site = _store_api.deleted_source_names_by_site
flush_pending_purge = _store_api.flush_pending_purge
bilibili_cookie_status = _common_api.bilibili_cookie_status
collect_window_hours_for_scope = _refresh_api.collect_window_hours_for_scope
is_item_orphaned = _store_api.is_item_orphaned
is_local_origin = _refresh_api.is_local_origin
is_trusted_origin = _refresh_api.is_trusted_origin
record_admin_auth_failure = _refresh_api.record_admin_auth_failure
reflected_cors_origin = _refresh_api.reflected_cors_origin
reset_admin_auth_failures = _refresh_api.reset_admin_auth_failures
trusted_origins = _refresh_api.trusted_origins
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
preflight_online_source_save = _online_api.preflight_online_source_save
write_youtube_subscriptions = _store_api.write_youtube_subscriptions

_base_json_response = _refresh_api.json_response

_SAVE_SYNC_FILE_PATHS = (
    "config/online-sources.json",
    "feeds/online-sources.opml",
    "data/archive.json",
    "data/latest-24h-all.json",
    "data/latest-24h.json",
    "data/stories-merged.json",
    "data/daily-brief.json",
    "data/pending-purge.json",
)


def _capture_save_sync_snapshot(root_dir: Path, pre_head: str) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for relative in _SAVE_SYNC_FILE_PATHS:
        path = root_dir / relative
        files[relative] = {
            "exists": path.is_file(),
            "content": path.read_bytes() if path.is_file() else b"",
        }
    return {"pre_head": pre_head, "files": files}


def _restore_save_sync_snapshot(root_dir: Path, snapshot: dict[str, Any]) -> None:
    pre_head = str(snapshot.get("pre_head") or "")
    if not pre_head:
        raise _online_api.OnlineSourcesError(
            "online_sources_recovery_pending",
            status_code=409,
            details={"reason": "missing_save_sync_head"},
        )
    if _online_api.git_checked(root_dir, ["rev-parse", "HEAD"]).stdout.strip() != pre_head:
        raise _online_api.OnlineSourcesError(
            "online_sources_recovery_pending",
            status_code=409,
            details={"reason": "head_changed_during_save_sync"},
        )
    if _online_api.operation_manifest_path(root_dir).exists():
        raise _online_api.OnlineSourcesError(
            "online_sources_recovery_pending",
            status_code=409,
            details={"reason": "git_operation_recovery_pending"},
        )
    staged = _online_api.git_name_list(root_dir, ["diff", "--cached", "--name-only"])
    if staged:
        raise _online_api.OnlineSourcesError(
            "online_sources_recovery_pending",
            status_code=409,
            details={"reason": "index_changed_during_save_sync"},
        )

    files = snapshot.get("files")
    if not isinstance(files, dict):
        raise _online_api.OnlineSourcesError(
            "online_sources_recovery_pending",
            status_code=409,
            details={"reason": "save_sync_snapshot_invalid"},
        )
    restore_paths: list[str] = []
    for relative in ("config/online-sources.json", "feeds/online-sources.opml"):
        proof = files.get(relative)
        if not isinstance(proof, dict):
            raise _online_api.OnlineSourcesError(
                "online_sources_recovery_pending",
                status_code=409,
                details={"reason": "online_source_snapshot_invalid"},
            )
        tracked_at_head = _online_api._git_blob_oid(root_dir, pre_head, relative) is not None
        if tracked_at_head != bool(proof.get("exists")):
            raise _online_api.OnlineSourcesError(
                "online_sources_recovery_pending",
                status_code=409,
                details={"reason": "online_source_snapshot_not_at_head"},
            )
        head_bytes = _online_api._git_blob_bytes(root_dir, pre_head, relative)
        expected_bytes = proof.get("content", b"") if proof.get("exists") else b""
        if head_bytes != expected_bytes:
            raise _online_api.OnlineSourcesError(
                "online_sources_recovery_pending",
                status_code=409,
                details={"reason": "online_source_snapshot_not_at_head"},
            )
        if tracked_at_head:
            restore_paths.append(relative)

    if restore_paths:
        _online_api.git_checked(
            root_dir,
            [
                "restore",
                f"--source={pre_head}",
                "--staged",
                "--worktree",
                "--",
                *restore_paths,
            ],
            timeout=60,
        )
    for relative, proof in files.items():
        path = root_dir / relative
        exists = bool(proof.get("exists"))
        content = proof.get("content", b"")
        if exists:
            if not isinstance(content, bytes):
                raise _online_api.OnlineSourcesError(
                    "online_sources_recovery_pending",
                    status_code=409,
                    details={"reason": "save_sync_snapshot_invalid"},
                )
            _online_api.atomic_replace_bytes(path, content)
        elif path.exists():
            path.unlink()
    for relative, proof in files.items():
        path = root_dir / relative
        if bool(proof.get("exists")) != path.is_file():
            raise _online_api.OnlineSourcesError(
                "online_sources_recovery_pending",
                status_code=409,
                details={"reason": "save_sync_rollback_verification_failed"},
            )
        if path.is_file() and path.read_bytes() != proof.get("content", b""):
            raise _online_api.OnlineSourcesError(
                "online_sources_recovery_pending",
                status_code=409,
                details={"reason": "save_sync_rollback_verification_failed"},
            )


def json_response(
    handler: SimpleHTTPRequestHandler,
    status: int,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> None:
    """json_response wrapper that reflects CORS headers for trusted remote origins."""
    merged = dict(headers or {})
    try:
        origin = handler.headers.get("Origin", "")
    except AttributeError:
        origin = ""
    cors_origin = reflected_cors_origin(origin)
    if cors_origin:
        merged.setdefault("Access-Control-Allow-Origin", cors_origin)
        merged.setdefault("Vary", "Origin")
        merged.setdefault("Access-Control-Expose-Headers", "ETag")
    _base_json_response(handler, status, payload, headers=merged)


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
    _defer_auto_collect: bool = False,
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
        # 新增抖音/微信信源时登记一次本机采集（云端 Actions 抓不了这两类）。
        # 只登记不触发：真正派发要等同步确认推送成功，否则采集会拖慢紧随其后的
        # git push，导致前端「Failed to fetch」。任何失败都不得影响本次保存的结果。
        if not _defer_auto_collect:
            try:
                result["auto_collect"] = _auto_collect_api.handle_saved_config(
                    root_dir,
                    previous_config if isinstance(previous_config, dict) else None,
                    result["config"],
                )
            except Exception as exc:  # noqa: BLE001 - 保存结果优先于采集登记
                result["auto_collect"] = {"pending": False, "error": str(exc)}
        return result


def save_and_sync_online_source_config(
    root_dir: Path,
    payload: dict[str, Any],
    *,
    if_match: Any = None,
) -> dict[str, Any]:
    with _online_api.online_sources_guard():
        current = read_online_source_config(root_dir).get("config")
        current_config = current if isinstance(current, dict) else {"sources": []}
        effective_if_match = if_match
        if effective_if_match is None:
            effective_if_match = _online_api.online_config_etag(current_config)
        target = preflight_online_source_save(root_dir)
        snapshot = _capture_save_sync_snapshot(root_dir, target["pre_head"])
        try:
            save_result = save_online_source_config(
                root_dir,
                payload,
                if_match=effective_if_match,
                _defer_auto_collect=True,
            )
            purge_summary = save_result.get("purged_items", {})
            if isinstance(purge_summary, dict) and purge_summary.get("error"):
                raise _online_api.OnlineSourcesError(
                    "online_sources_purge_failed",
                    status_code=500,
                    details={"reason": "purge_failed"},
                )
            sync_result = sync_saved_online_source_config(
                root_dir,
                if_match=save_result["etag"],
            )
            outcome = sync_result.get("outcome")
            if sync_result.get("ok") is False or (
                outcome is not None and outcome not in {"pushed", "no_change"}
            ):
                raise _online_api.OnlineSourcesError(
                    "online_sources_sync_incomplete",
                    status_code=409,
                    details={"reason": str(outcome or "unknown")},
                )
            sync_result["purged_items"] = purge_summary
            try:
                sync_result["auto_collect"] = _auto_collect_api.handle_saved_config(
                    root_dir,
                    current_config,
                    save_result["config"],
                )
                if sync_result.get("pushed") or outcome == "no_change":
                    sync_result["auto_collect"] = _auto_collect_api.flush_pending_collect(root_dir)
            except Exception as exc:  # noqa: BLE001 - 同步结果优先于采集派发
                sync_result["auto_collect"] = {"triggered": False, "error": str(exc)}
            return sync_result
        except Exception:
            try:
                _restore_save_sync_snapshot(root_dir, snapshot)
            except _online_api.OnlineSourcesError:
                raise
            raise


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


ASSETS_CACHE_CONTROL = "public, max-age=31536000, immutable"
HTML_CACHE_CONTROL = "public, max-age=0, s-maxage=600, stale-while-revalidate=86400"
DATA_JSON_CACHE_CONTROL = "public, max-age=0, s-maxage=300, stale-while-revalidate=1800"


def origin_cache_control(path: str) -> str | None:
    """Return the origin Cache-Control for a request path, ignoring the query string.

    /api/* returns None so json_response keeps its existing no-store header
    and this layer does not add a caching directive.
    """
    route = unquote(path.split("?", 1)[0])
    normalized = posixpath.normpath(route).replace("\\", "/")
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if normalized.startswith("/assets/"):
        return ASSETS_CACHE_CONTROL
    if normalized in {"/", "/index.html"}:
        return HTML_CACHE_CONTROL
    if (
        normalized.startswith("/data/")
        and normalized.endswith(".json")
        and "/" not in normalized[len("/data/") :]
    ):
        return DATA_JSON_CACHE_CONTROL
    return None


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
        if is_trusted_origin(origin) and is_trusted_origin(referer):
            return False
        json_response(self, HTTPStatus.FORBIDDEN, {"ok": False, "error": "non_local_origin"})
        return True

    def reject_unauthorized_admin(self) -> bool:
        """Token-mode gate for every /api/* route. No-op when RADAR_ADMIN_TOKEN is unset."""
        if not admin_token_required():
            return False
        client_ip = str(self.client_address[0]) if self.client_address else ""
        remaining = admin_auth_block_remaining(client_ip)
        if remaining > 0:
            retry = max(1, int(math.ceil(remaining)))
            json_response(
                self,
                HTTPStatus.TOO_MANY_REQUESTS,
                {"ok": False, "error": "admin_auth_rate_limited", "retry_after_seconds": retry},
                headers={"Retry-After": str(retry)},
            )
            return True
        verdict = check_admin_token_value(self.headers.get(ADMIN_TOKEN_HEADER))
        if verdict == "ok":
            reset_admin_auth_failures(client_ip)
            return False
        record_admin_auth_failure(client_ip)
        if verdict == "missing":
            json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "admin_token_required"})
        else:
            json_response(self, HTTPStatus.FORBIDDEN, {"ok": False, "error": "admin_token_invalid"})
        return True

    PUBLIC_STATIC_EXACT = frozenset(
        {"/", "/index.html", "/site.webmanifest", "/favicon.ico", "/bilibili-account-preview.html"}
    )
    PUBLIC_STATIC_PREFIXES = ("/assets/", "/data/")
    PUBLIC_STATIC_DENIED_EXACT = frozenset({"/data/pending-purge.json"})

    def send_response(self, code: int, message: str | None = None) -> None:
        self._response_status = int(code)
        super().send_response(code, message)

    def _header_already_set(self, name: str) -> bool:
        prefix = f"{name.lower()}:"
        for line in getattr(self, "_headers_buffer", []) or []:
            if line.lower().startswith(prefix.encode("latin-1")):
                return True
        return False

    def end_headers(self) -> None:
        if (
            getattr(self, "command", "") in {"GET", "HEAD"}
            and getattr(self, "_response_status", None) == int(HTTPStatus.OK)
            and not self._header_already_set("Cache-Control")
        ):
            value = origin_cache_control(self.path)
            if value is not None:
                self.send_header("Cache-Control", value)
        super().end_headers()

    def reject_private_static(self, route: str) -> bool:
        """In token mode (publicly reachable), only serve an explicit static allowlist.

        Private on-disk files (sources.config.json, feeds/follow.opml, local-secrets/,
        .git/, logs, plans, venvs) must never leak through the tunnel. Decoding and
        normalization mirror SimpleHTTPRequestHandler.translate_path so encoded
        traversal like /assets/%2e%2e/sources.config.json is rejected too.
        """
        if not admin_token_required():
            return False
        decoded = unquote(route)
        normalized = posixpath.normpath(decoded).replace("\\", "/")
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        allowed = normalized in self.PUBLIC_STATIC_EXACT or any(
            normalized.startswith(prefix) for prefix in self.PUBLIC_STATIC_PREFIXES
        )
        if normalized in self.PUBLIC_STATIC_DENIED_EXACT:
            allowed = False
        if allowed:
            return False
        json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        return True

    def do_OPTIONS(self) -> None:
        route = self.path.split("?", 1)[0]
        cors_origin = reflected_cors_origin(self.headers.get("Origin", ""))
        self.send_response(HTTPStatus.NO_CONTENT)
        if route.startswith("/api/") and cors_origin:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", f"Content-Type, {ADMIN_TOKEN_HEADER}, If-Match")
            self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:
        route = self.path.split("?", 1)[0]
        if self.reject_private_static(route):
            return
        super().do_HEAD()

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
        if route.startswith("/api/") and self.reject_unauthorized_admin():
            return
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
            if self.reject_private_static(route):
                return
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
        if route.startswith("/api/") and self.reject_unauthorized_admin():
            return
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
        if route == "/api/save-and-sync-online-source-config":
            self.handle_save_and_sync_online_source_config()
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

    def handle_save_and_sync_online_source_config(self) -> None:
        if self.reject_nonlocal_origin():
            return
        payload = self.read_json_body(MAX_CONFIG_BYTES)
        if payload is None:
            return
        if_match = self.require_if_match()
        if if_match is None:
            return
        try:
            result = save_and_sync_online_source_config(
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
        # 推送已完成，此时派发采集才不会拖慢 git push。schtasks 是毫秒级返回，
        # 真正吃资源的 MediaCrawler 要十几秒后才起来，那时响应早已发出。
        try:
            result["auto_collect"] = _auto_collect_api.flush_pending_collect(self.root_dir)
        except Exception as exc:  # noqa: BLE001 - 同步结果优先于采集派发
            result["auto_collect"] = {"triggered": False, "error": str(exc)}
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

    host_is_loopback = args.host in {"127.0.0.1", "localhost", "::1"}
    if not host_is_loopback and not admin_token_required():
        print(
            f"Refusing to bind {args.host}: set {_refresh_api.ADMIN_TOKEN_ENV} before exposing the admin API beyond loopback.",
            file=sys.stderr,
        )
        return 2

    class Handler(LocalRadarHandler):
        def __init__(self, *handler_args: Any, **handler_kwargs: Any) -> None:
            super().__init__(*handler_args, directory=str(root_dir), **handler_kwargs)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.root_dir = root_dir  # type: ignore[attr-defined]
    print(f"Serving {root_dir} at http://{args.host}:{args.port}/")
    print(f"Config endpoint: http://{args.host}:{args.port}/api/source-config")
    print(f"Refresh endpoint: http://{args.host}:{args.port}/api/refresh")
    if admin_token_required():
        print("Admin token mode: ON (all /api/* require X-Admin-Token; static files restricted to allowlist)")
        extra_origins = trusted_origins()
        if extra_origins:
            print(f"Trusted remote origins: {', '.join(extra_origins)}")
    else:
        print("Admin token mode: OFF (loopback local console)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
