from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import github_star_autosync
from scripts.radar.server import github_stars, online_sources
from test_github_stars import (
    ACCOUNT,
    FakeResponse,
    FakeSession,
    config_with,
    managed_source,
    manual_source,
    public_repo,
    rss_source,
)


class AutosyncFakeSession(FakeSession):
    def __init__(self, responses):
        super().__init__(responses)
        self.headers: dict[str, str] = {}


def write_repo_fixture(root: Path, config: dict) -> dict:
    normalized = online_sources.validate_online_config_schema(copy.deepcopy(config), existing=True)
    user_sources = online_sources.online_user_sources_from_config(normalized)
    candidate = online_sources.build_online_config(
        user_sources,
        updated_at=normalized.get("updated_at"),
        github_star_sync=normalized.get("github_star_sync"),
    )
    (root / "data").mkdir(parents=True, exist_ok=True)
    online_sources.write_json_atomic(root / "config" / "online-sources.json", candidate)
    opml, _ = online_sources.render_online_opml_bytes(candidate["sources"])
    online_sources.atomic_replace_bytes(root / "feeds" / "online-sources.opml", opml)
    return candidate


class GitHubStarAutosyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="github-star-autosync-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def write_config(self, config: dict) -> dict:
        return write_repo_fixture(self.root, config)

    def session_for(self, repositories: list[dict]) -> AutosyncFakeSession:
        return AutosyncFakeSession(
            [FakeResponse(200, ACCOUNT), FakeResponse(200, repositories)]
        )

    def config_path(self) -> Path:
        return self.root / "config" / "online-sources.json"

    def opml_path(self) -> Path:
        return self.root / "feeds" / "online-sources.opml"

    def config_bytes(self) -> tuple[bytes, bytes]:
        return self.config_path().read_bytes(), self.opml_path().read_bytes()

    def run_with_workflow(
        self,
        repositories: list[dict],
        *,
        run_id: str,
        attempt: str = "1",
        sha: str = "a" * 40,
    ) -> dict:
        with patch.dict(
            os.environ,
            {
                "GITHUB_RUN_ID": run_id,
                "GITHUB_RUN_ATTEMPT": attempt,
                "GITHUB_SHA": sha,
            },
            clear=False,
        ):
            return github_star_autosync.run_autosync(
                self.root, session=self.session_for(repositories)
            )

    def changed_pair_contents(self) -> tuple[bytes, bytes]:
        config = online_sources._read_online_json_config(self.root)
        sources = online_sources.online_user_sources_from_config(config)
        sources[0]["name"] = "Changed source"
        candidate = online_sources.build_online_config(
            sources,
            updated_at="2026-07-18T01:00:00Z",
            github_star_sync=config.get("github_star_sync"),
        )
        config_content = online_sources.render_json_bytes(candidate)
        opml_content, _ = online_sources.render_online_opml_bytes(sources)
        return config_content, opml_content

    def call_main(self, argv: list[str]) -> tuple[int, dict]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = github_star_autosync.main(argv)
        return result, json.loads(stdout.getvalue())

    def test_not_bound_skips_without_changing_config_pair(self):
        self.write_config(config_with([], bound=False))
        before = self.config_bytes()

        result = github_star_autosync.run_autosync(self.root)

        self.assertEqual(result["outcome"], "skipped_not_bound")
        self.assertTrue(result["ok"])
        self.assertEqual(self.config_bytes(), before)

    def test_no_change_preserves_config_bytes_timestamp_and_opml(self):
        config = self.write_config(config_with([managed_source(1, "owner/one")]))
        before = self.config_bytes()

        result = github_star_autosync.run_autosync(
            self.root, session=self.session_for([public_repo(1, "owner/one")])
        )

        after = online_sources._read_online_json_config(self.root)
        self.assertEqual(result["outcome"], "no_change")
        self.assertEqual(self.config_bytes(), before)
        self.assertEqual(after["updated_at"], config["updated_at"])

    def test_new_star_writes_config_and_regenerates_opml(self):
        self.write_config(config_with([]))
        before = self.config_bytes()
        writes: list[str] = []
        original_replace = online_sources.atomic_replace_bytes

        def recording_replace(path: Path, content: bytes) -> None:
            if path in {self.config_path(), self.opml_path()}:
                writes.append(path.name)
            original_replace(path, content)

        with patch.object(online_sources, "atomic_replace_bytes", side_effect=recording_replace):
            result = github_star_autosync.run_autosync(
                self.root, session=self.session_for([public_repo(1, "owner/one")])
            )

        after = online_sources._read_online_json_config(self.root)
        source = next(item for item in after["sources"] if item["id"] == "online_github_repo_1")
        expected_opml, _ = online_sources.render_online_opml_bytes(after["sources"])
        self.assertEqual(result["outcome"], "synced")
        self.assertNotEqual(self.config_path().read_bytes(), before[0])
        self.assertEqual(self.opml_path().read_bytes(), expected_opml)
        self.assertEqual(writes, ["online-sources.opml", "online-sources.json"])
        self.assertEqual(source["managed_state"], "active")
        self.assertNotEqual(after["updated_at"], "2026-07-15T00:00:00Z")

    def test_unstar_disables_without_deleting_or_changing_other_sources(self):
        unchanged = manual_source("manual_keep", "owner/manual", name="Keep manual")
        self.write_config(
            config_with(
                [managed_source(1, "owner/one"), managed_source(2, "owner/two"), unchanged]
            )
        )

        self.run_with_workflow([public_repo(2, "owner/two")], run_id="101")
        result = self.run_with_workflow([public_repo(2, "owner/two")], run_id="102")

        after = online_sources._read_online_json_config(self.root)
        disabled = next(item for item in after["sources"] if item["id"] == "online_github_repo_1")
        kept = next(item for item in after["sources"] if item["id"] == "manual_keep")
        self.assertEqual(result["outcome"], "synced")
        self.assertFalse(disabled["enabled"])
        self.assertEqual(disabled["managed_state"], "auto_disabled")
        self.assertEqual(kept, unchanged)

    def test_empty_snapshot_refuses_to_disable_managed_sources(self):
        self.write_config(config_with([managed_source(1, "owner/one")]))
        before = self.config_bytes()

        result = github_star_autosync.run_autosync(self.root, session=self.session_for([]))

        self.assertEqual(result["outcome"], "refused_empty_snapshot")
        self.assertFalse(result["ok"])
        self.assertEqual(self.config_bytes(), before)

    def test_more_than_three_disables_refuses_to_write(self):
        sources = [managed_source(index, f"owner/repo-{index}") for index in range(1, 16)]
        self.write_config(config_with(sources))
        before = self.config_bytes()

        repositories = [public_repo(index, f"owner/repo-{index}") for index in range(5, 16)]
        self.run_with_workflow(repositories, run_id="101")
        result = self.run_with_workflow(repositories, run_id="102")

        self.assertEqual(result["outcome"], "refused_mass_disable")
        self.assertEqual(len(result["summary"]["disabled"]), 4)
        self.assertEqual(self.config_bytes(), before)

    def test_disable_threshold_allows_three_of_fifteen(self):
        sources = [managed_source(index, f"owner/repo-{index}") for index in range(1, 16)]
        self.write_config(config_with(sources))

        repositories = [public_repo(index, f"owner/repo-{index}") for index in range(4, 16)]
        self.run_with_workflow(repositories, run_id="101")
        result = self.run_with_workflow(repositories, run_id="102")

        after = online_sources._read_online_json_config(self.root)
        disabled = [item for item in after["sources"] if item.get("managed_state") == "auto_disabled"]
        self.assertEqual(result["outcome"], "synced")
        self.assertEqual([item["managed_repo_id"] for item in disabled], [1, 2, 3])

    def test_large_proportional_drop_refuses_even_at_three_disables(self):
        sources = [managed_source(index, f"owner/repo-{index}") for index in range(1, 6)]
        self.write_config(config_with(sources))
        before = self.config_bytes()

        repositories = [public_repo(index, f"owner/repo-{index}") for index in (4, 5)]
        self.run_with_workflow(repositories, run_id="101")
        result = self.run_with_workflow(repositories, run_id="102")

        self.assertEqual(result["outcome"], "refused_mass_disable")
        self.assertEqual(len(result["summary"]["disabled"]), 3)
        self.assertEqual(self.config_bytes(), before)

    def test_adopting_an_enabled_manual_source_requires_confirmation(self):
        self.write_config(config_with([manual_source("manual_one", "owner/one")]))
        before = self.config_bytes()

        result = github_star_autosync.run_autosync(
            self.root, session=self.session_for([public_repo(1, "owner/one")])
        )

        self.assertEqual(result["outcome"], "manual_confirmation_required")
        self.assertTrue(result["summary"]["adopted"])
        self.assertEqual(self.config_bytes(), before)

    def test_mismatched_opml_aborts_before_network_or_write(self):
        self.write_config(config_with([rss_source(1)]))
        self.opml_path().write_bytes(b"not the derived OPML")
        before = self.config_bytes()
        session = AutosyncFakeSession([])

        result = github_star_autosync.run_autosync(self.root, session=session)

        self.assertEqual(result["outcome"], "aborted_opml_mismatch")
        self.assertEqual(session.calls, [])
        self.assertEqual(self.config_bytes(), before)

    def test_github_token_is_forwarded_only_when_present(self):
        self.write_config(config_with([managed_source(1, "owner/one")]))
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=True):
            with_token = self.session_for([public_repo(1, "owner/one")])
            github_star_autosync.run_autosync(self.root, session=with_token)

        with patch.dict(os.environ, {}, clear=True):
            without_token = self.session_for([public_repo(1, "owner/one")])
            github_star_autosync.run_autosync(self.root, session=without_token)

        self.assertEqual(with_token.headers, {"Authorization": "Bearer test-token"})
        self.assertEqual(without_token.headers, {})

    def test_dry_run_does_not_write_config_or_status_files(self):
        self.write_config(config_with([]))
        before = self.config_bytes()

        result = github_star_autosync.run_autosync(
            self.root,
            dry_run=True,
            session=self.session_for([public_repo(1, "owner/one")]),
        )

        self.assertEqual(result["outcome"], "dry_run")
        self.assertEqual(self.config_bytes(), before)
        self.assertFalse((self.root / github_star_autosync.STATUS_FILENAME).exists())

        with patch.object(github_star_autosync, "run_autosync", return_value=result):
            code, stdout = self.call_main(["--root", str(self.root), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout["outcome"], "dry_run")
        self.assertFalse((self.root / github_star_autosync.STATUS_FILENAME).exists())

    def test_main_writes_a_public_status_heartbeat(self):
        self.write_config(config_with([], bound=False))
        status = {
            "version": 1,
            "ok": True,
            "outcome": "no_change",
            "finished_at": "2026-07-18T01:00:00Z",
            "error_code": "",
        }

        with patch.object(github_star_autosync, "run_autosync", return_value=status):
            code, stdout = self.call_main(["--root", str(self.root)])

        written = json.loads((self.root / github_star_autosync.STATUS_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, status)
        self.assertEqual(written, status)
        self.assertEqual(written["version"], 1)

    def test_main_records_upstream_error_without_writing_config(self):
        self.write_config(config_with([managed_source(1, "owner/one")]))
        before = self.config_bytes()
        upstream_error = github_stars.GitHubStarsError(
            "github_upstream_rate_limited", status_code=429
        )

        with patch.object(github_star_autosync, "run_autosync", side_effect=upstream_error):
            code, stdout = self.call_main(["--root", str(self.root)])

        self.assertEqual(code, 1)
        self.assertEqual(stdout["error_code"], "github_upstream_rate_limited")
        self.assertEqual(self.config_bytes(), before)
        self.assertEqual(
            json.loads((self.root / github_star_autosync.STATUS_FILENAME).read_text(encoding="utf-8")),
            stdout,
        )

    def test_main_hides_unexpected_error_details(self):
        self.write_config(config_with([], bound=False))

        with patch.object(
            github_star_autosync,
            "run_autosync",
            side_effect=ValueError("private path and upstream response must not leak"),
        ):
            code, stdout = self.call_main(["--root", str(self.root)])

        serialized = json.dumps(stdout, ensure_ascii=False)
        self.assertEqual(code, 1)
        self.assertEqual(stdout["error_code"], "autosync_internal_error")
        self.assertNotIn("private path", serialized)
        self.assertNotIn("upstream response", serialized)

    def test_no_change_heartbeats_refresh_status_without_changing_config(self):
        config = self.write_config(config_with([managed_source(1, "owner/one")]))
        before = self.config_bytes()
        statuses = [
            {
                "version": 1,
                "ok": True,
                "outcome": "no_change",
                "finished_at": "2026-07-18T01:00:00Z",
                "error_code": "",
            },
            {
                "version": 1,
                "ok": True,
                "outcome": "no_change",
                "finished_at": "2026-07-18T01:30:00Z",
                "error_code": "",
            },
        ]

        with patch.object(github_star_autosync, "run_autosync", side_effect=statuses):
            self.call_main(["--root", str(self.root)])
            self.call_main(["--root", str(self.root)])

        written = json.loads((self.root / github_star_autosync.STATUS_FILENAME).read_text(encoding="utf-8"))
        after = online_sources._read_online_json_config(self.root)
        self.assertEqual(self.config_bytes(), before)
        self.assertEqual(after["updated_at"], config["updated_at"])
        self.assertEqual(written["finished_at"], "2026-07-18T01:30:00Z")

    def test_config_write_failure_rolls_back_both_files_byte_for_byte(self):
        self.write_config(config_with([managed_source(1, "owner/one")]))
        before = self.config_bytes()
        config_content, opml_content = self.changed_pair_contents()
        original_replace = online_sources.atomic_replace_bytes
        failed = False

        def fail_config_once(path: Path, content: bytes) -> None:
            nonlocal failed
            if path == self.config_path() and not failed:
                failed = True
                raise OSError("injected config write failure")
            original_replace(path, content)

        with patch.object(online_sources, "atomic_replace_bytes", side_effect=fail_config_once):
            with self.assertRaises(github_star_autosync.AutosyncError) as raised:
                github_star_autosync._write_config_pair(
                    self.root,
                    config_path=self.config_path(),
                    opml_path=self.opml_path(),
                    config_content=config_content,
                    opml_content=opml_content,
                )

        self.assertEqual(raised.exception.code, "config_pair_write_failed")
        self.assertEqual(self.config_bytes(), before)

    def test_postcheck_failure_rolls_back_both_files_byte_for_byte(self):
        self.write_config(config_with([managed_source(1, "owner/one")]))
        before = self.config_bytes()
        config_content, opml_content = self.changed_pair_contents()

        with patch.object(online_sources, "_online_file_matches", return_value=False):
            with self.assertRaises(github_star_autosync.AutosyncError) as raised:
                github_star_autosync._write_config_pair(
                    self.root,
                    config_path=self.config_path(),
                    opml_path=self.opml_path(),
                    config_content=config_content,
                    opml_content=opml_content,
                )

        self.assertEqual(raised.exception.code, "config_pair_postcheck_failed")
        self.assertEqual(self.config_bytes(), before)

    def test_rollback_failure_is_reported_as_dangerous_error(self):
        self.write_config(config_with([managed_source(1, "owner/one")]))
        config_before, opml_before = self.config_bytes()
        config_content, opml_content = self.changed_pair_contents()
        original_replace = online_sources.atomic_replace_bytes
        config_write_failed = False

        def fail_write_and_opml_rollback(path: Path, content: bytes) -> None:
            nonlocal config_write_failed
            if path == self.config_path() and not config_write_failed:
                config_write_failed = True
                raise OSError("injected config write failure")
            if path == self.opml_path() and content == opml_before:
                raise OSError("injected rollback failure")
            original_replace(path, content)

        with patch.object(
            online_sources,
            "atomic_replace_bytes",
            side_effect=fail_write_and_opml_rollback,
        ):
            with self.assertRaises(github_star_autosync.AutosyncError) as raised:
                github_star_autosync._write_config_pair(
                    self.root,
                    config_path=self.config_path(),
                    opml_path=self.opml_path(),
                    config_content=config_content,
                    opml_content=opml_content,
                )

        self.assertEqual(raised.exception.code, "config_pair_rollback_failed")
        self.assertEqual(self.config_path().read_bytes(), config_before)

    def test_first_absence_only_records_pending_and_second_run_disables(self):
        self.write_config(config_with([managed_source(1, "owner/one"), managed_source(2, "owner/two")]))

        first = self.run_with_workflow([public_repo(2, "owner/two")], run_id="101")
        after_first = online_sources._read_online_json_config(self.root)
        first_state_path = self.root / github_star_autosync.PURGE_STATE_FILENAME
        first_state_bytes = first_state_path.read_bytes()
        first_state = json.loads(first_state_bytes.decode("utf-8"))

        second = self.run_with_workflow([public_repo(2, "owner/two")], run_id="102")
        after_second = online_sources._read_online_json_config(self.root)

        self.assertEqual(first["pending_absent_repo_ids"], ["1"])
        self.assertEqual(first["confirmed_absent_repo_ids"], [])
        self.assertEqual(first["version"], 2)
        self.assertTrue(first["snapshot_complete"])
        self.assertEqual(first["workflow_run_id"], "101")
        self.assertEqual(
            first["purge_state_sha256"],
            hashlib.sha256(first_state_bytes).hexdigest(),
        )
        self.assertTrue(next(item for item in after_first["sources"] if item["managed_repo_id"] == 1)["enabled"])
        self.assertEqual(first_state["absence_confirmations"], {"1": 1})
        self.assertEqual(second["confirmed_absent_repo_ids"], ["1"])
        self.assertFalse(next(item for item in after_second["sources"] if item["managed_repo_id"] == 1)["enabled"])

    def test_same_run_cannot_count_as_the_second_absence_confirmation(self):
        self.write_config(config_with([managed_source(1, "owner/one"), managed_source(2, "owner/two")]))

        self.run_with_workflow([public_repo(2, "owner/two")], run_id="101")
        repeated = self.run_with_workflow([public_repo(2, "owner/two")], run_id="101", attempt="2")

        config = online_sources._read_online_json_config(self.root)
        state = json.loads((self.root / github_star_autosync.PURGE_STATE_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(repeated["pending_absent_repo_ids"], ["1"])
        self.assertEqual(repeated["confirmed_absent_repo_ids"], [])
        self.assertEqual(state["absence_confirmations"], {"1": 1})
        self.assertTrue(next(item for item in config["sources"] if item["managed_repo_id"] == 1)["enabled"])

    def test_reappearing_repo_clears_pending_absence_state(self):
        self.write_config(config_with([managed_source(1, "owner/one"), managed_source(2, "owner/two")]))
        self.run_with_workflow([public_repo(2, "owner/two")], run_id="101")
        self.run_with_workflow([public_repo(2, "owner/two")], run_id="102")

        result = self.run_with_workflow(
            [public_repo(1, "owner/one"), public_repo(2, "owner/two")], run_id="103"
        )

        config = online_sources._read_online_json_config(self.root)
        state = json.loads((self.root / github_star_autosync.PURGE_STATE_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(result["pending_absent_repo_ids"], [])
        self.assertEqual(state["absence_confirmations"], {})
        self.assertTrue(next(item for item in config["sources"] if item["managed_repo_id"] == 1)["enabled"])

    def test_failed_snapshot_does_not_advance_existing_confirmation_state(self):
        self.write_config(config_with([managed_source(1, "owner/one"), managed_source(2, "owner/two")]))
        self.run_with_workflow([public_repo(2, "owner/two")], run_id="101")
        state_path = self.root / github_star_autosync.PURGE_STATE_FILENAME
        before = state_path.read_bytes()
        failed_session = AutosyncFakeSession(
            [FakeResponse(200, ACCOUNT), FakeResponse(500, {"message": "internal"})]
        )

        with patch.dict(
            os.environ,
            {"GITHUB_RUN_ID": "102", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40},
            clear=False,
        ):
            with self.assertRaises(github_stars.GitHubStarsError):
                github_star_autosync.run_autosync(self.root, session=failed_session)

        self.assertEqual(state_path.read_bytes(), before)

    def test_empty_snapshot_preserves_prior_absence_confirmation_state(self):
        self.write_config(config_with([managed_source(1, "owner/one"), managed_source(2, "owner/two")]))
        self.run_with_workflow([public_repo(2, "owner/two")], run_id="101")
        before = (self.root / github_star_autosync.PURGE_STATE_FILENAME).read_bytes()

        result = self.run_with_workflow([], run_id="102")

        self.assertEqual(result["outcome"], "refused_empty_snapshot")
        self.assertEqual((self.root / github_star_autosync.PURGE_STATE_FILENAME).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
