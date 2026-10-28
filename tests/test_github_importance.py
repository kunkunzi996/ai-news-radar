import json
from datetime import datetime

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
