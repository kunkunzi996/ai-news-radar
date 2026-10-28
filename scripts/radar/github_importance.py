from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


GITHUB_IMPORTANCE_THRESHOLD = 70

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:\+[0-9a-z.-]+)?$", re.IGNORECASE)
_PRERELEASE_RE = re.compile(
    r"(?:^|[\s._-])(alpha|beta|rc|preview|nightly)(?=$|[\s._-]|\d)",
    re.IGNORECASE,
)
_SKILL_WORD = r"skills?(?![\w-])"
_STRONG_INTENT_PATTERNS = (
    re.compile(r"\bbreaking[\s_-]+change\b", re.IGNORECASE),
    re.compile(r"\bfeat(?:\([^)]*\))?!\s*:", re.IGNORECASE),
    re.compile(
        r"\b(?:launch(?:es|ed|ing)?|introduc(?:e|es|ed|ing)|new)\b.{0,60}"
        r"\b(?:feature|capabilit(?:y|ies)|platform|integration|module|command|workflow|provider|agent)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"(?:全新|重大更新|重大功能|核心重构|正式上线|新平台|新集成)"),
    re.compile(r"新增.{0,30}(?:功能|能力|模块|命令|入口|平台|集成|服务)"),
    # Skill 包的新增/更新本身就是功能变化。强意图 + 一份产品文件 = 70，单文件修改也能过门槛。
    re.compile(
        rf"\b(?:add(?:ed|s|ing)?|new|update[ds]?|updating)\b.{{0,80}}\b{_SKILL_WORD}",
        re.IGNORECASE,
    ),
    re.compile(rf"(?:新增|更新|增加|接入).{{0,40}}(?:{_SKILL_WORD}|技能)|新技能", re.IGNORECASE),
    re.compile(r"(?:^|\n)\s*feat\([^)]*skills?[^)]*\)\s*:", re.IGNORECASE),
    re.compile(
        rf"(?:^|\n)\s*feat(?:\([^)]*\))?\s*:[^\n]{{0,120}}\b{_SKILL_WORD}",
        re.IGNORECASE,
    ),
)
_NORMAL_INTENT_PATTERNS = (
    re.compile(r"(?:^|\n)\s*feat(?:\([^)]*\))?\s*:", re.IGNORECASE),
    re.compile(r"\badd(?:ed|s|ing)?\s+(?:support|integration|feature|command|workflow)\b", re.IGNORECASE),
    re.compile(r"(?:新增|增加支持|接入)"),
)
_NOISE_MESSAGE_RE = re.compile(
    r"^\s*(?:docs?|tests?|ci|chore|style|build|deps?|refactor|format|typo)"
    r"(?:\([^)]*\))?\s*:",
    re.IGNORECASE,
)
_GENERIC_MERGE_RE = re.compile(r"^\s*merge\s+(?:pull request|branch)\b", re.IGNORECASE)
_NOISE_MESSAGE_TEXT_RE = re.compile(
    r"(?:^update\s+readme\b|dependabot|renovate|auto(?:matic)?\s+sync|sync\s+skill|格式整理|标点整理)",
    re.IGNORECASE,
)

_NOISE_DIRS = {
    ".github",
    "ci",
    "doc",
    "docs",
    "test",
    "tests",
    "__tests__",
    "snapshots",
    "generated",
    "vendor",
}
_LOCK_FILES = {
    "cargo.lock",
    "composer.lock",
    "gemfile.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}
# 只认技能包产物，不把任意 .md 抬成产品文件。docs/tests 等目录里的同名副本仍走噪声规则。
_SKILL_PACKAGE_DIRS = {"skill", "skills"}
_DOC_NOISE_BASENAME_PREFIXES = ("readme", "changelog", "license", "contributing", "code_of_conduct")

_SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".proto",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".scss",
    ".sh",
    ".sql",
    ".svelte",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}


@dataclass(frozen=True)
class GithubImportanceDecision:
    score: int
    visible: bool
    reasons: tuple[str, ...] = ()
    rejected_reason: str = ""


def _decision(score: int, reasons: list[str], rejected_reason: str = "") -> GithubImportanceDecision:
    bounded = max(0, min(100, int(score)))
    return GithubImportanceDecision(
        score=bounded,
        visible=not rejected_reason and bounded >= GITHUB_IMPORTANCE_THRESHOLD,
        reasons=tuple(reasons),
        rejected_reason=rejected_reason,
    )


def _intent_strength(text: str) -> str:
    if any(pattern.search(text) for pattern in _STRONG_INTENT_PATTERNS):
        return "strong"
    if any(pattern.search(text) for pattern in _NORMAL_INTENT_PATTERNS):
        return "normal"
    return ""


def _release_is_prerelease(release: Mapping[str, Any], text: str) -> bool:
    return bool(release.get("prerelease")) or bool(_PRERELEASE_RE.search(text))


def score_github_release(release: Mapping[str, Any]) -> GithubImportanceDecision:
    tag = str(release.get("tag_name") or "").strip()
    name = str(release.get("name") or "").strip()
    body = str(release.get("body") or "").strip()
    version_text = " ".join(value for value in (tag, name) if value)
    if release.get("draft"):
        return _decision(0, [], "draft")
    if _release_is_prerelease(release, version_text):
        return _decision(0, [], "prerelease")

    score = 25
    reasons = ["stable_release"]
    match = _SEMVER_RE.fullmatch(tag or name)
    if match:
        major, minor, patch = (int(value) for value in match.groups())
        is_calendar_version = 2000 <= major <= 2099
        if not is_calendar_version and major > 0 and minor == 0 and patch == 0:
            score = 100
            reasons = ["semver_major"]
        elif not is_calendar_version and minor > 0 and patch == 0:
            score = 80
            reasons = ["semver_minor"]

    intent = _intent_strength("\n".join(value for value in (name, body) if value))
    if intent == "strong":
        score += 45
        reasons.append("strong_feature_notes")
    elif intent == "normal":
        score += 25
        reasons.append("feature_notes")
    return _decision(score, reasons)


def _normalized_filename(file_info: Mapping[str, Any]) -> str:
    return str(file_info.get("filename") or "").strip().replace("\\", "/").lower()


def _path_parts(filename: str) -> list[str]:
    return [part for part in filename.split("/") if part]


def _is_test_like_basename(basename: str) -> bool:
    return basename.startswith("test_") or ".test." in basename or ".spec." in basename


def _is_skill_product_markdown(parts: list[str]) -> bool:
    """SKILL.md，以及 skill 包目录下的配套 Markdown。普通文档不算。"""
    if not parts:
        return False
    basename = parts[-1]
    if not basename.endswith(".md"):
        return False
    if basename.startswith(_DOC_NOISE_BASENAME_PREFIXES) or _is_test_like_basename(basename):
        return False
    parents = parts[:-1]
    if any(part in _NOISE_DIRS for part in parents):
        return False
    if basename == "skill.md":
        return True
    return any(part in _SKILL_PACKAGE_DIRS for part in parents)


def _is_noise_file(file_info: Mapping[str, Any]) -> bool:
    filename = _normalized_filename(file_info)
    if not filename:
        return True
    parts = _path_parts(filename)
    basename = parts[-1]
    if _is_skill_product_markdown(parts):
        return False
    if any(part in _NOISE_DIRS for part in parts[:-1]):
        return True
    if basename in _LOCK_FILES:
        return True
    if basename.startswith(_DOC_NOISE_BASENAME_PREFIXES):
        return True
    if basename.endswith((".md", ".rst", ".adoc", ".snap", ".min.js", ".min.css")):
        return True
    if _is_test_like_basename(basename):
        return True
    return False


def _is_product_source_file(file_info: Mapping[str, Any]) -> bool:
    if _is_noise_file(file_info):
        return False
    filename = _normalized_filename(file_info)
    if _is_skill_product_markdown(_path_parts(filename)):
        return True
    return any(filename.endswith(suffix) for suffix in _SOURCE_SUFFIXES)


def _file_changes(file_info: Mapping[str, Any]) -> int:
    try:
        return max(0, int(file_info.get("changes") or 0))
    except (TypeError, ValueError):
        return 0


def score_github_commit(commit: Mapping[str, Any]) -> GithubImportanceDecision:
    commit_data = commit.get("commit") if isinstance(commit.get("commit"), Mapping) else {}
    message = str(commit_data.get("message") or "").strip()
    title = message.splitlines()[0].strip() if message else ""
    files_value = commit.get("files")
    files = [item for item in files_value if isinstance(item, Mapping)] if isinstance(files_value, list) else []

    if _NOISE_MESSAGE_RE.search(title) or _GENERIC_MERGE_RE.search(title) or _NOISE_MESSAGE_TEXT_RE.search(title):
        return _decision(0, [], "noise_message")

    product_files = [item for item in files if _is_product_source_file(item)]
    if files and not product_files:
        return _decision(0, [], "noise_only_files")

    intent = _intent_strength(message)
    score = 0
    reasons: list[str] = []
    if intent == "strong":
        score += 45
        reasons.append("strong_feature_intent")
    elif intent == "normal":
        score += 25
        reasons.append("feature_intent")

    if product_files:
        score += 25
        reasons.append("product_code")

    added_product_files = [item for item in product_files if str(item.get("status") or "").lower() == "added"]
    if intent and added_product_files:
        score += 20
        reasons.append("new_product_module")

    product_changes = sum(_file_changes(item) for item in product_files)
    if len(product_files) >= 3 or product_changes >= 100:
        score += 20
        reasons.append("substantial_product_scope")

    if not intent:
        return _decision(score, reasons, "missing_feature_intent")
    if not product_files:
        return _decision(score, reasons, "missing_product_code")
    return _decision(score, reasons)


def _stored_importance_score(record: Mapping[str, Any]) -> int | float | None:
    """采集时写入的分数。缺字段或不是数字的旧归档继续走回退。"""
    if "github_importance_score" not in record:
        return None
    value = record.get("github_importance_score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def github_archive_record_is_reader_visible(record: Mapping[str, Any]) -> bool:
    stored_score = _stored_importance_score(record)
    if stored_score is not None:
        # 与采集共用 _decision / GITHUB_IMPORTANCE_THRESHOLD，不再用空 body 重算。
        return _decision(stored_score, []).visible
    kind = str(record.get("github_source_kind") or "").strip()
    if kind == "commit_fallback":
        # 旧记录没有文件证据，也没有采集分数，按高置信度原则保守隐藏，但不删除归档。
        return False
    if kind != "release" and not (record.get("release_id") or record.get("tag_name")):
        return False
    decision = score_github_release(
        {
            "tag_name": record.get("tag_name"),
            "name": record.get("release_name") or record.get("tag_name"),
            "body": "",
            "draft": False,
            "prerelease": bool(record.get("prerelease")),
        }
    )
    return decision.visible
