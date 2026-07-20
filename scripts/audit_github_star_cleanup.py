#!/usr/bin/env python3
"""Read-only preview for the GitHub star subscription cleanup contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import github_star_autosync
from scripts.radar.config_runtime import load_source_config
from scripts.radar.pipeline import load_archive, propose_github_star_subscription_cleanup


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _sha256_path(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only GitHub star history cleanup audit")
    parser.add_argument("--source-config", default="config/online-sources.json")
    parser.add_argument("--archive", default="data/archive.json")
    parser.add_argument("--state", default="data/github-star-purge-state.json")
    parser.add_argument("--status", default="data/github-star-autosync.json")
    args = parser.parse_args()

    source_config_path = Path(args.source_config)
    archive_path = Path(args.archive)
    state_path = Path(args.state)
    status_path = Path(args.status)
    source_config, source_status = load_source_config(str(source_config_path))
    archive = load_archive(archive_path)
    autosync_status = _read_object(status_path)
    purge_state = github_star_autosync.load_purge_state(state_path)
    workflow = github_star_autosync.workflow_identity_from_environment()
    _proposed, proposal = propose_github_star_subscription_cleanup(
        archive,
        source_config,
        autosync_status=autosync_status,
        purge_state=purge_state,
        purge_state_sha256=_sha256_path(state_path),
        workflow_identity=workflow,
        archive_sha256_before=_sha256_path(archive_path),
    )
    recorded = autosync_status or {}
    output = {
        "mode": "audit",
        "source_config": source_status,
        "archive_github_item_count": sum(
            1 for record in archive.values() if str(record.get("site_id") or "") == "github_foundation_sunshine_releases"
        ),
        "recorded_workflow_run_id": recorded.get("workflow_run_id", ""),
        "recorded_workflow_run_attempt": recorded.get("workflow_run_attempt", ""),
        "recorded_workflow_head_sha": recorded.get("workflow_head_sha", ""),
        "current_workflow_identity": workflow or {},
        "snapshot_complete": recorded.get("snapshot_complete") is True,
        "purge_state_sha256_matches": bool(
            recorded.get("purge_state_sha256")
            and recorded.get("purge_state_sha256") == _sha256_path(state_path)
        ),
        **proposal,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
