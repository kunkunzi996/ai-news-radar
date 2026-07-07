"""Local status maintenance issue helpers."""

from __future__ import annotations

from scripts.radar.server.common import (
    add_maintenance_issue as add_maintenance_issue,
    bilibili_cookie_file_path as bilibili_cookie_file_path,
    bilibili_cookie_status as bilibili_cookie_status,
    bilibili_fix_actions as bilibili_fix_actions,
    dedupe_maintenance_issues as dedupe_maintenance_issues,
    existing_open_target as existing_open_target,
    is_no_new_in_collection_window as is_no_new_in_collection_window,
    maintenance_action_for_error as maintenance_action_for_error,
    maintenance_issues_from_status as maintenance_issues_from_status,
    mediacrawler_fix_actions as mediacrawler_fix_actions,
    open_path_action as open_path_action,
    open_url_action as open_url_action,
    platform_label_for_runtime_id as platform_label_for_runtime_id,
    platform_url_for_runtime_id as platform_url_for_runtime_id,
    read_source_status as read_source_status,
    resolve_latest_mediacrawler_jsonl as resolve_latest_mediacrawler_jsonl,
    start_service_action as start_service_action,
    wewe_dashboard_url as wewe_dashboard_url,
    wewe_fix_actions as wewe_fix_actions,
)

__all__ = [
    "add_maintenance_issue",
    "bilibili_cookie_file_path",
    "bilibili_cookie_status",
    "bilibili_fix_actions",
    "dedupe_maintenance_issues",
    "existing_open_target",
    "is_no_new_in_collection_window",
    "maintenance_action_for_error",
    "maintenance_issues_from_status",
    "mediacrawler_fix_actions",
    "open_path_action",
    "open_url_action",
    "platform_label_for_runtime_id",
    "platform_url_for_runtime_id",
    "read_source_status",
    "resolve_latest_mediacrawler_jsonl",
    "site_display_name",
    "start_service_action",
    "wewe_dashboard_url",
    "wewe_fix_actions",
]


def site_display_name(site: dict[str, object]) -> str:
    return str(site.get("site_name") or site.get("source_name") or site.get("site_id") or "未知来源")
