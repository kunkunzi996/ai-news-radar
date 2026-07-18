#!/usr/bin/env python3
"""GitHub 星标自动同步：供 Actions 在每轮采集前调用。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from scripts.radar.server import github_stars as _github_stars  # noqa: E402
from scripts.radar.server import online_sources as _online_sources  # noqa: E402


STATUS_FILENAME = Path("data") / "github-star-autosync.json"
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
) -> dict:
    payload = {
        "version": 1,
        "ok": ok,
        "outcome": outcome,
        "finished_at": _online_sources.utc_timestamp(),
        "error_code": error_code,
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
    if binding is None:
        return _status("skipped_not_bound", ok=True)

    # 与手动保存路径一样，先确认 JSON 与其派生 OPML 一致；不一致时不写任何配置。
    config_path, opml_path = _online_sources.ensure_public_online_paths(root_dir)
    expected_opml, _ = _online_sources.render_online_opml_bytes(config["sources"])
    if not _online_sources._online_file_matches(opml_path, expected_opml):
        return _status("aborted_opml_mismatch", ok=False)

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

    merge = _github_stars.merge_github_star_sources(
        config,
        account=snapshot["account"],
        repositories=snapshot["repositories"],
    )
    summary = merge["summary"]
    account = snapshot["account"]
    if not merge["config_changed"]:
        return _status(
            "no_change", ok=True, account=account, snapshot=snapshot, summary=summary
        )
    if summary["adopted"]:
        # 收编手动源必须人工确认（沿用 V3 规则），本轮整体不写。
        return _status(
            "manual_confirmation_required",
            ok=False,
            account=account,
            snapshot=snapshot,
            summary=summary,
        )
    if snapshot["starred_count"] == 0 and summary["disabled"]:
        # 合法但全空的快照不能无人值守地停用所有受管源。
        return _status(
            "refused_empty_snapshot",
            ok=False,
            account=account,
            snapshot=snapshot,
            summary=summary,
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
        )
    if dry_run:
        return _status(
            "dry_run", ok=True, account=account, snapshot=snapshot, summary=summary
        )

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
    _write_config_pair(
        root_dir,
        config_path=config_path,
        opml_path=opml_path,
        config_content=config_content,
        opml_content=opml_content,
    )
    return _status("synced", ok=True, account=account, snapshot=snapshot, summary=summary)


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
    try:
        status = run_autosync(root_dir, dry_run=args.dry_run)
    except (
        AutosyncError,
        _github_stars.GitHubStarsError,
        _online_sources.OnlineSourcesError,
    ) as exc:
        status = _status("failed", ok=False, error_code=exc.code)
    except Exception:
        # 不把上游响应、路径或其它内部细节写进公开状态文件。
        status = _status("failed", ok=False, error_code="autosync_internal_error")
    if not args.dry_run:
        _online_sources.write_json_atomic(root_dir / STATUS_FILENAME, status)
    print(json.dumps(status, ensure_ascii=False))
    return 0 if status.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
