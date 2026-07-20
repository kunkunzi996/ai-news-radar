from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.radar.common import GITHUB_REPO_SUBSCRIPTION_SITE_ID
from scripts.radar.config_runtime import normalize_repo_identity
from scripts.radar.cli import apply_github_subscription_cleanup
from scripts.radar.pipeline import propose_github_star_subscription_cleanup
from scripts.restore_github_subscription_cleanup import restore_github_items_by_id


WORKFLOW = {
    "run_id": "1001",
    "run_attempt": "1",
    "head_sha": "a" * 40,
}
PURGE_SHA = "b" * 64


def managed_config(*, state: str = "auto_disabled", repo_id: int = 101) -> dict:
    return {
        "github_star_sync": {"account_id": 7},
        "sources": [
            {
                "id": "managed-repo",
                "managed_by": "github_stars",
                "managed_account_id": 7,
                "managed_repo_id": repo_id,
                "managed_state": state,
                "enabled": state == "active",
            }
        ],
    }


def matched_status(*, repo_id: str = "101") -> dict:
    return {
        "version": 2,
        "ok": True,
        "account_id": 7,
        "snapshot_complete": True,
        "workflow_run_id": WORKFLOW["run_id"],
        "workflow_run_attempt": WORKFLOW["run_attempt"],
        "workflow_head_sha": WORKFLOW["head_sha"],
        "purge_state_sha256": PURGE_SHA,
        "confirmed_absent_repo_ids": [repo_id],
    }


def matched_purge_state(*, repo_id: str = "101") -> dict:
    return {
        "version": 1,
        "account_id": 7,
        "last_complete_snapshot_at": "2026-07-20T00:00:00Z",
        "last_snapshot_run_id": "1000",
        "last_snapshot_run_attempt": "1",
        "last_snapshot_head_sha": "c" * 40,
        "absence_confirmations": {repo_id: 2},
    }


def github_record(item_id: str, *, repo_id: str = "101", source: str = "old-owner/old-name") -> dict:
    return {
        "id": item_id,
        "site_id": GITHUB_REPO_SUBSCRIPTION_SITE_ID,
        "source": source,
        "title": f"Release {item_id}",
        "url": f"https://example.test/{item_id}",
        "published_at": "2026-07-20T00:00:00Z",
        "github_repo_identity": repo_id,
        "github_entry_identity": f"release:{item_id}",
    }


def archive_digest(archive: dict) -> str:
    return hashlib.sha256(
        json.dumps(archive, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class GitHubSubscriptionCleanupContractTests(unittest.TestCase):
    def test_normalize_repo_identity_rejects_noncanonical_values(self):
        self.assertEqual(normalize_repo_identity(101), "101")
        self.assertEqual(normalize_repo_identity("101"), "101")
        with self.assertRaises(ValueError):
            normalize_repo_identity(101, allow_integer=False)
        for value in (True, False, 0, -1, 1.0, "", " 101", "+101", "001", "0", "-1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_repo_identity(value)

    def test_proposal_uses_stable_repo_id_not_renameable_source_text(self):
        archive = {
            "remove": github_record("remove", source="old-owner/old-name"),
            "keep": {
                "id": "keep",
                "site_id": "bilibili_dynamic",
                "source": "Keep",
            },
        }

        proposed, report = propose_github_star_subscription_cleanup(
            archive,
            managed_config(),
            autosync_status=matched_status(),
            purge_state=matched_purge_state(),
            purge_state_sha256=PURGE_SHA,
            workflow_identity=WORKFLOW,
            archive_sha256_before="d" * 64,
        )

        self.assertEqual(set(proposed), {"keep"})
        self.assertEqual(report["candidate_repo_ids"], ["101"])
        self.assertEqual(report["candidate_item_ids"], ["remove"])
        self.assertEqual(report["skip_reasons"], [])

    def test_missing_github_identity_fuses_the_entire_channel(self):
        archive = {
            "remove": github_record("remove"),
            "legacy": {
                "id": "legacy",
                "site_id": GITHUB_REPO_SUBSCRIPTION_SITE_ID,
                "source": "unknown",
            },
        }

        proposed, report = propose_github_star_subscription_cleanup(
            archive,
            managed_config(),
            autosync_status=matched_status(),
            purge_state=matched_purge_state(),
            purge_state_sha256=PURGE_SHA,
            workflow_identity=WORKFLOW,
            archive_sha256_before="d" * 64,
        )

        self.assertEqual(proposed, archive)
        self.assertEqual(report["candidate_item_ids"], [])
        self.assertIn("archive_missing_github_repo_identity", report["skip_reasons"])

    def test_status_run_mismatch_fuses_the_entire_channel(self):
        status = matched_status()
        status["workflow_run_id"] = "stale-run"
        archive = {"remove": github_record("remove")}

        proposed, report = propose_github_star_subscription_cleanup(
            archive,
            managed_config(),
            autosync_status=status,
            purge_state=matched_purge_state(),
            purge_state_sha256=PURGE_SHA,
            workflow_identity=WORKFLOW,
            archive_sha256_before="d" * 64,
        )

        self.assertEqual(proposed, archive)
        self.assertIn("stale_autosync_status", report["skip_reasons"])

    def test_manual_disabled_github_source_never_becomes_a_candidate(self):
        archive = {"remove": github_record("remove")}
        proposed, report = propose_github_star_subscription_cleanup(
            archive,
            managed_config(state="active"),
            autosync_status=matched_status(),
            purge_state=matched_purge_state(),
            purge_state_sha256=PURGE_SHA,
            workflow_identity=WORKFLOW,
            archive_sha256_before="d" * 64,
        )

        self.assertEqual(proposed, archive)
        self.assertEqual(report["candidate_item_ids"], [])

    def test_audit_keeps_archive_unchanged_and_on_requires_exact_digest(self):
        archive = {"remove": github_record("remove")}
        archive_sha = archive_digest(archive)
        with tempfile.TemporaryDirectory(prefix="github-cleanup-audit-") as temp_dir:
            audit_path = Path(temp_dir) / "github-star-subscription-cleanup.json"
            audited, audit = apply_github_subscription_cleanup(
                archive,
                managed_config(),
                mode="audit",
                autosync_status=matched_status(),
                purge_state=matched_purge_state(),
                purge_state_sha256=PURGE_SHA,
                workflow_identity=WORKFLOW,
                archive_sha256_before=archive_sha,
                approval_digest="",
                audit_path=audit_path,
            )
            mismatched, mismatch = apply_github_subscription_cleanup(
                archive,
                managed_config(),
                mode="on",
                autosync_status=matched_status(),
                purge_state=matched_purge_state(),
                purge_state_sha256=PURGE_SHA,
                workflow_identity=WORKFLOW,
                archive_sha256_before=archive_sha,
                approval_digest="wrong",
                audit_path=audit_path,
            )
            applied, on = apply_github_subscription_cleanup(
                archive,
                managed_config(),
                mode="on",
                autosync_status=matched_status(),
                purge_state=matched_purge_state(),
                purge_state_sha256=PURGE_SHA,
                workflow_identity=WORKFLOW,
                archive_sha256_before=archive_sha,
                approval_digest=audit["approval_digest"],
                audit_path=audit_path,
            )

            written = json.loads(audit_path.read_text(encoding="utf-8"))
        self.assertEqual(audited, archive)
        self.assertFalse(audit["applied"])
        self.assertEqual(mismatched, archive)
        self.assertIn("approval_digest_mismatch", mismatch["skip_reasons"])
        self.assertEqual(applied, {})
        self.assertTrue(on["applied"])
        self.assertTrue(written["applied"])

    def test_audit_write_failure_keeps_archive_unchanged(self):
        archive = {"remove": github_record("remove")}
        with tempfile.TemporaryDirectory(prefix="github-cleanup-audit-") as temp_dir:
            audit_path = Path(temp_dir) / "github-star-subscription-cleanup.json"
            audit_path.write_text('{"previous":true}', encoding="utf-8")
            with patch("scripts.radar.cli._online_sources.write_json_atomic", side_effect=OSError("disk full")):
                result, report = apply_github_subscription_cleanup(
                    archive,
                    managed_config(),
                    mode="on",
                    autosync_status=matched_status(),
                    purge_state=matched_purge_state(),
                    purge_state_sha256=PURGE_SHA,
                    workflow_identity=WORKFLOW,
                    archive_sha256_before=archive_digest(archive),
                    approval_digest="irrelevant",
                    audit_path=audit_path,
                )
            self.assertEqual(audit_path.read_text(encoding="utf-8"), '{"previous":true}')
        self.assertEqual(result, archive)
        self.assertIn("audit_write_failed", report["skip_reasons"])

    def test_precise_restore_uses_record_id_and_keeps_newer_items(self):
        current = {
            "total_items": 1,
            "items": [
                {"id": "newer", "site_id": "bilibili_dynamic", "source": "New"},
            ],
        }
        before = {
            "total_items": 2,
            "items": [
                github_record("github-removed"),
                {"id": "wechat", "site_id": "we_mp_rss_jsonl", "source": "Nope"},
            ],
        }

        restored, report = restore_github_items_by_id(current, before, ["github-removed"])

        self.assertFalse(report["fail_safe"])
        self.assertEqual(report["restored_item_ids"], ["github-removed"])
        self.assertEqual({item["id"] for item in restored["items"]}, {"newer", "github-removed"})
        self.assertEqual(restored["total_items"], 2)

    def test_precise_restore_rejects_a_mixed_conflict_batch(self):
        current = {"items": [github_record("already")]}
        before = {"items": [github_record("already"), github_record("target")]}

        restored, report = restore_github_items_by_id(current, before, ["target", "already"])

        self.assertEqual(restored, current)
        self.assertTrue(report["fail_safe"])
        self.assertEqual(report["conflict_item_ids"], ["already"])
        self.assertEqual(report["restored_item_ids"], [])


if __name__ == "__main__":
    unittest.main()
