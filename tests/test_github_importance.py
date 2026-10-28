import json
from datetime import datetime

import pytest

from scripts.radar.common import apply_public_raw_meta
from scripts.radar.fetchers.subscriptions import fetch_github_repo_subscription
from scripts.radar.github_importance import (
    github_archive_record_is_reader_visible,
    score_github_commit,
    score_github_release,
)


def release(tag: str, *, name: str = "", body: str = "", prerelease: bool = False) -> dict:
    return {
        "tag_name": tag,
        "name": name or tag,
        "body": body,
        "draft": False,
        "prerelease": prerelease,
    }


def commit(message: str, files: list[dict]) -> dict:
    return {
        "commit": {"message": message},
        "files": files,
    }


def source_file(name: str, *, status: str = "modified", changes: int = 20) -> dict:
    return {
        "filename": name,
        "status": status,
        "changes": changes,
        "additions": changes,
        "deletions": 0,
    }


def test_semver_major_and_minor_releases_are_visible() -> None:
    major = score_github_release(release("v2.0.0"))
    minor = score_github_release(release("v6.2.0"))

    assert major.visible is True
    assert major.score == 100
    assert minor.visible is True
    assert minor.score == 80


def test_zero_major_placeholder_release_is_not_treated_as_major() -> None:
    placeholder = score_github_release(release("v0.0.0"))
    pre_one_minor = score_github_release(release("v0.1.0"))

    assert placeholder.visible is False
    assert placeholder.score == 25
    assert placeholder.reasons == ("stable_release",)
    assert pre_one_minor.visible is True
    assert pre_one_minor.score == 80


def test_patch_and_calendar_releases_need_strong_release_notes() -> None:
    patch = score_github_release(release("v1.4.164"))
    calendar = score_github_release(release("v2026.08.02", body="修正文档链接和 CI gate"))
    strong_patch = score_github_release(
        release("v1.4.165", body="Launch a new provider integration and command workflow.")
    )

    assert patch.visible is False
    assert patch.score == 25
    assert calendar.visible is False
    assert calendar.score == 25
    assert strong_patch.visible is True
    assert strong_patch.score == 70


def test_prerelease_is_rejected_before_scoring() -> None:
    flagged = score_github_release(release("v2.0.0", prerelease=True))
    suffixed = score_github_release(release("v2.0.0-rc.1"))

    assert flagged.visible is False
    assert flagged.rejected_reason == "prerelease"
    assert suffixed.visible is False
    assert suffixed.rejected_reason == "prerelease"


def test_prerelease_marker_does_not_match_arbitrary_substrings() -> None:
    decision = score_github_release(release("v2.0.0", name="Source control release"))

    assert decision.visible is True
    assert decision.rejected_reason == ""


def test_strong_commit_requires_product_code_evidence() -> None:
    decision = score_github_commit(
        commit("feat!: launch provider tool filtering", [source_file("src/provider_filter.py")])
    )

    assert decision.visible is True
    assert decision.score == 70


def test_plain_feat_is_hidden_when_scope_is_small() -> None:
    decision = score_github_commit(
        commit("feat: streamline terminology lookup", [source_file("src/terms.py", changes=30)])
    )

    assert decision.visible is False
    assert decision.score == 50


def test_plain_feat_passes_with_substantial_product_scope() -> None:
    decision = score_github_commit(
        commit(
            "feat: add workspace automation",
            [
                source_file("src/workspace.py", changes=40),
                source_file("src/runner.py", changes=35),
                source_file("src/commands.py", changes=30),
            ],
        )
    )

    assert decision.visible is True
    assert decision.score == 70


def test_docs_only_change_is_rejected_even_with_strong_title() -> None:
    decision = score_github_commit(
        commit(
            "feat!: launch a new platform",
            [source_file("README.md", status="modified", changes=500)],
        )
    )

    assert decision.visible is False
    assert decision.rejected_reason == "noise_only_files"


@pytest.mark.parametrize(
    "message",
    [
        "Add /animation-performance skill",
        "Add break ui skill",
        "new skill",
        "Update skill",
        "Update SKILL.md",
        "新增 skill",
        "更新技能",
        "新技能",
        "feat(skills): add animation-performance",
        "feat: update animation skill",
        "feat(skill): 调整说明",
    ],
)
def test_skill_update_with_skill_md_is_visible(message: str) -> None:
    decision = score_github_commit(
        commit(message, [source_file("skills/animation-performance/SKILL.md")])
    )

    assert decision.visible is True
    assert decision.score >= 70
    assert decision.rejected_reason == ""
    assert "strong_feature_intent" in decision.reasons
    assert "product_code" in decision.reasons


def test_add_skill_commit_counts_skill_md_not_readme() -> None:
    decision = score_github_commit(
        commit(
            "Add /animation-performance skill",
            [
                source_file("README.md", status="modified", changes=1),
                source_file(
                    "skills/animation-performance/SKILL.md",
                    status="added",
                    changes=223,
                ),
            ],
        )
    )

    assert decision.visible is True
    assert decision.score >= 70
    assert decision.reasons == (
        "strong_feature_intent",
        "product_code",
        "new_product_module",
        "substantial_product_scope",
    )


def test_skill_noise_messages_and_non_product_files_stay_hidden() -> None:
    readme = score_github_commit(
        commit("update readme", [source_file("README.md"), source_file("skills/foo/SKILL.md")])
    )
    sync_skill = score_github_commit(
        commit("sync skill", [source_file("skills/foo/SKILL.md", status="added", changes=200)])
    )
    dependabot = score_github_commit(
        commit("Bump lodash from 1 to 2 by dependabot", [source_file("src/app.py")])
    )
    no_files = score_github_commit(commit("Add /animation-performance skill", []))
    readme_only = score_github_commit(
        commit("Add /animation-performance skill", [source_file("README.md")])
    )
    notes_only = score_github_commit(
        commit("新增 skill", [source_file("src/notes.md")])
    )
    plain_add = score_github_commit(
        commit("新增说明", [source_file("src/terms.py", changes=30)])
    )
    compound = score_github_commit(
        commit("Add skill-based routing", [source_file("src/router.py", changes=20)])
    )

    assert readme.visible is False
    assert readme.rejected_reason == "noise_message"
    assert sync_skill.visible is False
    assert sync_skill.rejected_reason == "noise_message"
    assert dependabot.visible is False
    assert dependabot.rejected_reason == "noise_message"
    assert no_files.visible is False
    assert no_files.rejected_reason == "missing_product_code"
    assert readme_only.visible is False
    assert readme_only.rejected_reason == "noise_only_files"
    assert notes_only.visible is False
    assert notes_only.rejected_reason == "noise_only_files"
    assert plain_add.visible is False
    assert plain_add.score == 50
    assert compound.visible is False
    assert compound.rejected_reason == "missing_feature_intent"


def test_legacy_archive_visibility_is_conservative_and_non_destructive() -> None:
    major = {
        "github_source_kind": "release",
        "tag_name": "v2.0.0",
        "release_name": "Partner 2.0.0",
        "prerelease": False,
    }
    patch = {
        "github_source_kind": "release",
        "tag_name": "v1.4.164",
        "release_name": "v1.4.164",
        "prerelease": False,
    }
    prerelease = {
        "github_source_kind": "release",
        "tag_name": "v1.4.164-rc.3",
        "release_name": "v1.4.164-rc.3",
        "prerelease": True,
    }
    legacy_commit = {
        "github_source_kind": "commit_fallback",
        "title": "owner/repo 提交: feat!: launch a new provider",
    }

    assert github_archive_record_is_reader_visible(major) is True
    assert github_archive_record_is_reader_visible(patch) is False
    assert github_archive_record_is_reader_visible(prerelease) is False
    assert github_archive_record_is_reader_visible(legacy_commit) is False


class _JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_patch_release_with_body_keeps_collection_score_when_displayed() -> None:
    notes = "Launch a new provider integration and command workflow."
    payload = {
        "id": 123,
        "tag_name": "v1.2.3",
        "name": "v1.2.3",
        "body": notes,
        "html_url": "https://github.com/example/repo/releases/tag/v1.2.3",
        "published_at": "2026-08-01T00:00:00Z",
        "draft": False,
        "prerelease": False,
    }
    decision = score_github_release(payload)
    without_body = score_github_release({**payload, "body": ""})

    assert decision.visible is True
    assert without_body.visible is False

    class FakeSession:
        def get(self, url, **kwargs):
            return _JsonResponse([payload])

    items = fetch_github_repo_subscription(
        FakeSession(),
        datetime.fromisoformat("2026-08-02T00:00:00+00:00"),
        api_url="https://api.github.com/repos/example/repo/releases",
        repo_label="example/repo",
    )

    assert len(items) == 1
    meta = items[0].meta
    assert meta["github_importance_score"] == decision.score
    assert meta["github_importance_reasons"] == list(decision.reasons)
    assert github_archive_record_is_reader_visible(meta) is True

    archive_record: dict = {}
    apply_public_raw_meta(archive_record, items[0])
    persisted = json.loads(json.dumps(archive_record))
    assert persisted["github_importance_score"] == decision.score
    assert persisted["github_importance_reasons"] == list(decision.reasons)
    assert github_archive_record_is_reader_visible(persisted) is True

    # 有存档分数就直接用它，即使标签本身重算会过线。
    low_score_major = {
        "github_source_kind": "release",
        "tag_name": "v2.0.0",
        "release_name": "v2.0.0",
        "prerelease": False,
        "github_importance_score": without_body.score,
        "github_importance_reasons": list(without_body.reasons),
    }
    assert github_archive_record_is_reader_visible(low_score_major) is False


def test_scored_commit_fallback_is_visible_and_legacy_commit_stays_hidden() -> None:
    sha = "a" * 40
    summary = {
        "sha": sha,
        "html_url": f"https://github.com/example/repo/commit/{sha}",
        "commit": {
            "message": "feat!: launch workspace automation\n\nAdd the first workspace runner.",
            "committer": {"date": "2026-07-15T12:00:00Z"},
            "author": {"date": "2026-07-15T11:00:00Z"},
        },
    }
    detail = {
        **summary,
        "stats": {"total": 40, "additions": 35, "deletions": 5},
        "files": [{
            "filename": "src/workspace_runner.py",
            "status": "added",
            "changes": 40,
            "additions": 35,
            "deletions": 5,
        }],
    }
    decision = score_github_commit(detail)
    assert decision.visible is True

    class FakeSession:
        def get(self, url, **kwargs):
            if url.endswith("/releases"):
                return _JsonResponse([])
            if url.endswith("/commits"):
                return _JsonResponse([summary])
            return _JsonResponse(detail)

    items = fetch_github_repo_subscription(
        FakeSession(),
        datetime.fromisoformat("2026-07-16T00:00:00+00:00"),
        api_url="https://api.github.com/repos/example/repo/releases",
        repo_label="example/repo",
        source_id="online_github_manual_abc",
    )

    assert len(items) == 1
    meta = items[0].meta
    assert meta["github_source_kind"] == "commit_fallback"
    assert meta["github_importance_score"] == decision.score
    assert meta["github_importance_reasons"] == list(decision.reasons)
    assert github_archive_record_is_reader_visible(meta) is True

    archive_record: dict = {}
    apply_public_raw_meta(archive_record, items[0])
    assert github_archive_record_is_reader_visible(json.loads(json.dumps(archive_record))) is True

    legacy_commit = {
        "github_source_kind": "commit_fallback",
        "title": "example/repo 提交: feat!: launch workspace automation",
    }
    assert github_archive_record_is_reader_visible(legacy_commit) is False

    hidden = score_github_commit(
        commit("feat: streamline terminology lookup", [source_file("src/terms.py", changes=30)])
    )
    assert hidden.visible is False
    assert github_archive_record_is_reader_visible({
        "github_source_kind": "commit_fallback",
        "github_importance_score": hidden.score,
        "github_importance_reasons": list(hidden.reasons),
    }) is False


def test_skill_commit_fallback_reaches_detail_and_stays_visible() -> None:
    sha = "b" * 40
    message = "Add /animation-performance skill"
    summary = {
        "sha": sha,
        "html_url": f"https://github.com/emilkowalski/skills/commit/{sha}",
        "commit": {
            "message": message,
            "committer": {"date": "2026-10-11T12:00:00Z"},
        },
    }
    detail = {
        **summary,
        "files": [
            {"filename": "README.md", "status": "modified", "changes": 1, "additions": 1, "deletions": 0},
            {
                "filename": "skills/animation-performance/SKILL.md",
                "status": "added",
                "changes": 223,
                "additions": 223,
                "deletions": 0,
            },
        ],
    }
    summary_decision = score_github_commit(summary)
    detail_decision = score_github_commit(detail)
    assert summary_decision.rejected_reason == "missing_product_code"
    assert detail_decision.visible is True

    class FakeSession:
        def get(self, url, **kwargs):
            if url.endswith("/releases"):
                return _JsonResponse([])
            if url.endswith("/commits"):
                return _JsonResponse([summary])
            return _JsonResponse(detail)

    items = fetch_github_repo_subscription(
        FakeSession(),
        datetime.fromisoformat("2026-10-12T00:00:00+00:00"),
        api_url="https://api.github.com/repos/emilkowalski/skills/releases",
        repo_label="emilkowalski/skills",
        source_id="online_github_manual_skills",
    )

    assert len(items) == 1
    assert items[0].meta["github_source_kind"] == "commit_fallback"
    assert items[0].meta["github_importance_score"] == detail_decision.score
    assert github_archive_record_is_reader_visible(items[0].meta) is True


def test_legacy_release_without_stored_score_keeps_rescore_behavior() -> None:
    patch = {
        "github_source_kind": "release",
        "tag_name": "v1.2.3",
        "release_name": "v1.2.3",
        "prerelease": False,
    }
    major = {
        "github_source_kind": "release",
        "tag_name": "v2.0.0",
        "release_name": "v2.0.0",
        "prerelease": False,
    }
    prerelease = {
        "github_source_kind": "release",
        "tag_name": "v1.2.3-rc.1",
        "release_name": "v1.2.3-rc.1",
        "prerelease": True,
    }

    assert "github_importance_score" not in patch
    assert github_archive_record_is_reader_visible(patch) is False
    assert github_archive_record_is_reader_visible(major) is True
    assert github_archive_record_is_reader_visible(prerelease) is False
    assert github_archive_record_is_reader_visible(patch) is score_github_release(
        {"tag_name": "v1.2.3", "name": "v1.2.3", "body": "", "draft": False, "prerelease": False}
    ).visible


# --- Mutation-hardening tests (noise classification, change counting, archive gate) ---

from scripts.radar.github_importance import (
    GITHUB_IMPORTANCE_THRESHOLD,
    _decision,
    _file_changes,
    _is_noise_file,
    _is_product_source_file,
)


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "   ",
        "docs/guide.py",
        "src/tests/helper.py",
        "pkg/vendor/lib.py",
        ".github/workflows/ci.py",
        "a/generated/x.ts",
        "uv.lock",
        "frontend/package-lock.json",
        "README.txt",
        "ChangeLog",
        "LICENSE",
        "CONTRIBUTING.txt",
        "code_of_conduct",
        "src/notes.md",
        "src/skills.md",
        "performance-cheatsheet.md",
        "skills/foo/README.md",
        "skills/foo/docs/guide.md",
        "skills/foo/core.test.md",
        "docs/SKILL.md",
        "tests/fixtures/SKILL.md",
        ".github/skills/foo/SKILL.md",
        "src/notes.rst",
        "src/notes.adoc",
        "src/ui.snap",
        "static/app.min.js",
        "static/app.min.css",
        "src/test_core.py",
        "src/core.test.ts",
        "src/core.spec.ts",
        "DOCS\\Guide.py",
    ],
)
def test_noise_files_are_classified_as_noise(filename: str) -> None:
    assert _is_noise_file({"filename": filename}) is True


@pytest.mark.parametrize(
    "filename",
    [
        "src/agent.py",
        "SKILL.md",
        "skill.md",
        "skills/animation-performance/SKILL.md",
        "skills/animate/RECIPES.md",
        ".claude/skills/foo/SKILL.md",
        ".agents/skills/foo/NOTES.md",
        "skills/ai-news-radar/references/source-intake.md",
        "docs.py",
        "tests.py",
        "src/uv.lock.py",
        "src/my_readme_parser.py",
        "src/contest_runner.py",
        "src/latest.py",
        "src/spectest.ts",
        "src/core.ts",
        "a//b/model.go",
    ],
)
def test_product_files_are_not_noise(filename: str) -> None:
    assert _is_noise_file({"filename": filename}) is False


@pytest.mark.parametrize(
    "filename",
    [
        "SKILL.md",
        "skill.md",
        "skills/animation-performance/SKILL.md",
        "skills/animate/RECIPES.md",
        ".agents/skills/foo/NOTES.md",
    ],
)
def test_skill_markdown_is_product_source(filename: str) -> None:
    assert _is_product_source_file({"filename": filename}) is True
    assert _is_noise_file({"filename": filename}) is False


def test_missing_filename_is_noise() -> None:
    assert _is_noise_file({}) is True
    assert _is_noise_file({"filename": None}) is True


@pytest.mark.parametrize(
    "value, expected",
    [(None, 0), ("", 0), (0, 0), (-5, 0), (1, 1), ("42", 42), (150, 150), ("abc", 0), ([1], 0)],
)
def test_file_changes_parses_and_clamps(value, expected) -> None:
    assert _file_changes({"changes": value}) == expected


def test_file_changes_missing_key_is_zero() -> None:
    assert _file_changes({}) == 0


def test_decision_clamps_score_bounds() -> None:
    assert _decision(-10, []).score == 0
    assert _decision(250, []).score == 100
    assert _decision(GITHUB_IMPORTANCE_THRESHOLD, []).visible is True
    assert _decision(GITHUB_IMPORTANCE_THRESHOLD - 1, []).visible is False
    assert _decision(100, [], "x").visible is False


def test_draft_release_is_rejected() -> None:
    decision = score_github_release({"tag_name": "v2.0.0", "draft": True})
    assert decision.rejected_reason == "draft"
    assert decision.score == 0
    assert decision.visible is False


def test_calendar_year_bounds() -> None:
    assert score_github_release(release("v2000.1.0")).visible is False
    assert score_github_release(release("v2099.0.0")).visible is False
    assert score_github_release(release("v1999.0.0")).visible is True
    assert score_github_release(release("v2100.0.0")).visible is True


def test_commit_scope_thresholds_are_inclusive() -> None:
    msg = "feat: add thing"
    two = [source_file("src/a.py", changes=10), source_file("src/b.py", changes=10)]
    three = two + [source_file("src/c.py", changes=10)]
    assert "substantial_product_scope" not in score_github_commit(commit(msg, two)).reasons
    assert "substantial_product_scope" in score_github_commit(commit(msg, three)).reasons
    assert "substantial_product_scope" not in score_github_commit(commit(msg, [source_file("src/a.py", changes=99)])).reasons
    assert "substantial_product_scope" in score_github_commit(commit(msg, [source_file("src/a.py", changes=100)])).reasons
    # negative change counts must not reduce the total
    neg = [source_file("src/a.py", changes=100), source_file("src/b.py", changes=-50)]
    assert "substantial_product_scope" in score_github_commit(commit(msg, neg)).reasons


@pytest.mark.parametrize(
    "record, expected",
    [
        ({"github_importance_score": 70}, True),
        ({"github_importance_score": 69}, False),
        ({"github_importance_score": 69.9}, False),
        ({"github_importance_score": 250}, True),
        ({"github_importance_score": 90, "github_source_kind": "commit_fallback"}, True),
        ({"github_importance_score": 10, "github_source_kind": "release", "tag_name": "v2.0.0"}, False),
        # bool / non-numeric scores fall back to legacy logic
        ({"github_importance_score": True, "github_source_kind": "release", "tag_name": "v2.0.0"}, True),
        ({"github_importance_score": True, "github_source_kind": "commit_fallback"}, False),
        ({"github_importance_score": "90", "github_source_kind": "commit_fallback"}, False),
        ({"github_importance_score": None, "github_source_kind": "release", "tag_name": "v2.0.0"}, True),
        # legacy (no stored score) paths
        ({"github_source_kind": "commit_fallback", "tag_name": "v2.0.0"}, False),
        ({"github_source_kind": " commit_fallback ", "tag_name": "v2.0.0"}, False),
        ({"github_source_kind": "release", "tag_name": "v2.0.0"}, True),
        ({"github_source_kind": " release ", "tag_name": "v2.0.0"}, True),
        ({"github_source_kind": "release", "tag_name": "v2.0.1"}, False),
        ({"github_source_kind": "release", "tag_name": "v2.0.0", "prerelease": True}, False),
        ({"github_source_kind": "release", "release_name": "v3.0.0", "tag_name": ""}, True),
        ({"github_source_kind": "commit", "tag_name": "v2.0.0"}, True),
        ({"github_source_kind": "commit", "release_id": 1, "tag_name": "v2.0.0"}, True),
        ({"github_source_kind": "commit", "release_id": 1, "release_name": "v2.0.0"}, True),
        ({"github_source_kind": "commit"}, False),
        ({}, False),
    ],
)
def test_archive_visibility_gate(record, expected) -> None:
    assert github_archive_record_is_reader_visible(record) is expected
