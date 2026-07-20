#!/usr/bin/env python3
"""GitHub 星标自动同步：供 Actions 在每轮采集前调用。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from scripts.radar.server import github_stars as _github_stars  # noqa: E402
from scripts.radar.server import online_sources as _online_sources  # noqa: E402
from scripts.radar.config_runtime import (  # noqa: E402
    managed_github_repo_sources,
    normalize_repo_identity,
)


STATUS_FILENAME = Path("data") / "github-star-autosync.json"
PURGE_STATE_FILENAME = Path("data") / "github-star-purge-state.json"
MAX_AUTOMATIC_DISABLE_COUNT = 3


class AutosyncError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _status(
    outcome: str,
    *,
    ok: bool,
    account: dict | None = None,
    snapshot: dict | None = None,
    summary: dict | None = None,
    error_code: str = "",
    workflow_identity: dict[str, str] | None = None,
    snapshot_complete: bool = False,
    purge_state_sha256: str = "",
    pending_absent_repo_ids: list[str] | None = None,
    confirmed_absent_repo_ids: list[str] | None = None,
) -> dict:
    workflow = workflow_identity or {}
    payload = {
        "version": 2,
        "ok": ok,
        "outcome": outcome,
        "finished_at": _online_sources.utc_timestamp(),
        "error_code": error_code,
        "workflow_run_id": workflow.get("run_id", ""),
        "workflow_run_attempt": workflow.get("run_attempt", ""),
        "workflow_head_sha": workflow.get("head_sha", ""),
        "snapshot_complete": snapshot_complete,
        "snapshot_completed_at": _online_sources.utc_timestamp() if snapshot_complete else "",
        "purge_state_sha256": purge_state_sha256,
        "pending_absent_repo_ids": sorted(set(pending_absent_repo_ids or [])),
        "confirmed_absent_repo_ids": sorted(set(confirmed_absent_repo_ids or [])),
    }
    if account is not None:
        payload["account_id"] = account.get("id")
        payload["account_login"] = account.get("login")
    if snapshot is not None:
        payload["starred_count"] = snapshot.get("starred_count")
        payload["private_skipped_count"] = snapshot.get("private_skipped_count")
    if summary is not None:
        payload["summary"] = summary
    return payload


def workflow_identity_from_environment() -> dict[str, str] | None:
    run_id = os.environ.get("GITHUB_RUN_ID")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    head_sha = os.environ.get("GITHUB_SHA")
    if not all(isinstance(value, str) and value for value in (run_id, run_attempt, head_sha)):
        return None
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        return None
    return {
        "run_id": run_id,
        "run_attempt": run_attempt,
        "head_sha": head_sha.lower(),
    }


def _sha256_path(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def load_purge_state(path: Path) -> dict[str, Any] | None:
    """Read only the narrow, public state contract used for cleanup approval."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload.get("version") != 1:
        return None
    try:
        account_id = normalize_repo_identity(payload.get("account_id"))
    except ValueError:
        return None
    required_text = (
        "last_complete_snapshot_at",
        "last_snapshot_run_id",
        "last_snapshot_run_attempt",
        "last_snapshot_head_sha",
    )
    if any(not isinstance(payload.get(key), str) or not payload[key] for key in required_text):
        return None
    if not re.fullmatch(r"[0-9a-fA-F]{40}", payload["last_snapshot_head_sha"]):
        return None
    raw_confirmations = payload.get("absence_confirmations")
    if not isinstance(raw_confirmations, dict):
        return None
    confirmations: dict[str, int] = {}
    for raw_repo_id, raw_count in raw_confirmations.items():
        try:
            repo_id = normalize_repo_identity(raw_repo_id, allow_integer=False)
        except ValueError:
            return None
        if repo_id in confirmations or type(raw_count) is not int or raw_count not in {1, 2}:
            return None
        confirmations[repo_id] = raw_count
    return {
        "version": 1,
        "account_id": int(account_id),
        "last_complete_snapshot_at": payload["last_complete_snapshot_at"],
        "last_snapshot_run_id": payload["last_snapshot_run_id"],
        "last_snapshot_run_attempt": payload["last_snapshot_run_attempt"],
        "last_snapshot_head_sha": payload["last_snapshot_head_sha"].lower(),
        "absence_confirmations": confirmations,
    }


def _write_purge_state(path: Path, payload: dict[str, Any]) -> str:
    try:
        _online_sources.write_json_atomic(path, payload)
    except OSError as exc:
        raise AutosyncError("purge_state_write_failed") from exc
    digest = _sha256_path(path)
    if not digest:
        raise AutosyncError("purge_state_write_failed")
    return digest


def _next_purge_state(
    *,
    config: dict[str, Any],
    account_id: int,
    repositories: list[dict[str, Any]],
    previous: dict[str, Any] | None,
    workflow_identity: dict[str, str],
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Advance absence counts only for a nonempty complete Actions snapshot."""
    try:
        managed_sources = managed_github_repo_sources(config)
    except ValueError as exc:
        raise AutosyncError(str(exc) or "invalid_github_managed_source_config") from exc
    account_identity = normalize_repo_identity(account_id)
    tracked_repo_ids: set[str] = set()
    for repo_id, source in managed_sources.items():
        if normalize_repo_identity(source.get("managed_account_id")) == account_identity:
            tracked_repo_ids.add(repo_id)

    starred_repo_ids: set[str] = set()
    for repository in repositories:
        try:
            repo_id = normalize_repo_identity(repository.get("id") if isinstance(repository, dict) else None)
        except ValueError as exc:
            raise AutosyncError("github_upstream_invalid_response") from exc
        if repo_id in starred_repo_ids:
            raise AutosyncError("duplicate_github_star_repo_id")
        starred_repo_ids.add(repo_id)

    previous_confirmations: dict[str, int] = {}
    same_run = False
    if previous is not None and normalize_repo_identity(previous.get("account_id")) == account_identity:
        previous_confirmations = dict(previous["absence_confirmations"])
        same_run = previous.get("last_snapshot_run_id") == workflow_identity["run_id"]

    confirmations: dict[str, int] = {}
    pending: list[str] = []
    confirmed: list[str] = []
    for repo_id in sorted(tracked_repo_ids):
        if repo_id in starred_repo_ids:
            continue
        previous_count = previous_confirmations.get(repo_id, 0)
        count = previous_count if same_run else min(previous_count + 1, 2)
        confirmations[repo_id] = count
        if count >= 2:
            confirmed.append(repo_id)
        else:
            pending.append(repo_id)

    completed_at = _online_sources.utc_timestamp()
    return (
        {
            "version": 1,
            "account_id": account_id,
            "last_complete_snapshot_at": completed_at,
            "last_snapshot_run_id": workflow_identity["run_id"],
            "last_snapshot_run_attempt": workflow_identity["run_attempt"],
            "last_snapshot_head_sha": workflow_identity["head_sha"],
            "absence_confirmations": confirmations,
        },
        pending,
        confirmed,
    )


def _active_managed_source_count(config: dict, account_id: int) -> int:
    return sum(
        1
        for source in config["sources"]
        if source.get("managed_by") == "github_stars"
        and source.get("managed_account_id") == account_id
        and source.get("managed_state") == "active"
    )


def _write_config_pair(
    root_dir: Path,
    *,
    config_path: Path,
    opml_path: Path,
    config_content: bytes,
    opml_content: bytes,
) -> None:
    # 两次 os.replace 只能分别保证单文件完整；这里额外负责成对回滚与写后校验。
    try:
        config_before = config_path.read_bytes()
        opml_before = opml_path.read_bytes()
    except OSError as exc:
        raise AutosyncError("config_pair_backup_failed") from exc

    try:
        _online_sources.atomic_replace_bytes(opml_path, opml_content)
        _online_sources.atomic_replace_bytes(config_path, config_content)
        try:
            written_config = _online_sources._read_online_json_config(root_dir)
            expected_opml, _ = _online_sources.render_online_opml_bytes(
                written_config["sources"]
            )
            if config_path.read_bytes() != config_content:
                raise AutosyncError("config_pair_postcheck_failed")
            if not _online_sources._online_file_matches(opml_path, opml_content):
                raise AutosyncError("config_pair_postcheck_failed")
            if not _online_sources._online_file_matches(opml_path, expected_opml):
                raise AutosyncError("config_pair_postcheck_failed")
        except AutosyncError:
            raise
        except Exception as exc:
            raise AutosyncError("config_pair_postcheck_failed") from exc
    except Exception as exc:
        rollback_failed = False
        # 两个文件都恢复，不根据“可能写过哪个”做猜测。
        for path, content in (
            (config_path, config_before),
            (opml_path, opml_before),
        ):
            try:
                _online_sources.atomic_replace_bytes(path, content)
            except Exception:
                rollback_failed = True
        if rollback_failed:
            raise AutosyncError("config_pair_rollback_failed") from exc
        code = exc.code if isinstance(exc, AutosyncError) else "config_pair_write_failed"
        raise AutosyncError(code) from exc


def run_autosync(
    root_dir: Path,
    *,
    dry_run: bool = False,
    session: requests.Session | None = None,
) -> dict:
    config = _online_sources._read_online_json_config(root_dir)
    binding = config.get("github_star_sync")
    state_path = root_dir / PURGE_STATE_FILENAME
    existing_state_sha256 = _sha256_path(state_path)
    if binding is None:
        return _status("skipped_not_bound", ok=True, purge_state_sha256=existing_state_sha256)

    # 与手动保存路径一样，先确认 JSON 与其派生 OPML 一致；不一致时不写任何配置。
    config_path, opml_path = _online_sources.ensure_public_online_paths(root_dir)
    expected_opml, _ = _online_sources.render_online_opml_bytes(config["sources"])
    if not _online_sources._online_file_matches(opml_path, expected_opml):
        return _status("aborted_opml_mismatch", ok=False, purge_state_sha256=existing_state_sha256)

    owned_session = session is None
    active_session = session or _github_stars.create_github_stars_session()
    token = str(os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        active_session.headers["Authorization"] = f"Bearer {token}"
    try:
        snapshot = _github_stars.fetch_github_star_snapshot(
            active_session,
            account_id=binding["account_id"],
        )
    finally:
        if owned_session:
            active_session.close()

    account = snapshot["account"]
    workflow_identity = workflow_identity_from_environment()
    if not snapshot.get("repositories"):
        # 第一批不把空公开星标列表当作可自动停用或清理的证据。
        return _status(
            "refused_empty_snapshot",
            ok=False,
            account=account,
            snapshot=snapshot,
            workflow_identity=workflow_identity,
            purge_state_sha256=existing_state_sha256,
        )

    snapshot_complete = workflow_identity is not None
    next_state: dict[str, Any] | None = None
    pending_absent_repo_ids: list[str] = []
    confirmed_absent_repo_ids: list[str] = []
    if snapshot_complete:
        previous_state = load_purge_state(state_path)
        next_state, pending_absent_repo_ids, confirmed_absent_repo_ids = _next_purge_state(
            config=config,
            account_id=account["id"],
            repositories=snapshot["repositories"],
            previous=previous_state,
            workflow_identity=workflow_identity,
        )

    merge = _github_stars.merge_github_star_sources(
        config,
        account=snapshot["account"],
        repositories=snapshot["repositories"],
        allow_auto_disable_repo_ids=set(confirmed_absent_repo_ids),
    )
    summary = merge["summary"]
    if summary["adopted"]:
        # 收编手动源必须人工确认（沿用 V3 规则），本轮整体不写。
        return _status(
            "manual_confirmation_required",
            ok=False,
            account=account,
            snapshot=snapshot,
            summary=summary,
            workflow_identity=workflow_identity,
            snapshot_complete=snapshot_complete,
            purge_state_sha256=existing_state_sha256,
        )
    active_managed_count = _active_managed_source_count(config, binding["account_id"])
    disabled_count = len(summary["disabled"])
    if disabled_count > MAX_AUTOMATIC_DISABLE_COUNT or (
        active_managed_count > 0 and disabled_count * 2 > active_managed_count
    ):
        # 非空但数量骤降同样可能是上游返回了不完整快照，转人工确认。
        return _status(
            "refused_mass_disable",
            ok=False,
            account=account,
            snapshot=snapshot,
            summary=summary,
            workflow_identity=workflow_identity,
            snapshot_complete=snapshot_complete,
            purge_state_sha256=existing_state_sha256,
        )
    if dry_run:
        return _status(
            "dry_run",
            ok=True,
            account=account,
            snapshot=snapshot,
            summary=summary,
            workflow_identity=workflow_identity,
            snapshot_complete=snapshot_complete,
            purge_state_sha256=existing_state_sha256,
            pending_absent_repo_ids=pending_absent_repo_ids,
            confirmed_absent_repo_ids=confirmed_absent_repo_ids,
        )

    if merge["config_changed"]:
        normalized_candidate = _online_sources.validate_online_config_schema(
            merge["config"], existing=True
        )
        user_sources = _online_sources.online_user_sources_from_config(normalized_candidate)
        candidate = _online_sources.build_online_config(
            user_sources,
            github_star_sync=normalized_candidate.get("github_star_sync"),
        )
        config_content = _online_sources.render_json_bytes(candidate)
        opml_content, _ = _online_sources.render_online_opml_bytes(user_sources)
        config_before = config_path.read_bytes()
        opml_before = opml_path.read_bytes()
        _write_config_pair(
            root_dir,
            config_path=config_path,
            opml_path=opml_path,
            config_content=config_content,
            opml_content=opml_content,
        )
        if next_state is not None:
            try:
                state_sha256 = _write_purge_state(state_path, next_state)
            except AutosyncError as exc:
                try:
                    _write_config_pair(
                        root_dir,
                        config_path=config_path,
                        opml_path=opml_path,
                        config_content=config_before,
                        opml_content=opml_before,
                    )
                except AutosyncError as rollback_error:
                    raise AutosyncError("purge_state_write_rollback_failed") from rollback_error
                raise exc
        else:
            state_sha256 = existing_state_sha256
        outcome = "synced"
    else:
        state_sha256 = _write_purge_state(state_path, next_state) if next_state is not None else existing_state_sha256
        outcome = "no_change"

    return _status(
        outcome,
        ok=True,
        account=account,
        snapshot=snapshot,
        summary=summary,
        workflow_identity=workflow_identity,
        snapshot_complete=snapshot_complete,
        purge_state_sha256=state_sha256,
        pending_absent_repo_ids=pending_absent_repo_ids,
        confirmed_absent_repo_ids=confirmed_absent_repo_ids,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GitHub 星标自动同步（Actions 用）")
    parser.add_argument("--root", default=".", help="仓库根目录")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将发生的变化，不写任何文件（含状态文件）",
    )
    args = parser.parse_args(argv)
    root_dir = Path(args.root).resolve()
    failure_context = {
        "workflow_identity": workflow_identity_from_environment(),
        "purge_state_sha256": _sha256_path(root_dir / PURGE_STATE_FILENAME),
    }
    try:
        status = run_autosync(root_dir, dry_run=args.dry_run)
    except (
        AutosyncError,
        _github_stars.GitHubStarsError,
        _online_sources.OnlineSourcesError,
    ) as exc:
        status = _status("failed", ok=False, error_code=exc.code, **failure_context)
    except Exception:
        # 不把上游响应、路径或其它内部细节写进公开状态文件。
        status = _status("failed", ok=False, error_code="autosync_internal_error", **failure_context)
    if not args.dry_run:
        _online_sources.write_json_atomic(root_dir / STATUS_FILENAME, status)
    print(json.dumps(status, ensure_ascii=False))
    return 0 if status.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
