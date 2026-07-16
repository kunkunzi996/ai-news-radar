from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import uuid
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse, urlunparse

"""Public online source-config persistence and git sync helpers."""

ONLINE_CONFIG_FILENAME = Path("config") / "online-sources.json"
ONLINE_OPML_FILENAME = Path("feeds") / "online-sources.opml"
ONLINE_OPML_SOURCE_ID = "online_opmlrss"
ONLINE_ALLOWED_TYPES = frozenset(
    {"bilibili_dynamic", "github_release", "mediacrawler_jsonl", "rss", "we_mp_rss_jsonl"}
)
ONLINE_COMMIT_MESSAGE = "配置：同步线上信源"
ONLINE_SYNC_STASH_MESSAGE = "ai-news-radar:online-source-sync"
SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
GITHUB_LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
ONLINE_RESERVED_SOURCE_IDS = frozenset({ONLINE_OPML_SOURCE_ID})
GITHUB_MANAGED_FIELDS = (
    "managed_by",
    "managed_account_id",
    "managed_repo_id",
    "managed_state",
)
GITHUB_SAFE_TEXT_FIELDS = frozenset({"id", "name", "target", "locator"})
ONLINE_SOURCES_LOCK = threading.RLock()
ONLINE_OPERATION_SCHEMA_VERSION = 1
ONLINE_OPERATION_KINDS = frozenset({"apply", "unbind", "manual_save", "manual_sync"})
ONLINE_OPERATION_PHASES = frozenset(
    {
        "prepared",
        "write_incomplete",
        "files_written",
        "committed",
        "rebasing",
        "push_unknown",
        "restoring_worktree",
    }
)
ONLINE_OPERATION_MANIFEST_NAME = "ai-news-radar/github-star-sync-operation.json"

SENSITIVE_MARKERS = (
    "token",
    "cookie",
    "secret",
    "password",
    "authorization",
    "xsec_token",
    ".env",
)
PRIVATE_PATH_MARKERS = (
    "local-secrets",
    "chrome-profile",
    "mediacrawler-local-test",
    "creator_contents_",
    "feeds/follow.opml",
)
HIGH_CONFIDENCE_CREDENTIAL_PATTERNS = (
    re.compile(r"\bghp_[A-Za-z0-9_=-]{8,}\b", re.IGNORECASE),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_=-]{8,}\b", re.IGNORECASE),
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"\btoken\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"\bsecret\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"\bauthorization\s*[=:]\s*\S+", re.IGNORECASE),
)
TYPE_ORDER = {
    "bilibili_dynamic": 0,
    "github_release": 1,
    "mediacrawler_jsonl": 2,
    "we_mp_rss_jsonl": 3,
    "rss": 4,
}


class OnlineSourcesError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.details = dict(details or {})
        super().__init__(code)


def _online_error(
    code: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> OnlineSourcesError:
    return OnlineSourcesError(code, status_code=status_code, details=details)


@contextmanager
def online_sources_guard() -> Iterator[None]:
    if not ONLINE_SOURCES_LOCK.acquire(blocking=False):
        raise _online_error("online_sources_busy", 409)
    try:
        yield
    finally:
        ONLINE_SOURCES_LOCK.release()


def require_online_config_match(raw_if_match: Any, current_digest: str) -> str:
    match = re.fullmatch(r'"([0-9a-f]{64})"', raw_if_match) if isinstance(raw_if_match, str) else None
    if match is None or match.group(1) != current_digest:
        raise _online_error("online_sources_config_stale", 409)
    return current_digest


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def online_config_path(root_dir: Path) -> Path:
    return (root_dir / ONLINE_CONFIG_FILENAME).resolve()


def online_opml_path(root_dir: Path) -> Path:
    return (root_dir / ONLINE_OPML_FILENAME).resolve()


def ensure_public_online_paths(root_dir: Path) -> tuple[Path, Path]:
    config_path = online_config_path(root_dir)
    opml_path = online_opml_path(root_dir)
    if config_path != (root_dir / ONLINE_CONFIG_FILENAME).resolve():
        raise ValueError("invalid_online_config_path")
    if opml_path != (root_dir / ONLINE_OPML_FILENAME).resolve():
        raise ValueError("invalid_online_opml_path")
    return config_path, opml_path


def contains_high_confidence_credential(value: str) -> bool:
    return any(pattern.search(value) for pattern in HIGH_CONFIDENCE_CREDENTIAL_PATTERNS)


def check_public_text_safe(value: str, path: str, *, allow_github_markers: bool = False) -> None:
    text = value.lower().replace("\\", "/")
    if contains_high_confidence_credential(value):
        raise ValueError(f"{path} contains a credential shape")
    if not allow_github_markers and any(marker in text for marker in SENSITIVE_MARKERS):
        raise ValueError(f"{path} contains sensitive text")
    if any(marker in text for marker in PRIVATE_PATH_MARKERS):
        raise ValueError(f"{path} contains a private local path")


def check_public_payload_safe(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            text = str(key).lower()
            if any(marker in text for marker in SENSITIVE_MARKERS):
                raise ValueError(f"{path}.{key} contains a sensitive field name")
            check_public_payload_safe(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            check_public_payload_safe(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        check_public_text_safe(value, path)


def check_online_source_payload_safe(source: dict[str, Any], index: int, source_type: str) -> None:
    path = f"sources[{index}]"
    for key, child in source.items():
        key_text = str(key).lower()
        child_path = f"{path}.{key}"
        if any(marker in key_text for marker in SENSITIVE_MARKERS):
            raise ValueError(f"{child_path} contains a sensitive field name")
        if isinstance(child, str):
            check_public_text_safe(
                child,
                child_path,
                allow_github_markers=(source_type == "github_release" and key_text in GITHUB_SAFE_TEXT_FIELDS),
            )
        elif isinstance(child, (dict, list)):
            check_public_payload_safe(child, child_path)


def positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_existing_source_id(source_id: Any, index: int) -> str:
    value = str(source_id or "").strip()
    if not SOURCE_ID_PATTERN.fullmatch(value) or value in ONLINE_RESERVED_SOURCE_IDS:
        raise ValueError(
            f"online_source_id_migration_required: sources[{index}].id is missing, invalid, or reserved"
        )
    return value


def manual_github_source_id(repo: str, used_ids: set[str] | None = None) -> str:
    digest = hashlib.sha256(repo.casefold().encode("utf-8")).hexdigest()
    occupied = used_ids or set()
    for length in (12, 16, 24, 64):
        candidate = f"online_github_manual_{digest[:length]}"
        if candidate not in occupied:
            return candidate
    raise ValueError("online_source_id_conflict: no collision-free GitHub manual source id")


def normalize_github_star_sync(raw_binding: Any) -> dict[str, Any] | None:
    if raw_binding is None:
        return None
    if not isinstance(raw_binding, dict):
        raise ValueError("github_star_binding_ambiguous: github_star_sync must be an object")
    allowed_keys = {"version", "account_id", "account_login"}
    if set(raw_binding) != allowed_keys:
        raise ValueError("github_star_binding_ambiguous: github_star_sync fields are invalid")
    version = raw_binding.get("version")
    account_id = raw_binding.get("account_id")
    account_login = str(raw_binding.get("account_login") or "").strip()
    if version != 1 or isinstance(version, bool) or not positive_integer(account_id):
        raise ValueError("github_star_binding_ambiguous: github_star_sync identity is invalid")
    if not GITHUB_LOGIN_PATTERN.fullmatch(account_login) or "--" in account_login:
        raise ValueError("github_star_binding_ambiguous: account_login is invalid")
    if contains_high_confidence_credential(account_login):
        raise ValueError("github_star_binding_ambiguous: account_login contains a credential shape")
    return {
        "version": 1,
        "account_id": account_id,
        "account_login": account_login,
    }


def normalize_managed_fields(
    source: dict[str, Any],
    index: int,
    source_type: str,
    enabled: bool,
) -> dict[str, Any]:
    present = [field in source for field in GITHUB_MANAGED_FIELDS]
    if any(present) and not all(present):
        raise ValueError(
            f"github_star_binding_ambiguous: sources[{index}] managed fields must be complete"
        )
    if not any(present):
        return {}
    managed_by = source.get("managed_by")
    account_id = source.get("managed_account_id")
    repo_id = source.get("managed_repo_id")
    managed_state = source.get("managed_state")
    if source_type != "github_release" or managed_by != "github_stars":
        raise ValueError(f"github_star_binding_ambiguous: sources[{index}] managed type is invalid")
    if not positive_integer(account_id) or not positive_integer(repo_id):
        raise ValueError(f"github_star_binding_ambiguous: sources[{index}] managed ids are invalid")
    if managed_state not in {"active", "auto_disabled"}:
        raise ValueError(f"github_star_binding_ambiguous: sources[{index}] managed_state is invalid")
    if (managed_state == "active") != enabled:
        raise ValueError(
            f"github_star_binding_ambiguous: sources[{index}] managed_state contradicts enabled"
        )
    return {
        "managed_by": "github_stars",
        "managed_account_id": account_id,
        "managed_repo_id": repo_id,
        "managed_state": managed_state,
    }


def slug_token(value: str, fallback: str = "source") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return (text or fallback)[:64]


def feed_id_for_url(url: str) -> str:
    digest = hashlib.sha1(str(url or "").strip().encode("utf-8")).hexdigest()[:10]
    return f"online_feed_{digest}"


def normalize_online_type(raw_type: str) -> str:
    value = str(raw_type or "rss").strip().lower().replace("-", "_")
    aliases = {
        "bilibili": "bilibili_dynamic",
        "b站": "bilibili_dynamic",
        "github": "github_release",
        "github_releases": "github_release",
        "youtube": "rss",
        "feed": "rss",
        "atom": "rss",
        "douyin": "mediacrawler_jsonl",
        "抖音": "mediacrawler_jsonl",
        "mediacrawler_douyin": "mediacrawler_jsonl",
    }
    return aliases.get(value, value)


def normalize_http_url(value: str, index: int) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"sources[{index}].locator must be an http/https URL")
    clean = parsed._replace(fragment="")
    return urlunparse(clean)


def normalize_bilibili_uid(value: str, index: int) -> str:
    uid = str(value or "").strip()
    if not re.fullmatch(r"\d{2,20}", uid):
        raise ValueError(f"sources[{index}].locator must be a public Bilibili UID")
    return uid


def normalize_douyin_homepage(value: str, index: int) -> str:
    """只接受抖音创作者主页链接，清洗成 https://www.douyin.com/user/<sec_uid>。"""
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.lower() in {"www.douyin.com", "douyin.com"}
        and len(parts) >= 2
        and parts[0] == "user"
        and re.fullmatch(r"[A-Za-z0-9_=-]+", parts[1] or "")
    ):
        return f"https://www.douyin.com/user/{parts[1]}"
    raise ValueError(f"sources[{index}].locator must be a Douyin creator homepage URL (https://www.douyin.com/user/...)")


def normalize_github_repo(value: str, index: int) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.netloc.lower() == "api.github.com":
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 3 and parts[0] == "repos":
            raw = f"{parts[1]}/{parts[2]}"
    elif parsed.netloc.lower() in {"github.com", "www.github.com"}:
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            raw = f"{parts[0]}/{parts[1]}"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", raw):
        raise ValueError(f"sources[{index}].locator must be owner/repo or a GitHub repo URL")
    return raw


def normalize_online_source_record(
    source: dict[str, Any],
    index: int,
    *,
    existing: bool = False,
    used_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        raise ValueError(f"sources[{index}] must be an object")
    source_type = normalize_online_type(str(source.get("type") or "rss"))
    source_id_value = str(source.get("id") or "").strip()
    if source_type == "opmlrss" and source_id_value == ONLINE_OPML_SOURCE_ID:
        return None
    if source_id_value in ONLINE_RESERVED_SOURCE_IDS:
        code = "online_source_id_migration_required" if existing else "online_source_id_conflict"
        raise ValueError(f"{code}: sources[{index}].id is reserved")
    if source_type not in ONLINE_ALLOWED_TYPES:
        raise ValueError(f"sources[{index}].type is not supported for online sync")

    name = str(source.get("name") or source.get("target") or "").strip()
    locator = str(source.get("locator") or source.get("url") or source.get("feed_url") or "").strip()
    notes = str(source.get("notes") or "").strip()
    enabled = source.get("enabled") is not False
    check_online_source_payload_safe(source, index, source_type)
    managed_fields = normalize_managed_fields(source, index, source_type, enabled)

    def record_id(generated: str) -> str:
        return validate_existing_source_id(source_id_value, index) if existing else generated

    if source_type == "bilibili_dynamic":
        locator = normalize_bilibili_uid(locator, index)
        if not name:
            raise ValueError(f"sources[{index}].name is required")
        record = {
            "id": record_id(f"online_bilibili_{locator}"),
            "name": name[:120],
            "type": source_type,
            "enabled": enabled,
            "channel": "B站动态",
            "target": name[:120],
            "locator": locator,
            "env": "",
            "notes": notes[:240] or "公开 UID",
        }
        record.update(managed_fields)
        return record

    if source_type == "mediacrawler_jsonl":
        homepage = normalize_douyin_homepage(locator, index)
        if not name:
            raise ValueError(f"sources[{index}].name is required")
        digest = hashlib.sha1(homepage.encode("utf-8")).hexdigest()[:10]
        record = {
            "id": record_id(f"online_douyin_{digest}"),
            "name": name[:120],
            "type": source_type,
            "enabled": enabled,
            "channel": "抖音订阅",
            "target": name[:120],
            "locator": homepage,
            "env": "",
            "notes": notes[:240] or "云电脑桥接采集",
        }
        record.update(managed_fields)
        return record

    if source_type == "we_mp_rss_jsonl":
        if not name:
            raise ValueError(f"sources[{index}].name is required")
        generated_id = source_id_value or f"online_we_mp_rss_{slug_token(name)}"
        if not SOURCE_ID_PATTERN.fullmatch(generated_id) or generated_id in ONLINE_RESERVED_SOURCE_IDS:
            code = "online_source_id_migration_required" if existing else "online_source_id_conflict"
            raise ValueError(f"{code}: sources[{index}].id is invalid or reserved")
        record = {
            "id": record_id(generated_id),
            "name": name[:120],
            "type": source_type,
            "enabled": enabled,
            "channel": "微信公众号",
            "target": str(source.get("target") or name).strip()[:120],
            "locator": locator,
            "env": "",
            "notes": notes[:240] or "云电脑桥接采集",
        }
        record.update(managed_fields)
        return record

    if source_type == "github_release":
        repo = normalize_github_repo(locator or name, index)
        display_name = name or repo
        if existing:
            source_id = validate_existing_source_id(source_id_value, index)
        elif managed_fields:
            source_id = f"online_github_repo_{managed_fields['managed_repo_id']}"
            if source_id in (used_ids or set()):
                raise ValueError(f"online_source_id_conflict: sources[{index}] managed id is occupied")
        else:
            source_id = manual_github_source_id(repo, used_ids)
        record = {
            "id": source_id,
            "name": display_name[:120],
            "type": source_type,
            "enabled": enabled,
            "channel": "GitHub Release",
            "target": repo,
            "locator": repo,
            "env": "",
            "notes": notes[:240] or "只追踪 release",
        }
        record.update(managed_fields)
        return record

    feed_url = normalize_http_url(locator, index)
    if not name:
        raise ValueError(f"sources[{index}].name is required")
    record = {
        "id": record_id(feed_id_for_url(feed_url)),
        "name": name[:120],
        "type": "rss",
        "enabled": enabled,
        "channel": str(source.get("channel") or "RSS/YouTube").strip()[:80],
        "target": str(source.get("target") or name).strip()[:120],
        "locator": feed_url,
        "env": "",
        "notes": notes[:240] or "公开 feed",
    }
    record.update(managed_fields)
    return record


def normalize_online_sources(
    raw_sources: Any,
    *,
    existing: bool = False,
    used_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(raw_sources, list):
        raise ValueError("sources must be an array")
    if len(raw_sources) > 300:
        raise ValueError("too many online sources")
    if existing:
        seen_existing_ids: set[str] = set()
        for index, source in enumerate(raw_sources):
            if not isinstance(source, dict):
                raise ValueError(f"sources[{index}] must be an object")
            source_type = normalize_online_type(str(source.get("type") or "rss"))
            source_id = str(source.get("id") or "").strip()
            if source_type == "opmlrss" and source_id == ONLINE_OPML_SOURCE_ID:
                continue
            source_id = validate_existing_source_id(source_id, index)
            if source_id in seen_existing_ids:
                raise ValueError(
                    f"online_source_id_migration_required: duplicate source id {source_id}"
                )
            seen_existing_ids.add(source_id)

    allocated_ids = set(used_ids or set())
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    by_id: dict[str, tuple[str, str]] = {}
    github_locators: set[str] = set()
    for index, source in enumerate(raw_sources):
        record = normalize_online_source_record(
            source,
            index,
            existing=existing,
            used_ids=allocated_ids,
        )
        if not record:
            continue
        key = (record["type"], record["locator"])
        if record["type"] == "github_release" and record["locator"].casefold() in github_locators:
            raise ValueError(
                f"online_source_id_conflict: duplicate GitHub locator {record['locator']}"
            )
        previous_key = by_id.get(record["id"])
        if previous_key is not None and previous_key != key:
            code = "online_source_id_migration_required" if existing else "online_source_id_conflict"
            raise ValueError(f"{code}: duplicate source id {record['id']}")
        if record["type"] == "github_release":
            github_locators.add(record["locator"].casefold())
        by_id[record["id"]] = key
        by_key[key] = record
        allocated_ids.add(record["id"])
    return sorted(
        by_key.values(),
        key=lambda item: (TYPE_ORDER.get(item["type"], 99), item["id"]),
    )


def validate_online_config_schema(config: Any, *, existing: bool = True) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("online config must be an object")
    raw_sources = config.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("online config must contain a sources array")

    for key, value in config.items():
        if key in {"sources", "github_star_sync"}:
            continue
        check_public_payload_safe(value, f"config.{key}")

    sources = normalize_online_sources(raw_sources, existing=existing)
    binding = normalize_github_star_sync(config.get("github_star_sync"))
    seen_repo_ids: set[int] = set()
    for index, source in enumerate(sources):
        if source.get("managed_by") != "github_stars":
            continue
        if binding is None:
            raise ValueError(
                "github_star_binding_ambiguous: managed sources require github_star_sync"
            )
        if source["managed_account_id"] != binding["account_id"]:
            raise ValueError(
                f"github_star_account_mismatch: sources[{index}] belongs to another account"
            )
        repo_id = source["managed_repo_id"]
        if repo_id in seen_repo_ids:
            raise ValueError(f"online_source_id_conflict: duplicate managed repo id {repo_id}")
        seen_repo_ids.add(repo_id)

    normalized = {
        "version": str(config.get("version") or "1.0"),
        "mode": str(config.get("mode") or "online-public-source-config"),
        "updated_at": str(config.get("updated_at") or ""),
        "sources": sources,
    }
    if binding is not None:
        normalized["github_star_sync"] = binding
    return normalized


def protected_online_config_projection(config: dict[str, Any]) -> dict[str, Any]:
    managed_sources = [
        dict(source)
        for source in config.get("sources", [])
        if isinstance(source, dict) and source.get("managed_by") == "github_stars"
    ]
    managed_sources.sort(key=lambda source: source.get("id", ""))
    return {
        "github_star_sync": config.get("github_star_sync"),
        "managed_sources": managed_sources,
    }


def online_config_digest(config: dict[str, Any]) -> str:
    if not isinstance(config, dict):
        raise ValueError("online config must be an object")
    projection: dict[str, Any] = {}
    for key, value in config.items():
        if key == "updated_at":
            continue
        if key == "sources":
            if not isinstance(value, list):
                raise ValueError("online config must contain a sources array")
            projection[key] = [
                source
                for source in value
                if not (
                    isinstance(source, dict)
                    and (
                        source.get("id") == ONLINE_OPML_SOURCE_ID
                        or source.get("type") == "opmlrss"
                    )
                )
            ]
        else:
            projection[key] = value
    canonical = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def online_config_etag(config_or_digest: dict[str, Any] | str) -> str:
    digest = (
        config_or_digest
        if isinstance(config_or_digest, str) and re.fullmatch(r"[0-9a-f]{64}", config_or_digest)
        else online_config_digest(config_or_digest)  # type: ignore[arg-type]
    )
    return f'"{digest}"'


def generated_opml_source(enabled: bool) -> dict[str, Any]:
    return {
        "id": ONLINE_OPML_SOURCE_ID,
        "name": "线上 RSS/YouTube 订阅包",
        "type": "opmlrss",
        "enabled": enabled,
        "channel": "RSS/OPML",
        "target": str(ONLINE_OPML_FILENAME).replace("\\", "/"),
        "locator": str(ONLINE_OPML_FILENAME).replace("\\", "/"),
        "env": "",
        "notes": "公开 feed 列表",
    }


def build_online_config(
    sources: list[dict[str, Any]],
    updated_at: str | None = None,
    github_star_sync: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rss_sources = [source for source in sources if source["type"] == "rss"]
    config_sources = [dict(source) for source in sources]
    if rss_sources:
        config_sources.append(generated_opml_source(any(source.get("enabled") is not False for source in rss_sources)))
    config = {
        "version": "1.0",
        "mode": "online-public-source-config",
        "updated_at": updated_at or utc_timestamp(),
        "sources": config_sources,
    }
    if github_star_sync is not None:
        config["github_star_sync"] = dict(github_star_sync)
    return config


def read_online_opml(root_dir: Path) -> list[dict[str, Any]]:
    _, path = ensure_public_online_paths(root_dir)
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for outline in root.findall(".//outline"):
        xml_url = str(outline.attrib.get("xmlUrl") or "").strip()
        if not xml_url or xml_url in seen:
            continue
        try:
            feed_url = normalize_http_url(xml_url, len(sources))
        except ValueError:
            continue
        seen.add(feed_url)
        title = str(outline.attrib.get("title") or outline.attrib.get("text") or feed_url).strip()
        sources.append(
            {
                "id": feed_id_for_url(feed_url),
                "name": title[:120],
                "type": "rss",
                "enabled": True,
                "channel": "RSS/YouTube",
                "target": title[:120],
                "locator": feed_url,
                "env": "",
                "notes": "公开 feed",
            }
        )
    return sources


def render_online_opml_bytes(
    sources: list[dict[str, Any]],
) -> tuple[bytes, list[dict[str, Any]]]:
    feeds = [source for source in sources if source["type"] == "rss" and source.get("enabled") is not False]
    opml = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(opml, "head")
    title = ET.SubElement(head, "title")
    title.text = "AI News Radar Online Sources"
    body = ET.SubElement(opml, "body")
    for feed in feeds:
        ET.SubElement(
            body,
            "outline",
            {
                "text": feed["name"],
                "title": feed["name"],
                "type": "rss",
                "xmlUrl": feed["locator"],
                "htmlUrl": "",
            },
        )
    tree = ET.ElementTree(opml)
    ET.indent(tree, space="  ")
    return ET.tostring(opml, encoding="utf-8", xml_declaration=True), feeds


def write_online_opml(root_dir: Path, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _, path = ensure_public_online_paths(root_dir)
    content, feeds = render_online_opml_bytes(sources)
    atomic_replace_bytes(path, content)
    return feeds


def online_user_sources_from_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sources = config.get("sources") if isinstance(config, dict) else []
    normalized = normalize_online_sources(raw_sources, existing=True)
    return normalized


def read_online_source_config(root_dir: Path) -> dict[str, Any]:
    config_path, opml_path = ensure_public_online_paths(root_dir)
    config: dict[str, Any]
    binding: dict[str, Any] | None = None
    if config_path.exists():
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
        normalized_config = validate_online_config_schema(raw_config, existing=True)
        sources = normalized_config["sources"]
        binding = normalized_config.get("github_star_sync")
        updated_at = normalized_config.get("updated_at") or None
    else:
        sources = read_online_opml(root_dir)
        updated_at = None
    sources = normalize_online_sources(sources, existing=True)
    config = build_online_config(sources, updated_at=updated_at, github_star_sync=binding)
    digest = online_config_digest(config)
    return {
        "ok": True,
        "path": str(ONLINE_CONFIG_FILENAME).replace("\\", "/"),
        "opml_path": str(ONLINE_OPML_FILENAME).replace("\\", "/"),
        "exists": config_path.exists(),
        "opml_exists": opml_path.exists(),
        "source_count": len(sources),
        "enabled_source_count": sum(1 for source in sources if source.get("enabled") is not False),
        "base_config_digest": digest,
        "etag": online_config_etag(digest),
        "config": config,
        "sources": sources,
    }


def render_json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_replace_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_bytes(content)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def write_json_atomic(path: Path, payload: Any) -> None:
    atomic_replace_bytes(path, render_json_bytes(payload))


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes()) if path.exists() else sha256_bytes(b"")


def _normalized_online_text_bytes(content: bytes) -> bytes:
    return content.replace(b"\r\n", b"\n")


def _online_content_sha256(content: bytes) -> str:
    return sha256_bytes(_normalized_online_text_bytes(content))


def _online_file_sha256(path: Path) -> str:
    return _online_content_sha256(path.read_bytes()) if path.exists() else sha256_bytes(b"")


def _online_file_matches(path: Path, expected: bytes) -> bool:
    return path.exists() and _normalized_online_text_bytes(path.read_bytes()) == (
        _normalized_online_text_bytes(expected)
    )


def source_identity_key(source: dict[str, Any]) -> tuple[str, str]:
    source_type = str(source.get("type") or "")
    locator = str(source.get("locator") or "")
    if source_type == "github_release":
        locator = locator.casefold()
    return source_type, locator


def without_managed_fields(source: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if key not in GITHUB_MANAGED_FIELDS}


def normalize_online_sources_for_manual_save(
    raw_sources: Any,
    current_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_sources, list):
        raise ValueError("sources must be an array")
    if len(raw_sources) > 300:
        raise ValueError("too many online sources")

    current_by_id = {source["id"]: source for source in current_sources}
    current_by_key = {source_identity_key(source): source for source in current_sources}
    occupied_ids = set(current_by_id)
    candidate_sources: list[dict[str, Any]] = []

    for index, raw_source in enumerate(raw_sources):
        if not isinstance(raw_source, dict):
            raise ValueError(f"sources[{index}] must be an object")
        raw_id = str(raw_source.get("id") or "").strip()
        current = current_by_id.get(raw_id)
        managed_presence = [field in raw_source for field in GITHUB_MANAGED_FIELDS]
        if any(managed_presence) and not all(managed_presence):
            raise ValueError(
                f"github_star_managed_fields_readonly: sources[{index}] has partial managed fields"
            )

        if current is not None:
            if current.get("managed_by") == "github_stars":
                for key, value in raw_source.items():
                    if key in current and value != current[key]:
                        raise ValueError(
                            f"github_star_managed_fields_readonly: sources[{index}] managed source was modified"
                        )
            if current.get("managed_by") != "github_stars" and any(managed_presence):
                raise ValueError(
                    f"github_star_managed_fields_readonly: sources[{index}] cannot become managed"
                )
            incoming = normalize_online_source_record(raw_source, index, existing=True)
        else:
            if any(managed_presence):
                raise ValueError(
                    f"github_star_managed_fields_readonly: sources[{index}] cannot create managed fields"
                )
            incoming = normalize_online_source_record(
                raw_source,
                index,
                used_ids=occupied_ids,
            )
            if incoming is None:
                continue
            matching_current = current_by_key.get(source_identity_key(incoming))
            if matching_current is not None:
                if raw_id and raw_id != matching_current["id"]:
                    raise ValueError(
                        f"online_source_id_migration_required: sources[{index}] must preserve its existing id"
                    )
                source_with_existing_id = dict(raw_source)
                source_with_existing_id["id"] = matching_current["id"]
                incoming = normalize_online_source_record(
                    source_with_existing_id,
                    index,
                    existing=True,
                )
                current = matching_current
            elif incoming["id"] in current_by_id:
                raise ValueError(
                    f"online_source_id_conflict: sources[{index}].id is occupied by another source"
                )

        if incoming is None:
            continue
        if current is not None and current.get("managed_by") == "github_stars":
            if without_managed_fields(incoming) != without_managed_fields(current):
                raise ValueError(
                    f"github_star_managed_fields_readonly: sources[{index}] managed source was modified"
                )
            if all(managed_presence) and any(
                raw_source.get(field) != current.get(field) for field in GITHUB_MANAGED_FIELDS
            ):
                raise ValueError(
                    f"github_star_managed_fields_readonly: sources[{index}] managed fields were modified"
                )
            incoming = dict(current)

        candidate_sources.append(incoming)
        occupied_ids.add(incoming["id"])

    candidate_sources = normalize_online_sources(candidate_sources, existing=True)
    candidate_ids = {source["id"] for source in candidate_sources}
    missing_managed_ids = {
        source["id"]
        for source in current_sources
        if source.get("managed_by") == "github_stars" and source["id"] not in candidate_ids
    }
    if missing_managed_ids:
        raise ValueError(
            "github_star_managed_fields_readonly: managed sources cannot be deleted"
        )
    return candidate_sources


def _read_online_json_config(root_dir: Path) -> dict[str, Any]:
    config_path, _ = ensure_public_online_paths(root_dir)
    if not config_path.exists():
        return build_online_config([], updated_at=utc_timestamp())
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    return validate_online_config_schema(raw_config, existing=True)


def prepare_manual_online_config(
    root_dir: Path,
    payload: Any,
    *,
    current_config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], bool]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    current_config = current_config or _read_online_json_config(root_dir)
    current_sources = current_config["sources"]
    current_binding = current_config.get("github_star_sync")

    if "github_star_sync" in payload:
        requested_binding = normalize_github_star_sync(payload.get("github_star_sync"))
        if requested_binding != current_binding:
            raise ValueError(
                "github_star_managed_fields_readonly: github_star_sync cannot be changed by ordinary save"
            )
    for key, value in payload.items():
        if key in {"sources", "github_star_sync"}:
            continue
        check_public_payload_safe(value, f"payload.{key}")

    raw_sources = payload.get("sources")
    sources = normalize_online_sources_for_manual_save(raw_sources, current_sources)
    candidate_with_old_timestamp = build_online_config(
        sources,
        updated_at=current_config.get("updated_at") or utc_timestamp(),
        github_star_sync=current_binding,
    )
    validate_online_config_schema(candidate_with_old_timestamp, existing=True)
    if protected_online_config_projection(candidate_with_old_timestamp) != protected_online_config_projection(
        {"sources": current_sources, "github_star_sync": current_binding}
    ):
        raise ValueError(
            "github_star_managed_fields_readonly: protected GitHub star projection changed"
        )

    existing_count = len(current_sources)
    new_count = len(sources)
    confirm_bulk_delete = payload.get("confirm_bulk_delete") is True
    if existing_count >= 3 and new_count * 2 < existing_count and not confirm_bulk_delete:
        raise ValueError(
            "online_sources_bulk_delete_blocked: "
            f"本次写入会把 {existing_count} 个线上信源删到 {new_count} 个，已阻止；"
            "如确实要批量删除，请带 confirm_bulk_delete"
        )
    config_changed = online_config_digest(candidate_with_old_timestamp) != online_config_digest(
        current_config
    )
    config = (
        build_online_config(sources, github_star_sync=current_binding)
        if config_changed
        else current_config
    )
    return current_config, config, sources, config_changed


def _online_write_result(
    config: dict[str, Any],
    sources: list[dict[str, Any]],
    written_feeds: list[dict[str, Any]],
    *,
    config_changed: bool,
) -> dict[str, Any]:
    digest = online_config_digest(config)
    return {
        "ok": True,
        "path": str(ONLINE_CONFIG_FILENAME).replace("\\", "/"),
        "opml_path": str(ONLINE_OPML_FILENAME).replace("\\", "/"),
        "source_count": len(sources),
        "enabled_source_count": sum(1 for source in sources if source.get("enabled") is not False),
        "opml_feed_count": len(written_feeds),
        "base_config_digest": digest,
        "etag": online_config_etag(digest),
        "config_changed": config_changed,
        "config": config,
        "sources": sources,
    }


def write_online_source_config(root_dir: Path, payload: Any) -> dict[str, Any]:
    config_path, _ = ensure_public_online_paths(root_dir)
    _current, config, sources, config_changed = prepare_manual_online_config(root_dir, payload)
    if config_changed or not config_path.exists() or not online_opml_path(root_dir).exists():
        written_feeds = write_online_opml(root_dir, sources)
        write_json_atomic(config_path, config)
    else:
        written_feeds = [
            source
            for source in sources
            if source["type"] == "rss" and source.get("enabled") is not False
        ]
    return _online_write_result(
        config,
        sources,
        written_feeds,
        config_changed=config_changed,
    )


def git_run(root_dir: Path, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root_dir),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def git_checked(root_dir: Path, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    completed = git_run(root_dir, args, timeout=timeout)
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "git command failed").strip()
        raise RuntimeError(message)
    return completed


def git_name_list(root_dir: Path, args: list[str]) -> list[str]:
    completed = git_checked(root_dir, args)
    return [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]


def git_nul_name_list(root_dir: Path, args: list[str]) -> list[str]:
    completed = git_checked(root_dir, args)
    return [path.replace("\\", "/") for path in completed.stdout.split("\0") if path]


def operation_manifest_path(root_dir: Path) -> Path:
    raw_path = git_checked(
        root_dir,
        ["rev-parse", "--git-path", ONLINE_OPERATION_MANIFEST_NAME],
    ).stdout.strip()
    if not raw_path:
        raise _online_error("online_sources_preflight_failed", 409)
    path = Path(raw_path)
    return (path if path.is_absolute() else root_dir / path).resolve()


def _validate_operation_manifest(raw_manifest: Any) -> dict[str, Any]:
    if not isinstance(raw_manifest, dict):
        raise _online_error("online_sources_recovery_mismatch", 409)
    required_keys = {
        "schema_version",
        "operation_id",
        "operation_kind",
        "phase",
        "created_at",
        "pre_head",
        "branch",
        "remote_name",
        "remote_ref",
        "fetch_url_digest",
        "push_url_digest",
        "files",
        "preview_hash",
        "base_config_digest",
        "operation_commit_oid",
        "stable_patch_id",
        "commit_trailer",
        "stash",
    }
    if set(raw_manifest) != required_keys:
        raise _online_error("online_sources_recovery_mismatch", 409)
    if raw_manifest.get("schema_version") != ONLINE_OPERATION_SCHEMA_VERSION:
        raise _online_error("online_sources_recovery_mismatch", 409)
    operation_id = raw_manifest.get("operation_id")
    if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", operation_id):
        raise _online_error("online_sources_recovery_mismatch", 409)
    if raw_manifest.get("operation_kind") not in ONLINE_OPERATION_KINDS:
        raise _online_error("online_sources_recovery_mismatch", 409)
    if raw_manifest.get("phase") not in ONLINE_OPERATION_PHASES:
        raise _online_error("online_sources_recovery_mismatch", 409)
    if not isinstance(raw_manifest.get("created_at"), str):
        raise _online_error("online_sources_recovery_mismatch", 409)
    if not re.fullmatch(r"[0-9a-f]{40,64}", str(raw_manifest.get("pre_head") or "")):
        raise _online_error("online_sources_recovery_mismatch", 409)
    if raw_manifest.get("branch") != "master":
        raise _online_error("online_sources_recovery_mismatch", 409)
    if not isinstance(raw_manifest.get("remote_name"), str) or not raw_manifest["remote_name"]:
        raise _online_error("online_sources_recovery_mismatch", 409)
    if raw_manifest.get("remote_ref") != "refs/heads/master":
        raise _online_error("online_sources_recovery_mismatch", 409)
    for key in ("fetch_url_digest", "push_url_digest", "base_config_digest"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(raw_manifest.get(key) or "")):
            raise _online_error("online_sources_recovery_mismatch", 409)
    preview_hash = str(raw_manifest.get("preview_hash") or "")
    if preview_hash and not re.fullmatch(r"[0-9a-f]{64}", preview_hash):
        raise _online_error("online_sources_recovery_mismatch", 409)
    for key in ("operation_commit_oid", "stable_patch_id"):
        value = str(raw_manifest.get(key) or "")
        if value and not re.fullmatch(r"[0-9a-f]{40,64}", value):
            raise _online_error("online_sources_recovery_mismatch", 409)
    if raw_manifest.get("commit_trailer") != f"AI-News-Radar-Operation: {operation_id}":
        raise _online_error("online_sources_recovery_mismatch", 409)

    files = raw_manifest.get("files")
    allowed_paths = {
        str(ONLINE_CONFIG_FILENAME).replace("\\", "/"),
        str(ONLINE_OPML_FILENAME).replace("\\", "/"),
    }
    if not isinstance(files, dict) or set(files) != allowed_paths:
        raise _online_error("online_sources_recovery_mismatch", 409)
    for proof in files.values():
        if not isinstance(proof, dict) or set(proof) != {"before_sha256", "after_sha256"}:
            raise _online_error("online_sources_recovery_mismatch", 409)
        if any(
            not re.fullmatch(r"[0-9a-f]{64}", str(proof.get(key) or ""))
            for key in ("before_sha256", "after_sha256")
        ):
            raise _online_error("online_sources_recovery_mismatch", 409)

    stash = raw_manifest.get("stash")
    if not isinstance(stash, dict) or set(stash) != {"message", "oid", "paths"}:
        raise _online_error("online_sources_recovery_mismatch", 409)
    if stash.get("message") != f"ai-news-radar:{operation_id}":
        raise _online_error("online_sources_recovery_mismatch", 409)
    if not isinstance(stash.get("oid"), str) or not isinstance(stash.get("paths"), list):
        raise _online_error("online_sources_recovery_mismatch", 409)
    if stash["oid"] and not re.fullmatch(r"[0-9a-f]{40,64}", stash["oid"]):
        raise _online_error("online_sources_recovery_mismatch", 409)
    if stash["oid"] and not stash["paths"]:
        raise _online_error("online_sources_recovery_mismatch", 409)
    seen_stash_paths: set[str] = set()
    for proof in stash["paths"]:
        if not isinstance(proof, dict) or set(proof) != {
            "path",
            "before_exists",
            "before_sha256",
        }:
            raise _online_error("online_sources_recovery_mismatch", 409)
        path = proof.get("path")
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or "\0" in path
            or path.startswith("/")
            or re.match(r"^[A-Za-z]:", path)
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or path.split("/", 1)[0] == ".git"
            or path in allowed_paths
            or path in seen_stash_paths
            or not isinstance(proof.get("before_exists"), bool)
            or not re.fullmatch(r"[0-9a-f]{64}", str(proof.get("before_sha256") or ""))
        ):
            raise _online_error("online_sources_recovery_mismatch", 409)
        seen_stash_paths.add(path)
    return json.loads(json.dumps(raw_manifest, ensure_ascii=False))


def operation_manifest_digest(manifest: dict[str, Any]) -> str:
    normalized = _validate_operation_manifest(manifest)
    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(canonical)


def write_operation_manifest(root_dir: Path, manifest: dict[str, Any]) -> str:
    normalized = _validate_operation_manifest(manifest)
    path = operation_manifest_path(root_dir)
    atomic_replace_bytes(path, render_json_bytes(normalized))
    return operation_manifest_digest(normalized)


def read_operation_manifest(root_dir: Path) -> dict[str, Any] | None:
    path = operation_manifest_path(root_dir)
    if not path.exists():
        return None
    try:
        raw_manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _online_error("online_sources_recovery_mismatch", 409) from exc
    return _validate_operation_manifest(raw_manifest)


def public_operation_recovery(
    manifest: dict[str, Any] | None,
    *,
    actual_phase: str,
    outcome: str,
    recovery_pending: bool,
    allowed_actions: list[str],
) -> dict[str, Any]:
    if manifest is None:
        raise _online_error("online_sources_recovery_mismatch", 409)
    normalized = _validate_operation_manifest(manifest)
    return {
        "operation_id": normalized["operation_id"],
        "manifest_digest": operation_manifest_digest(normalized),
        "operation_kind": normalized["operation_kind"],
        "phase": actual_phase,
        "outcome": outcome,
        "recovery_pending": recovery_pending,
        "allowed_actions": list(allowed_actions),
        "created_at": normalized["created_at"],
    }


def _preflight_error(reason: str) -> OnlineSourcesError:
    return _online_error("online_sources_preflight_failed", 409, {"reason": reason})


def _git_path(root_dir: Path, name: str) -> Path:
    raw_path = git_checked(root_dir, ["rev-parse", "--git-path", name]).stdout.strip()
    path = Path(raw_path)
    return (path if path.is_absolute() else root_dir / path).resolve()


def _active_git_operation_paths(root_dir: Path) -> list[Path]:
    return [
        path
        for path in (
            _git_path(root_dir, "rebase-merge"),
            _git_path(root_dir, "rebase-apply"),
            _git_path(root_dir, "MERGE_HEAD"),
            _git_path(root_dir, "CHERRY_PICK_HEAD"),
        )
        if path.exists()
    ]


def _active_foreign_git_operation_paths(root_dir: Path) -> list[Path]:
    return [
        path
        for path in (
            _git_path(root_dir, "MERGE_HEAD"),
            _git_path(root_dir, "CHERRY_PICK_HEAD"),
        )
        if path.exists()
    ]


def _canonical_git_remote_url(root_dir: Path, raw_url: str) -> str:
    value = raw_url.strip()
    if not value:
        raise _preflight_error("remote_url_missing")
    if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("/", "\\")):
        path = str(Path(value).resolve()).replace("\\", "/").removesuffix(".git")
        return "file:" + (path.casefold() if os.name == "nt" else path)
    if "://" not in value:
        scp_match = re.fullmatch(
            r"(?:(?P<user>[^@/:]+)@)?(?P<host>[^/:]+):(?P<path>.+)",
            value,
        )
        if scp_match:
            user = scp_match.group("user") or ""
            host = scp_match.group("host").casefold()
            path = scp_match.group("path").strip("/").removesuffix(".git")
            userinfo = f"{user}@" if user else ""
            return f"remote:ssh://{userinfo}{host}/{path}"
        if "@" in value:
            raise _preflight_error("remote_url_invalid")
        path = str((root_dir / value).resolve()).replace("\\", "/").removesuffix(".git")
        return "file:" + (path.casefold() if os.name == "nt" else path)
    parsed = urlparse(value)
    scheme = parsed.scheme.casefold()
    if parsed.password is not None:
        raise _preflight_error("remote_url_invalid")
    host = (parsed.hostname or "").casefold()
    path = parsed.path.strip("/").removesuffix(".git")
    try:
        port = parsed.port
    except ValueError as exc:
        raise _preflight_error("remote_url_invalid") from exc
    suffix = f"?{parsed.query}" if parsed.query else ""
    if parsed.fragment:
        suffix += f"#{parsed.fragment}"
    if scheme == "file":
        if parsed.username:
            raise _preflight_error("remote_url_invalid")
        if host and host != "localhost":
            authority = f"{host}:{port}" if port is not None else host
            if not path:
                raise _preflight_error("remote_url_invalid")
            return f"file://{authority}/{path}{suffix}"
        local_path = parsed.path
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", local_path):
            local_path = local_path[1:]
        normalized = str(Path(local_path).resolve()).replace("\\", "/").removesuffix(".git")
        normalized = normalized.casefold() if os.name == "nt" else normalized
        return f"file:{normalized}{suffix}"
    if not scheme or not host or not path:
        raise _preflight_error("remote_url_invalid")
    authority = f"{host}:{port}" if port is not None else host
    userinfo = f"{parsed.username}@" if parsed.username else ""
    return f"remote:{scheme}://{userinfo}{authority}/{path}{suffix}"


def _git_config_value(root_dir: Path, key: str) -> str:
    completed = git_run(root_dir, ["config", "--get", key])
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _configured_remote_target(root_dir: Path, branch: str) -> dict[str, str]:
    remote_name = _git_config_value(root_dir, f"branch.{branch}.remote")
    remote_ref = _git_config_value(root_dir, f"branch.{branch}.merge")
    if not remote_name or remote_name == "." or remote_ref != "refs/heads/master":
        raise _preflight_error("upstream_invalid")
    push_remote = (
        _git_config_value(root_dir, f"branch.{branch}.pushRemote")
        or _git_config_value(root_dir, "remote.pushDefault")
        or remote_name
    )
    if push_remote != remote_name:
        raise _preflight_error("remote_name_mismatch")
    fetch_urls = [
        line.strip()
        for line in git_checked(
            root_dir,
            ["remote", "get-url", "--all", remote_name],
        ).stdout.splitlines()
        if line.strip()
    ]
    push_urls = [
        line.strip()
        for line in git_checked(
            root_dir,
            ["remote", "get-url", "--push", "--all", push_remote],
        ).stdout.splitlines()
        if line.strip()
    ]
    if len(fetch_urls) != 1 or len(push_urls) != 1:
        raise _preflight_error("remote_url_ambiguous")
    fetch_url = fetch_urls[0]
    push_url = push_urls[0]
    canonical_fetch_url = _canonical_git_remote_url(root_dir, fetch_url)
    canonical_push_url = _canonical_git_remote_url(root_dir, push_url)
    if canonical_fetch_url != canonical_push_url:
        raise _preflight_error("remote_url_mismatch")
    tracking_ref = git_checked(
        root_dir,
        ["rev-parse", "--symbolic-full-name", f"{branch}@{{upstream}}"],
    ).stdout.strip()
    expected_tracking_ref = f"refs/remotes/{remote_name}/{remote_ref.removeprefix('refs/heads/')}"
    if (
        tracking_ref != expected_tracking_ref
        or git_run(root_dir, ["check-ref-format", tracking_ref]).returncode != 0
    ):
        raise _preflight_error("upstream_tracking_ref_invalid")
    return {
        "branch": branch,
        "remote_name": remote_name,
        "remote_ref": remote_ref,
        "fetch_url": fetch_url,
        "push_url": push_url,
        "tracking_ref": tracking_ref,
        "fetch_url_digest": sha256_bytes(canonical_fetch_url.encode("utf-8")),
        "push_url_digest": sha256_bytes(canonical_push_url.encode("utf-8")),
    }


def _fetch_remote_ref_oid(
    root_dir: Path,
    target: dict[str, str],
    *,
    operation_token: str,
) -> str:
    token_digest = sha256_bytes(operation_token.encode("utf-8"))
    private_ref = f"refs/ai-news-radar/fetch/{token_digest}"
    git_checked(
        root_dir,
        [
            "fetch",
            "--no-write-fetch-head",
            "--",
            target["fetch_url"],
            f"{target['remote_ref']}:{target['tracking_ref']}",
            f"+{target['remote_ref']}:{private_ref}",
        ],
        timeout=120,
    )
    fetched_oid = git_checked(
        root_dir,
        ["rev-parse", "--verify", f"{private_ref}^{{commit}}"],
    ).stdout.strip()
    git_checked(
        root_dir,
        ["update-ref", "-d", private_ref, fetched_oid],
    )
    return fetched_oid


def _assert_remote_data_only_advance(root_dir: Path, base_oid: str, fetched_oid: str) -> None:
    if git_run(root_dir, ["merge-base", "--is-ancestor", base_oid, fetched_oid]).returncode != 0:
        raise _preflight_error("remote_history_diverged")
    commits = [
        line.strip()
        for line in git_checked(
            root_dir,
            ["rev-list", "--reverse", "--topo-order", f"{base_oid}..{fetched_oid}"],
        ).stdout.splitlines()
        if line.strip()
    ]
    previous_oid = base_oid
    for commit_oid in commits:
        parents = git_checked(
            root_dir,
            ["show", "-s", "--format=%P", commit_oid],
        ).stdout.split()
        if parents != [previous_oid]:
            raise _preflight_error("remote_non_data_changes")
        changed = git_nul_name_list(
            root_dir,
            ["diff-tree", "--no-commit-id", "--name-only", "-r", "-z", commit_oid],
        )
        if any(not path.startswith("data/") for path in changed):
            raise _preflight_error("remote_non_data_changes")
        previous_oid = commit_oid
    if previous_oid != fetched_oid:
        raise _preflight_error("remote_history_diverged")
    changed = git_nul_name_list(
        root_dir,
        ["diff", "--name-only", "-z", base_oid, fetched_oid, "--"],
    )
    if any(not path.startswith("data/") for path in changed):
        raise _preflight_error("remote_non_data_changes")
    for path in _allowed_online_paths():
        if _git_blob_oid(root_dir, base_oid, path) != _git_blob_oid(root_dir, fetched_oid, path):
            raise _preflight_error("remote_online_files_changed")


def _git_blob_oid(root_dir: Path, revision: str, path: str) -> str | None:
    completed = git_run(root_dir, ["rev-parse", "--verify", f"{revision}:{path}"])
    return completed.stdout.strip() if completed.returncode == 0 else None


def _assert_git_quiet(root_dir: Path, args: list[str], reason: str) -> None:
    completed = git_run(root_dir, args)
    if completed.returncode == 1:
        raise _preflight_error(reason)
    if completed.returncode != 0:
        raise _preflight_error("git_state_unreadable")


def fresh_git_preflight(root_dir: Path) -> dict[str, str]:
    root = root_dir.resolve()
    try:
        top = Path(git_checked(root, ["rev-parse", "--show-toplevel"]).stdout.strip()).resolve()
        if top != root:
            raise _preflight_error("repo_root_required")
        branch = git_checked(root, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        if branch != "master":
            raise _preflight_error("master_branch_required")
        pre_head = git_checked(root, ["rev-parse", "--verify", "HEAD"]).stdout.strip()

        if git_name_list(root, ["diff", "--cached", "--name-only"]):
            raise _preflight_error("index_not_clean")
        allowed_paths = [
            str(ONLINE_CONFIG_FILENAME).replace("\\", "/"),
            str(ONLINE_OPML_FILENAME).replace("\\", "/"),
        ]
        _assert_git_quiet(
            root,
            ["diff", "--quiet", "--", *allowed_paths],
            "online_files_worktree_dirty",
        )
        _assert_git_quiet(
            root,
            ["diff", "--cached", "--quiet", "--", *allowed_paths],
            "online_files_index_dirty",
        )
        if _active_git_operation_paths(root):
            raise _preflight_error("git_operation_in_progress")
        if operation_manifest_path(root).exists():
            raise _online_error("online_sources_recovery_pending", 409)

        target = _configured_remote_target(root, branch)
        fetched_oid = _fetch_remote_ref_oid(
            root,
            target,
            operation_token=uuid.uuid4().hex,
        )
        _assert_remote_data_only_advance(root, pre_head, fetched_oid)
        _assert_head(root, pre_head, "head_changed_during_fetch")
        if git_name_list(root, ["diff", "--cached", "--name-only"]):
            raise _preflight_error("index_changed_during_fetch")
        _assert_git_quiet(
            root,
            ["diff", "--quiet", "--", *allowed_paths],
            "online_files_changed_during_fetch",
        )
        _assert_git_quiet(
            root,
            ["diff", "--cached", "--quiet", "--", *allowed_paths],
            "online_files_index_changed_during_fetch",
        )
    except OnlineSourcesError:
        raise
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        raise _preflight_error("git_preflight_unavailable") from exc

    return {
        "pre_head": pre_head,
        "branch": branch,
        "remote_name": target["remote_name"],
        "remote_ref": target["remote_ref"],
        "fetched_oid": fetched_oid,
        "fetch_url": target["fetch_url"],
        "push_url": target["push_url"],
        "fetch_url_digest": target["fetch_url_digest"],
        "push_url_digest": target["push_url_digest"],
    }


def _local_git_target(root_dir: Path) -> dict[str, str]:
    root = root_dir.resolve()
    try:
        top = Path(git_checked(root, ["rev-parse", "--show-toplevel"]).stdout.strip()).resolve()
        branch = git_checked(root, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        pre_head = git_checked(root, ["rev-parse", "--verify", "HEAD"]).stdout.strip()
        if top != root or branch != "master":
            raise _preflight_error("master_repo_root_required")
        target = _configured_remote_target(root, branch)
    except OnlineSourcesError:
        raise
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        raise _preflight_error("git_preflight_unavailable") from exc
    return {
        "pre_head": pre_head,
        **target,
    }


def new_operation_manifest(
    *,
    operation_kind: str,
    target: dict[str, str],
    before_hashes: dict[str, str],
    after_hashes: dict[str, str],
    preview_hash: str = "",
    base_config_digest: str,
) -> dict[str, Any]:
    operation_id = uuid.uuid4().hex
    allowed_paths = (
        str(ONLINE_CONFIG_FILENAME).replace("\\", "/"),
        str(ONLINE_OPML_FILENAME).replace("\\", "/"),
    )
    return {
        "schema_version": ONLINE_OPERATION_SCHEMA_VERSION,
        "operation_id": operation_id,
        "operation_kind": operation_kind,
        "phase": "prepared",
        "created_at": utc_timestamp(),
        "pre_head": target["pre_head"],
        "branch": target["branch"],
        "remote_name": target["remote_name"],
        "remote_ref": target["remote_ref"],
        "fetch_url_digest": target["fetch_url_digest"],
        "push_url_digest": target["push_url_digest"],
        "files": {
            path: {
                "before_sha256": before_hashes[path],
                "after_sha256": after_hashes[path],
            }
            for path in allowed_paths
        },
        "preview_hash": preview_hash,
        "base_config_digest": base_config_digest,
        "operation_commit_oid": "",
        "stable_patch_id": "",
        "commit_trailer": f"AI-News-Radar-Operation: {operation_id}",
        "stash": {
            "message": f"ai-news-radar:{operation_id}",
            "oid": "",
            "paths": [],
        },
    }


def update_operation_manifest(
    root_dir: Path,
    manifest: dict[str, Any],
    **changes: Any,
) -> tuple[dict[str, Any], str]:
    updated = {**manifest, **changes}
    digest = write_operation_manifest(root_dir, updated)
    return updated, digest


def delete_operation_manifest(
    root_dir: Path,
    *,
    expected_digest: str | None = None,
) -> None:
    path = operation_manifest_path(root_dir)
    if not path.exists():
        return
    if expected_digest is not None:
        current = read_operation_manifest(root_dir)
        if current is None or operation_manifest_digest(current) != expected_digest:
            raise _online_error("online_sources_recovery_mismatch", 409)
    path.unlink()


def save_online_source_config_transaction(
    root_dir: Path,
    payload: Any,
    *,
    if_match: Any,
) -> dict[str, Any]:
    with online_sources_guard():
        recovery = audit_online_source_operation(root_dir)
        if recovery is not None:
            raise _online_error("online_sources_recovery_pending", 409)
        current_config = _read_online_json_config(root_dir)
        current_digest = online_config_digest(current_config)
        require_online_config_match(if_match, current_digest)
        _current, candidate, sources, config_changed = prepare_manual_online_config(
            root_dir,
            payload,
            current_config=current_config,
        )
        written_feeds = [
            source
            for source in sources
            if source["type"] == "rss" and source.get("enabled") is not False
        ]
        if not config_changed:
            return _online_write_result(
                current_config,
                current_config["sources"],
                written_feeds,
                config_changed=False,
            )

        config_path, opml_path = ensure_public_online_paths(root_dir)
        config_content = render_json_bytes(candidate)
        opml_content, written_feeds = render_online_opml_bytes(sources)
        path_keys = {
            config_path: str(ONLINE_CONFIG_FILENAME).replace("\\", "/"),
            opml_path: str(ONLINE_OPML_FILENAME).replace("\\", "/"),
        }
        before_hashes = {key: sha256_file(path) for path, key in path_keys.items()}
        after_hashes = {
            path_keys[config_path]: sha256_bytes(config_content),
            path_keys[opml_path]: sha256_bytes(opml_content),
        }
        target = _local_git_target(root_dir)
        manifest = new_operation_manifest(
            operation_kind="manual_save",
            target=target,
            before_hashes=before_hashes,
            after_hashes=after_hashes,
            base_config_digest=current_digest,
        )
        manifest_digest = write_operation_manifest(root_dir, manifest)
        try:
            if any(sha256_file(path) != before_hashes[key] for path, key in path_keys.items()):
                raise _online_error("online_sources_config_stale", 409)
            atomic_replace_bytes(opml_path, opml_content)
            manifest, manifest_digest = update_operation_manifest(
                root_dir,
                manifest,
                phase="write_incomplete",
            )
            if sha256_file(config_path) != before_hashes[path_keys[config_path]]:
                raise _online_error("online_sources_config_stale", 409)
            atomic_replace_bytes(config_path, config_content)
            manifest, manifest_digest = update_operation_manifest(
                root_dir,
                manifest,
                phase="files_written",
            )
            if sha256_file(config_path) != after_hashes[path_keys[config_path]] or sha256_file(
                opml_path
            ) != after_hashes[path_keys[opml_path]]:
                raise OSError("online source file verification failed")
        except Exception as exc:
            config_is_original = sha256_file(config_path) == before_hashes[path_keys[config_path]]
            if config_is_original:
                try:
                    repair_content, _ = render_online_opml_bytes(current_config["sources"])
                    atomic_replace_bytes(opml_path, repair_content)
                    if sha256_file(opml_path) != before_hashes[path_keys[opml_path]]:
                        raise OSError("derived OPML repair verification failed")
                    delete_operation_manifest(root_dir)
                except Exception as repair_exc:
                    raise _online_error(
                        "online_sources_write_failed",
                        500,
                        {"recovery_pending": True},
                    ) from repair_exc
                if isinstance(exc, OnlineSourcesError) and exc.code == "online_sources_config_stale":
                    raise exc
                raise _online_error("online_sources_write_failed", 500) from exc
            try:
                update_operation_manifest(root_dir, manifest, phase="write_incomplete")
            except Exception:
                pass
            raise _online_error(
                "online_sources_write_failed",
                500,
                {"recovery_pending": True},
            ) from exc

        delete_operation_manifest(root_dir, expected_digest=manifest_digest)
        return _online_write_result(
            candidate,
            sources,
            written_feeds,
            config_changed=True,
        )


def _allowed_online_paths() -> list[str]:
    return [
        str(ONLINE_CONFIG_FILENAME).replace("\\", "/"),
        str(ONLINE_OPML_FILENAME).replace("\\", "/"),
    ]


def _git_blob_bytes(root_dir: Path, revision: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=str(root_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return b""
    return completed.stdout


def _git_head(root_dir: Path) -> str:
    return git_checked(root_dir, ["rev-parse", "--verify", "HEAD"]).stdout.strip()


def _assert_head(root_dir: Path, expected: str, reason: str = "head_changed") -> None:
    if _git_head(root_dir) != expected:
        raise _preflight_error(reason)


def _assert_operation_git_context(root_dir: Path, manifest: dict[str, Any]) -> None:
    if _active_git_operation_paths(root_dir):
        raise _online_error("online_sources_recovery_mismatch", 409)
    branch = git_checked(root_dir, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch != manifest["branch"]:
        raise _online_error("online_sources_recovery_mismatch", 409)


def _assert_online_file_hashes(
    root_dir: Path,
    proofs: dict[str, dict[str, str]],
    key: str,
) -> None:
    for path, proof in proofs.items():
        if _online_file_sha256(root_dir / path) != proof[key]:
            raise _online_error("online_sources_recovery_mismatch", 409)


def _operation_file_states(
    root_dir: Path,
    manifest: dict[str, Any],
) -> list[str]:
    states: list[str] = []
    for path, proof in manifest["files"].items():
        actual = _online_file_sha256(root_dir / path)
        if actual == proof["before_sha256"]:
            states.append("before")
        elif actual == proof["after_sha256"]:
            states.append("after")
        else:
            states.append("other")
    return states


def _safe_write_rollback_states(
    root_dir: Path,
    manifest: dict[str, Any],
    manifest_digest: str,
    *,
    allow_trusted_staged: bool = False,
) -> list[str] | None:
    try:
        current = read_operation_manifest(root_dir)
        if current is None or operation_manifest_digest(current) != manifest_digest:
            return None
        if manifest["operation_commit_oid"] or manifest["stable_patch_id"]:
            return None
        _assert_operation_git_context(root_dir, manifest)
        if _git_head(root_dir) != manifest["pre_head"]:
            return None
        staged = set(git_name_list(root_dir, ["diff", "--cached", "--name-only"]))
        if staged:
            if not allow_trusted_staged or staged != _manifest_changed_paths(manifest):
                return None
            for path, proof in manifest["files"].items():
                if path in staged and _online_content_sha256(_git_blob_bytes(root_dir, "", path)) != proof[
                    "after_sha256"
                ]:
                    return None
        states = _operation_file_states(root_dir, manifest)
        return states if "other" not in states else None
    except (OnlineSourcesError, OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        return None


def _manifest_changed_paths(manifest: dict[str, Any]) -> set[str]:
    return {
        path
        for path, proof in manifest["files"].items()
        if proof["before_sha256"] != proof["after_sha256"]
    }


def _stable_patch_id(root_dir: Path, commit_oid: str) -> str:
    patch = git_checked(
        root_dir,
        ["show", "--pretty=format:", "--binary", commit_oid],
    ).stdout
    completed = subprocess.run(
        ["git", "patch-id", "--stable"],
        cwd=str(root_dir),
        input=patch,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise _online_error("online_sources_recovery_mismatch", 409)
    patch_id = completed.stdout.split()[0]
    if not re.fullmatch(r"[0-9a-f]{40,64}", patch_id):
        raise _online_error("online_sources_recovery_mismatch", 409)
    return patch_id


def _verify_operation_commit(
    root_dir: Path,
    manifest: dict[str, Any],
    commit_oid: str,
    *,
    require_pre_head_parent: bool,
) -> str:
    normalized = _validate_operation_manifest(manifest)
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit_oid):
        raise _online_error("online_sources_recovery_mismatch", 409)
    parents = git_checked(root_dir, ["show", "-s", "--format=%P", commit_oid]).stdout.split()
    if len(parents) != 1:
        raise _online_error("online_sources_recovery_mismatch", 409)
    if require_pre_head_parent and parents[0] != normalized["pre_head"]:
        raise _online_error("online_sources_recovery_mismatch", 409)
    changed = set(
        git_name_list(
            root_dir,
            ["diff-tree", "--no-commit-id", "--name-only", "-r", commit_oid],
        )
    )
    if changed != _manifest_changed_paths(normalized):
        raise _online_error("online_sources_recovery_mismatch", 409)
    message_lines = git_checked(root_dir, ["show", "-s", "--format=%B", commit_oid]).stdout.splitlines()
    if message_lines.count(normalized["commit_trailer"]) != 1:
        raise _online_error("online_sources_recovery_mismatch", 409)
    for path, proof in normalized["files"].items():
        if _online_content_sha256(_git_blob_bytes(root_dir, commit_oid, path)) != proof[
            "after_sha256"
        ]:
            raise _online_error("online_sources_recovery_mismatch", 409)
    return _stable_patch_id(root_dir, commit_oid)


def _manual_sync_git_preflight(root_dir: Path) -> dict[str, str]:
    root = root_dir.resolve()
    try:
        target = _local_git_target(root)
        if git_name_list(root, ["diff", "--cached", "--name-only"]):
            raise _preflight_error("index_not_clean")
        if _active_git_operation_paths(root):
            raise _preflight_error("git_operation_in_progress")
        if operation_manifest_path(root).exists():
            raise _online_error("online_sources_recovery_pending", 409)
        fetched_oid = _fetch_remote_ref_oid(
            root,
            target,
            operation_token=uuid.uuid4().hex,
        )
        _assert_remote_data_only_advance(root, target["pre_head"], fetched_oid)
        _assert_head(root, target["pre_head"], "head_changed_during_fetch")
        if git_name_list(root, ["diff", "--cached", "--name-only"]):
            raise _preflight_error("index_changed_during_fetch")
    except OnlineSourcesError:
        raise
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        raise _preflight_error("git_preflight_unavailable") from exc
    return {**target, "fetched_oid": fetched_oid}


def _online_paths_changed_from_head(root_dir: Path) -> bool:
    head = _git_head(root_dir)
    for path in _allowed_online_paths():
        tracked = _git_blob_oid(root_dir, head, path) is not None
        exists = (root_dir / path).exists()
        if tracked != exists:
            return True
        if tracked and git_run(root_dir, ["diff", "--quiet", "HEAD", "--", path]).returncode != 0:
            return True
    return False


def _operation_result(
    config: dict[str, Any],
    *,
    outcome: str,
    config_changed: bool,
    write_complete: bool,
    commit: str = "",
    pushed: bool = False,
    recovery_pending: bool = False,
    summary: dict[str, Any] | None = None,
    recovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    digest = online_config_digest(config)
    partial = outcome in {"saved_not_committed", "committed_not_pushed"} or recovery_pending
    result = {
        "ok": not partial,
        "outcome": outcome,
        "write_complete": write_complete,
        "config_changed": config_changed,
        "commit": commit,
        "pushed": pushed,
        "partial": partial,
        "recovery_pending": recovery_pending,
        "summary": dict(summary or {}),
        "base_config_digest": digest,
        "etag": online_config_etag(digest),
        "config": config,
        "sources": config["sources"],
    }
    if recovery is not None:
        result["recovery"] = recovery
    return result


def _manual_save_recovery(root_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    try:
        current_config = _read_online_json_config(root_dir)
        expected_opml, _ = render_online_opml_bytes(current_config["sources"])
        opml_path = online_opml_path(root_dir)
        if not opml_path.exists() or opml_path.read_bytes() != expected_opml:
            atomic_replace_bytes(opml_path, expected_opml)
        if opml_path.read_bytes() != expected_opml:
            raise OSError("derived OPML repair verification failed")
        delete_operation_manifest(root_dir)
        return None
    except Exception:
        return public_operation_recovery(
            manifest,
            actual_phase="write_incomplete",
            outcome="saved_not_committed",
            recovery_pending=True,
            allowed_actions=["repair_derived_file"],
        )


def _operation_commit_candidates(
    root_dir: Path,
    manifest: dict[str, Any],
) -> list[tuple[str, str]]:
    completed = git_run(
        root_dir,
        [
            "log",
            "--all",
            "--format=%H",
            "--fixed-strings",
            f"--grep={manifest['commit_trailer']}",
        ],
    )
    if completed.returncode != 0:
        raise _online_error("online_sources_recovery_mismatch", 409)
    candidates: list[tuple[str, str]] = []
    require_pre_head_parent = not bool(manifest.get("stable_patch_id"))
    reachable_oids = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    for oid in dict.fromkeys(reachable_oids):
        try:
            patch_id = _verify_operation_commit(
                root_dir,
                manifest,
                oid,
                require_pre_head_parent=require_pre_head_parent,
            )
        except (OnlineSourcesError, OSError, RuntimeError, subprocess.SubprocessError):
            continue
        expected_patch_id = manifest.get("stable_patch_id") or ""
        if expected_patch_id and patch_id != expected_patch_id:
            continue
        candidates.append((oid, patch_id))
    if candidates or not manifest.get("operation_commit_oid"):
        return candidates
    recorded_oid = manifest["operation_commit_oid"]
    try:
        patch_id = _verify_operation_commit(
            root_dir,
            manifest,
            recorded_oid,
            require_pre_head_parent=require_pre_head_parent,
        )
    except (OnlineSourcesError, OSError, RuntimeError, subprocess.SubprocessError):
        return []
    expected_patch_id = manifest.get("stable_patch_id") or ""
    if expected_patch_id and patch_id != expected_patch_id:
        return []
    candidates.append((recorded_oid, patch_id))
    return candidates


def _verified_operation_remote_target(
    root_dir: Path,
    manifest: dict[str, Any],
    *,
    require_master_checkout: bool = True,
) -> dict[str, str]:
    normalized = _validate_operation_manifest(manifest)
    root = root_dir.resolve()
    try:
        top = Path(git_checked(root, ["rev-parse", "--show-toplevel"]).stdout.strip()).resolve()
        if top != root:
            raise _preflight_error("repo_root_required")
        if require_master_checkout:
            branch = git_checked(root, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
            if branch != normalized["branch"]:
                raise _preflight_error("master_branch_required")
        target = _configured_remote_target(root, normalized["branch"])
    except (OnlineSourcesError, OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        raise _online_error("online_sources_recovery_mismatch", 409) from exc
    for key in ("branch", "remote_name", "remote_ref", "fetch_url_digest", "push_url_digest"):
        if target[key] != normalized[key]:
            raise _online_error("online_sources_recovery_mismatch", 409)
    return target


def _fetch_operation_remote(
    root_dir: Path,
    manifest: dict[str, Any],
    *,
    require_master_checkout: bool = True,
) -> str:
    target = _verified_operation_remote_target(
        root_dir,
        manifest,
        require_master_checkout=require_master_checkout,
    )
    return _fetch_remote_ref_oid(
        root_dir,
        target,
        operation_token=manifest["operation_id"],
    )


def _operation_remote_status(
    root_dir: Path,
    manifest: dict[str, Any],
    commit_oid: str,
) -> str:
    try:
        fetched_oid = _fetch_operation_remote(root_dir, manifest)
    except OnlineSourcesError:
        return "unsafe"
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        return "unknown"
    if git_run(root_dir, ["merge-base", "--is-ancestor", commit_oid, fetched_oid]).returncode == 0:
        return "pushed"
    try:
        _assert_remote_data_only_advance(root_dir, manifest["pre_head"], fetched_oid)
    except OnlineSourcesError:
        return "unsafe"
    return "retryable"


def _operation_commit_parent_oid(root_dir: Path, commit_oid: str) -> str:
    parents = git_checked(root_dir, ["show", "-s", "--format=%P", commit_oid]).stdout.split()
    if len(parents) != 1:
        raise _online_error("online_sources_recovery_mismatch", 409)
    return parents[0]


def _operation_commit_parent_is_trusted(
    root_dir: Path,
    manifest: dict[str, Any],
    operation_oid: str,
) -> bool:
    try:
        parent_oid = _operation_commit_parent_oid(root_dir, operation_oid)
        if parent_oid == manifest["pre_head"]:
            return True
        _assert_remote_data_only_advance(root_dir, manifest["pre_head"], parent_oid)
        fetched_oid = _fetch_operation_remote(root_dir, manifest)
        return (
            git_run(root_dir, ["merge-base", "--is-ancestor", parent_oid, fetched_oid]).returncode
            == 0
        )
    except (OnlineSourcesError, OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        return False


def _operation_remote_target_matches(root_dir: Path, manifest: dict[str, Any]) -> bool:
    try:
        _verified_operation_remote_target(root_dir, manifest)
    except OnlineSourcesError:
        return False
    return True


def _active_rebase_paths(root_dir: Path) -> list[Path]:
    return [
        path
        for path in (_git_path(root_dir, "rebase-merge"), _git_path(root_dir, "rebase-apply"))
        if path.exists()
    ]


def _read_rebase_state_value(rebase_dir: Path, name: str) -> str:
    path = rebase_dir / name
    if not path.is_file() or path.stat().st_size > 4096:
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _owned_operation_rebase_proof(
    root_dir: Path,
    manifest: dict[str, Any],
) -> tuple[Path, str] | None:
    if manifest["phase"] != "rebasing":
        return None
    operation_oid = manifest["operation_commit_oid"]
    stable_patch_id = manifest["stable_patch_id"]
    if not operation_oid or not stable_patch_id:
        return None
    rebase_paths = _active_rebase_paths(root_dir)
    if len(rebase_paths) != 1 or rebase_paths[0].name != "rebase-merge":
        return None
    rebase_dir = rebase_paths[0]
    orig_head = _read_rebase_state_value(rebase_dir, "orig-head")
    head_name = _read_rebase_state_value(rebase_dir, "head-name")
    onto = _read_rebase_state_value(rebase_dir, "onto")
    if (
        orig_head != operation_oid
        or head_name != "refs/heads/master"
        or not re.fullmatch(r"[0-9a-f]{40,64}", onto)
        or onto == manifest["pre_head"]
    ):
        return None
    try:
        patch_id = _verify_operation_commit(
            root_dir,
            manifest,
            operation_oid,
            require_pre_head_parent=False,
        )
        if patch_id != stable_patch_id:
            return None
        _assert_remote_data_only_advance(root_dir, manifest["pre_head"], onto)
        fetched_oid = _fetch_operation_remote(
            root_dir,
            manifest,
            require_master_checkout=False,
        )
        if git_run(root_dir, ["merge-base", "--is-ancestor", onto, fetched_oid]).returncode != 0:
            return None
    except (OnlineSourcesError, OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        return None
    return rebase_dir, orig_head


def _abort_owned_operation_rebase(root_dir: Path, manifest: dict[str, Any]) -> bool:
    proof = _owned_operation_rebase_proof(root_dir, manifest)
    if proof is None:
        return False
    _rebase_dir, orig_head = proof
    aborted = git_run(root_dir, ["rebase", "--abort"], timeout=60)
    if aborted.returncode != 0 or _active_rebase_paths(root_dir):
        return False
    try:
        if _git_head(root_dir) != orig_head:
            return False
        _assert_online_file_hashes(root_dir, manifest["files"], "after_sha256")
        if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
            return False
    except (OnlineSourcesError, OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        return False
    return True


def _stash_path_proof(root_dir: Path, path: str) -> dict[str, Any]:
    local_path = root_dir / path
    exists = local_path.exists()
    if exists and not local_path.is_file():
        raise _online_error("online_sources_recovery_mismatch", 409)
    return {
        "path": path,
        "before_exists": exists,
        "before_sha256": sha256_file(local_path),
    }


def _stash_path_matches(root_dir: Path, proof: dict[str, Any]) -> bool:
    local_path = root_dir / proof["path"]
    exists = local_path.exists()
    if exists != proof["before_exists"]:
        return False
    if not exists:
        return True
    return local_path.is_file() and sha256_file(local_path) == proof["before_sha256"]


def _stash_restore_destination_is_clean(root_dir: Path, dirty_paths: list[str]) -> bool:
    if not dirty_paths or _active_git_operation_paths(root_dir):
        return False
    return (
        git_run(
            root_dir,
            ["--literal-pathspecs", "diff", "--cached", "--quiet", "--", *dirty_paths],
        ).returncode
        == 0
        and git_run(
            root_dir,
            ["--literal-pathspecs", "diff", "--quiet", "--", *dirty_paths],
        ).returncode
        == 0
    )


def _stash_paths_are_restored(root_dir: Path, manifest: dict[str, Any]) -> bool:
    dirty_paths = [proof["path"] for proof in manifest["stash"]["paths"]]
    if not dirty_paths or _active_git_operation_paths(root_dir):
        return False
    try:
        staged = set(git_nul_name_list(root_dir, ["diff", "--cached", "--name-only", "-z"]))
        if staged.intersection(dirty_paths):
            return False
        return all(_stash_path_matches(root_dir, proof) for proof in manifest["stash"]["paths"])
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        return False


def _stash_restore_can_continue(root_dir: Path, manifest: dict[str, Any]) -> bool:
    dirty_paths = [proof["path"] for proof in manifest["stash"]["paths"]]
    return _stash_restore_destination_is_clean(root_dir, dirty_paths) or (
        manifest["phase"] == "restoring_worktree"
        and _stash_paths_are_restored(root_dir, manifest)
    )


def _operation_local_state_matches(
    root_dir: Path,
    manifest: dict[str, Any],
    operation_oid: str,
) -> bool:
    try:
        _assert_operation_git_context(root_dir, manifest)
        if _git_head(root_dir) != operation_oid:
            return False
        if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
            return False
        _assert_online_file_hashes(root_dir, manifest["files"], "after_sha256")
    except (OnlineSourcesError, OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        return False
    return True


def _owned_stash_oid(root_dir: Path, manifest: dict[str, Any]) -> str:
    stash = manifest["stash"]
    if not stash["oid"] and not stash["paths"]:
        return ""
    lines = git_checked(
        root_dir,
        ["stash", "list", "--format=%H%x09%gs"],
    ).stdout.splitlines()
    entries: list[tuple[str, str]] = []
    for line in lines:
        oid, separator, subject = line.partition("\t")
        if separator:
            entries.append((oid.strip(), subject.strip()))
    if stash["oid"]:
        matches = [oid for oid, _subject in entries if oid == stash["oid"]]
    else:
        matches = [
            oid
            for oid, subject in entries
            if subject == stash["message"] or subject.endswith(f": {stash['message']}")
        ]
    if len(matches) != 1:
        raise _online_error("online_sources_recovery_mismatch", 409)
    return matches[0]


def _restore_owned_stash(
    root_dir: Path,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    _assert_operation_git_context(root_dir, manifest)
    stash_oid = _owned_stash_oid(root_dir, manifest)
    if not stash_oid or not manifest["stash"]["paths"]:
        raise _online_error("online_sources_recovery_mismatch", 409)
    dirty_paths = [proof["path"] for proof in manifest["stash"]["paths"]]
    already_restored = _stash_paths_are_restored(root_dir, manifest)
    if not already_restored and not _stash_restore_destination_is_clean(root_dir, dirty_paths):
        raise _online_error("online_sources_recovery_mismatch", 409)
    manifest, manifest_digest = update_operation_manifest(
        root_dir,
        manifest,
        phase="restoring_worktree",
        stash={**manifest["stash"], "oid": stash_oid},
    )
    _assert_operation_git_context(root_dir, manifest)
    if not already_restored:
        git_checked(
            root_dir,
            [
                "--literal-pathspecs",
                "restore",
                f"--source={stash_oid}",
                "--worktree",
                "--",
                *dirty_paths,
            ],
            timeout=60,
        )
    for proof in manifest["stash"]["paths"]:
        if not _stash_path_matches(root_dir, proof):
            raise _online_error("online_sources_recovery_mismatch", 409)
    staged = set(git_nul_name_list(root_dir, ["diff", "--cached", "--name-only", "-z"]))
    if staged.intersection(dirty_paths):
        raise _online_error("online_sources_recovery_mismatch", 409)
    _assert_operation_git_context(root_dir, manifest)
    selector = git_stash_selector_for_oid(root_dir, stash_oid)
    git_checked(root_dir, ["stash", "drop", selector], timeout=60)
    return update_operation_manifest(
        root_dir,
        manifest,
        phase="push_unknown",
        stash={**manifest["stash"], "oid": "", "paths": []},
    )


def audit_online_source_operation(root_dir: Path) -> dict[str, Any] | None:
    manifest = read_operation_manifest(root_dir)
    if manifest is None:
        return None
    if _active_foreign_git_operation_paths(root_dir):
        committed = bool(manifest["operation_commit_oid"] or manifest["stable_patch_id"])
        return public_operation_recovery(
            manifest,
            actual_phase="committed" if committed else manifest["phase"],
            outcome="committed_not_pushed" if committed else "saved_not_committed",
            recovery_pending=True,
            allowed_actions=[],
        )
    if manifest["operation_kind"] == "manual_save":
        return _manual_save_recovery(root_dir, manifest)

    if _active_rebase_paths(root_dir):
        if not _abort_owned_operation_rebase(root_dir, manifest):
            return public_operation_recovery(
                manifest,
                actual_phase="rebasing",
                outcome=(
                    "committed_not_pushed"
                    if manifest["operation_commit_oid"]
                    else "saved_not_committed"
                ),
                recovery_pending=True,
                allowed_actions=[],
            )
        manifest, _ = update_operation_manifest(
            root_dir,
            manifest,
            phase="committed",
        )

    candidates = _operation_commit_candidates(root_dir, manifest)
    if len(candidates) > 1:
        return public_operation_recovery(
            manifest,
            actual_phase="committed",
            outcome="committed_not_pushed",
            recovery_pending=True,
            allowed_actions=[],
        )
    if not candidates and (manifest["operation_commit_oid"] or manifest["stable_patch_id"]):
        return public_operation_recovery(
            manifest,
            actual_phase="committed",
            outcome="committed_not_pushed",
            recovery_pending=True,
            allowed_actions=[],
        )
    if len(candidates) == 1:
        operation_oid, patch_id = candidates[0]
        if not _operation_commit_parent_is_trusted(root_dir, manifest, operation_oid):
            pushed = _remote_contains_commit(root_dir, manifest, operation_oid)
            return public_operation_recovery(
                manifest,
                actual_phase="committed",
                outcome="pushed" if pushed else "committed_not_pushed",
                recovery_pending=True,
                allowed_actions=[],
            )
        if manifest["operation_commit_oid"] != operation_oid or manifest["stable_patch_id"] != patch_id:
            manifest, _ = update_operation_manifest(
                root_dir,
                manifest,
                phase="committed",
                operation_commit_oid=operation_oid,
                stable_patch_id=patch_id,
            )
        stash_pending = bool(manifest["stash"]["oid"] or manifest["stash"]["paths"])
        if stash_pending:
            try:
                stash_oid = _owned_stash_oid(root_dir, manifest)
            except OnlineSourcesError:
                if (
                    manifest["phase"] == "restoring_worktree"
                    and manifest["stash"]["oid"]
                    and _operation_local_state_matches(root_dir, manifest, operation_oid)
                    and _stash_paths_are_restored(root_dir, manifest)
                ):
                    manifest, _ = update_operation_manifest(
                        root_dir,
                        manifest,
                        phase="push_unknown",
                        stash={**manifest["stash"], "oid": "", "paths": []},
                    )
                    stash_pending = False
                else:
                    remote_status = _operation_remote_status(root_dir, manifest, operation_oid)
                    return public_operation_recovery(
                        manifest,
                        actual_phase="committed",
                        outcome=(
                            "pushed" if remote_status == "pushed" else "committed_not_pushed"
                        ),
                        recovery_pending=True,
                        allowed_actions=[],
                    )
            else:
                if manifest["stash"]["oid"] != stash_oid:
                    manifest, _ = update_operation_manifest(
                        root_dir,
                        manifest,
                        stash={**manifest["stash"], "oid": stash_oid},
                    )
        remote_status = _operation_remote_status(root_dir, manifest, operation_oid)
        local_state_matches = _operation_local_state_matches(root_dir, manifest, operation_oid)
        remote_target_matches = _operation_remote_target_matches(root_dir, manifest)
        if (
            remote_status == "pushed"
            and not stash_pending
            and local_state_matches
            and remote_target_matches
        ):
            delete_operation_manifest(
                root_dir,
                expected_digest=operation_manifest_digest(manifest),
            )
            return None
        if remote_status == "pushed":
            dirty_paths = [proof["path"] for proof in manifest["stash"]["paths"]]
            allowed_actions = (
                ["restore_worktree"]
                if stash_pending
                and local_state_matches
                and remote_target_matches
                and _stash_restore_can_continue(root_dir, manifest)
                else []
            )
        elif (
            remote_status in {"retryable", "unknown"}
            and local_state_matches
            and remote_target_matches
            and (not stash_pending or _stash_restore_can_continue(root_dir, manifest))
        ):
            allowed_actions = ["retry_push"]
        else:
            allowed_actions = []
        return public_operation_recovery(
            manifest,
            actual_phase="committed",
            outcome="pushed" if remote_status == "pushed" else "committed_not_pushed",
            recovery_pending=True,
            allowed_actions=allowed_actions,
        )

    file_states = _operation_file_states(root_dir, manifest)
    rollback_safe = (
        _safe_write_rollback_states(
            root_dir,
            manifest,
            operation_manifest_digest(manifest),
            allow_trusted_staged=True,
        )
        is not None
    )
    if all(state == "before" for state in file_states) and manifest["phase"] == "prepared":
        delete_operation_manifest(
            root_dir,
            expected_digest=operation_manifest_digest(manifest),
        )
        return None
    remote_target_matches = _operation_remote_target_matches(root_dir, manifest)
    if all(state == "after" for state in file_states):
        actual_phase = "files_written"
        allowed_actions = []
        if _git_head(root_dir) == manifest["pre_head"] and rollback_safe:
            allowed_actions = ["rollback"]
            if remote_target_matches:
                allowed_actions.insert(0, "retry_commit")
    elif "other" not in file_states and any(state == "after" for state in file_states):
        actual_phase = "write_incomplete"
        allowed_actions = ["rollback"] if rollback_safe else []
    else:
        actual_phase = "write_incomplete"
        allowed_actions = []
    if manifest["phase"] != actual_phase:
        manifest, _ = update_operation_manifest(root_dir, manifest, phase=actual_phase)
    return public_operation_recovery(
        manifest,
        actual_phase=actual_phase,
        outcome="saved_not_committed",
        recovery_pending=True,
        allowed_actions=allowed_actions,
    )


def _remote_contains_commit(root_dir: Path, manifest: dict[str, Any], commit_oid: str) -> bool:
    return _operation_remote_status(root_dir, manifest, commit_oid) == "pushed"


def _commit_and_push_operation(
    root_dir: Path,
    manifest: dict[str, Any],
    config: dict[str, Any],
    *,
    config_changed: bool,
    summary: dict[str, Any] | None,
    allow_trusted_staged: bool = False,
) -> dict[str, Any]:
    manifest_digest = operation_manifest_digest(manifest)
    operation_oid = ""
    patch_id = ""
    try:
        _assert_operation_git_context(root_dir, manifest)
        _assert_head(root_dir, manifest["pre_head"])
        staged_before = set(git_name_list(root_dir, ["diff", "--cached", "--name-only"]))
        if staged_before:
            if not allow_trusted_staged or staged_before != _manifest_changed_paths(manifest):
                raise _preflight_error("index_changed_before_commit")
            for path, proof in manifest["files"].items():
                if _online_content_sha256(_git_blob_bytes(root_dir, "", path)) != proof[
                    "after_sha256"
                ]:
                    raise _online_error("online_sources_recovery_mismatch", 409)
        _assert_online_file_hashes(root_dir, manifest["files"], "after_sha256")
        git_checked(root_dir, ["add", "--", *_allowed_online_paths()])
        _assert_operation_git_context(root_dir, manifest)
        _assert_head(root_dir, manifest["pre_head"])
        if set(git_name_list(root_dir, ["diff", "--cached", "--name-only"])) != _manifest_changed_paths(
            manifest
        ):
            raise _preflight_error("staged_paths_mismatch")
        tree_oid = git_checked(root_dir, ["write-tree"]).stdout.strip()
        operation_oid = git_checked(
            root_dir,
            [
                "commit-tree",
                tree_oid,
                "-p",
                manifest["pre_head"],
                "-m",
                ONLINE_COMMIT_MESSAGE,
                "-m",
                manifest["commit_trailer"],
            ],
            timeout=60,
        ).stdout.strip()
        patch_id = _verify_operation_commit(
            root_dir,
            manifest,
            operation_oid,
            require_pre_head_parent=True,
        )
        _assert_operation_git_context(root_dir, manifest)
        git_checked(
            root_dir,
            [
                "update-ref",
                "refs/heads/master",
                operation_oid,
                manifest["pre_head"],
            ],
        )
        _assert_head(root_dir, operation_oid)
        manifest, manifest_digest = update_operation_manifest(
            root_dir,
            manifest,
            phase="committed",
            operation_commit_oid=operation_oid,
            stable_patch_id=patch_id,
        )
    except Exception:
        current = read_operation_manifest(root_dir) or manifest
        try:
            recovery = audit_online_source_operation(root_dir)
        except Exception:
            recovery = None
        if recovery is None:
            finalized_pushed = False
            if operation_oid and patch_id:
                try:
                    finalized_pushed = (
                        _verify_operation_commit(
                            root_dir,
                            current,
                            operation_oid,
                            require_pre_head_parent=True,
                        )
                        == patch_id
                        and _operation_commit_parent_is_trusted(
                            root_dir,
                            current,
                            operation_oid,
                        )
                        and _operation_local_state_matches(
                            root_dir,
                            current,
                            operation_oid,
                        )
                        and _operation_remote_target_matches(root_dir, current)
                        and _remote_contains_commit(root_dir, current, operation_oid)
                    )
                except (
                    OnlineSourcesError,
                    OSError,
                    RuntimeError,
                    subprocess.SubprocessError,
                    ValueError,
                ):
                    finalized_pushed = False
            if finalized_pushed:
                latest_config = _read_online_json_config(root_dir)
                return _operation_result(
                    latest_config,
                    outcome="pushed",
                    config_changed=config_changed,
                    write_complete=True,
                    commit=operation_oid,
                    pushed=True,
                    summary=summary,
                )
            raise _online_error("online_sources_recovery_mismatch", 409)
        audited_manifest = read_operation_manifest(root_dir) or current
        audited_outcome = recovery["outcome"]
        audited_commit = (
            audited_manifest["operation_commit_oid"]
            if audited_outcome in {"committed_not_pushed", "pushed"}
            else ""
        )
        latest_config = _read_online_json_config(root_dir)
        return _operation_result(
            latest_config,
            outcome=audited_outcome,
            config_changed=config_changed,
            write_complete=True,
            commit=audited_commit,
            pushed=audited_outcome == "pushed",
            recovery_pending=True,
            summary=summary,
            recovery=recovery,
        )

    dirty_paths: list[str] = []
    stash_oid = ""
    try:
        _assert_operation_git_context(root_dir, manifest)
        _assert_head(root_dir, operation_oid)
        if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
            raise _preflight_error("index_changed_before_stash")
        dirty_paths = [
            path
            for path in git_nul_name_list(root_dir, ["diff", "--name-only", "-z"])
            if path not in _allowed_online_paths()
        ]
        if dirty_paths:
            stash_proofs = [_stash_path_proof(root_dir, path) for path in dirty_paths]
            manifest, manifest_digest = update_operation_manifest(
                root_dir,
                manifest,
                stash={**manifest["stash"], "paths": stash_proofs},
            )
            _assert_head(root_dir, operation_oid)
            if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
                raise _preflight_error("index_changed_before_stash")
            for proof in stash_proofs:
                if not _stash_path_matches(root_dir, proof):
                    raise _online_error("online_sources_recovery_mismatch", 409)
            previous = git_run(root_dir, ["rev-parse", "--verify", "refs/stash"])
            previous_oid = previous.stdout.strip() if previous.returncode == 0 else ""
            _assert_operation_git_context(root_dir, manifest)
            git_checked(
                root_dir,
                [
                    "--literal-pathspecs",
                    "stash",
                    "push",
                    "--keep-index",
                    "-m",
                    manifest["stash"]["message"],
                    "--",
                    *dirty_paths,
                ],
                timeout=60,
            )
            stash_oid = git_checked(root_dir, ["rev-parse", "--verify", "refs/stash"]).stdout.strip()
            if not stash_oid or stash_oid == previous_oid:
                raise _online_error("online_sources_recovery_mismatch", 409)
            manifest, manifest_digest = update_operation_manifest(
                root_dir,
                manifest,
                stash={**manifest["stash"], "oid": stash_oid},
            )

        _assert_operation_git_context(root_dir, manifest)
        _assert_head(root_dir, operation_oid)
        if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
            raise _preflight_error("index_changed_after_stash")
        fetched_oid = _fetch_operation_remote(root_dir, manifest)
        _assert_operation_git_context(root_dir, manifest)
        _assert_remote_data_only_advance(root_dir, manifest["pre_head"], fetched_oid)
        if fetched_oid != manifest["pre_head"]:
            manifest, manifest_digest = update_operation_manifest(
                root_dir,
                manifest,
                phase="rebasing",
            )
            _verified_operation_remote_target(root_dir, manifest)
            _assert_operation_git_context(root_dir, manifest)
            _assert_head(root_dir, operation_oid)
            _assert_online_file_hashes(root_dir, manifest["files"], "after_sha256")
            if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
                raise _preflight_error("index_changed_before_rebase")
            git_checked(root_dir, ["rebase", "--merge", fetched_oid], timeout=120)
            _assert_operation_git_context(root_dir, manifest)
            operation_oid = _git_head(root_dir)
            rebased_patch_id = _verify_operation_commit(
                root_dir,
                manifest,
                operation_oid,
                require_pre_head_parent=False,
            )
            if rebased_patch_id != manifest["stable_patch_id"]:
                raise _online_error("online_sources_recovery_mismatch", 409)
            if _operation_commit_parent_oid(root_dir, operation_oid) != fetched_oid:
                raise _online_error("online_sources_recovery_mismatch", 409)
            manifest, manifest_digest = update_operation_manifest(
                root_dir,
                manifest,
                phase="committed",
                operation_commit_oid=operation_oid,
            )
        _assert_operation_git_context(root_dir, manifest)
        _assert_head(root_dir, operation_oid)
        if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
            raise _preflight_error("index_changed_before_push")
        manifest, manifest_digest = update_operation_manifest(
            root_dir,
            manifest,
            phase="push_unknown",
        )
        push_target = _verified_operation_remote_target(root_dir, manifest)
        _assert_operation_git_context(root_dir, manifest)
        _assert_head(root_dir, operation_oid)
        _assert_online_file_hashes(root_dir, manifest["files"], "after_sha256")
        if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
            raise _preflight_error("index_changed_before_push")
        try:
            git_checked(
                root_dir,
                ["push", "--", push_target["push_url"], f"{operation_oid}:{manifest['remote_ref']}"],
                timeout=120,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        pushed = _remote_contains_commit(root_dir, manifest, operation_oid)
    except Exception:
        rebase_blocked = False
        if _active_rebase_paths(root_dir):
            if _abort_owned_operation_rebase(root_dir, manifest):
                manifest, manifest_digest = update_operation_manifest(
                    root_dir,
                    manifest,
                    phase="committed",
                )
            else:
                rebase_blocked = True
        pushed = False if rebase_blocked else _remote_contains_commit(root_dir, manifest, operation_oid)
    else:
        rebase_blocked = False

    restore_ok = True
    if stash_oid and not rebase_blocked:
        try:
            manifest, manifest_digest = _restore_owned_stash(root_dir, manifest)
            if not pushed:
                manifest, manifest_digest = update_operation_manifest(
                    root_dir,
                    manifest,
                    phase="committed",
                )
        except Exception:
            restore_ok = False
    elif stash_oid:
        restore_ok = False

    local_state_matches = _operation_local_state_matches(root_dir, manifest, operation_oid)
    remote_target_matches = _operation_remote_target_matches(root_dir, manifest)
    if pushed and restore_ok and local_state_matches and remote_target_matches:
        delete_operation_manifest(root_dir, expected_digest=manifest_digest)
        return _operation_result(
            config,
            outcome="pushed",
            config_changed=config_changed,
            write_complete=True,
            commit=operation_oid,
            pushed=True,
            summary=summary,
        )
    remote_status = (
        "unsafe"
        if rebase_blocked
        else ("pushed" if pushed else _operation_remote_status(root_dir, manifest, operation_oid))
    )
    stash_pending = bool(manifest["stash"]["oid"] or manifest["stash"]["paths"])
    dirty_paths = [proof["path"] for proof in manifest["stash"]["paths"]]
    restore_destination_clean = _stash_restore_can_continue(root_dir, manifest) if stash_pending else True
    if (
        remote_status == "pushed"
        and stash_pending
        and local_state_matches
        and remote_target_matches
        and restore_destination_clean
    ):
        allowed_actions = ["restore_worktree"]
    elif (
        remote_status in {"retryable", "unknown"}
        and local_state_matches
        and remote_target_matches
        and restore_destination_clean
    ):
        allowed_actions = ["retry_push"]
    else:
        allowed_actions = []
    recovery = public_operation_recovery(
        manifest,
        actual_phase=manifest["phase"],
        outcome="pushed" if remote_status == "pushed" else "committed_not_pushed",
        recovery_pending=True,
        allowed_actions=allowed_actions,
    )
    latest_config = _read_online_json_config(root_dir)
    return _operation_result(
        latest_config,
        outcome="pushed" if remote_status == "pushed" else "committed_not_pushed",
        config_changed=config_changed,
        write_complete=True,
        commit=operation_oid,
        pushed=remote_status == "pushed",
        recovery_pending=True,
        summary=summary,
        recovery=recovery,
    )


def sync_saved_online_source_config(
    root_dir: Path,
    *,
    if_match: Any,
) -> dict[str, Any]:
    with online_sources_guard():
        recovery = audit_online_source_operation(root_dir)
        if recovery is not None:
            raise _online_error("online_sources_recovery_pending", 409)
        config = _read_online_json_config(root_dir)
        digest = online_config_digest(config)
        require_online_config_match(if_match, digest)
        config_path = online_config_path(root_dir)
        config_bytes = config_path.read_bytes()
        expected_opml, _ = render_online_opml_bytes(config["sources"])
        opml_path = online_opml_path(root_dir)
        if not _online_file_matches(opml_path, expected_opml):
            raise _preflight_error("derived_opml_mismatch")
        opml_bytes = opml_path.read_bytes()
        target = _manual_sync_git_preflight(root_dir)
        if config_path.read_bytes() != config_bytes or opml_path.read_bytes() != opml_bytes:
            raise _online_error("online_sources_config_stale", 409)
        post_fetch_config = _read_online_json_config(root_dir)
        if online_config_digest(post_fetch_config) != digest:
            raise _online_error("online_sources_config_stale", 409)
        post_fetch_opml, _ = render_online_opml_bytes(post_fetch_config["sources"])
        if not _online_file_matches(opml_path, post_fetch_opml):
            raise _online_error("online_sources_config_stale", 409)
        if not _online_paths_changed_from_head(root_dir):
            return _operation_result(
                config,
                outcome="no_change",
                config_changed=False,
                write_complete=True,
            )
        path_map = {path: root_dir / path for path in _allowed_online_paths()}
        before_hashes = {
            path: _online_content_sha256(_git_blob_bytes(root_dir, target["pre_head"], path))
            for path in _allowed_online_paths()
        }
        after_hashes = {
            path: _online_file_sha256(local_path)
            for path, local_path in path_map.items()
        }
        manifest = new_operation_manifest(
            operation_kind="manual_sync",
            target=target,
            before_hashes=before_hashes,
            after_hashes=after_hashes,
            base_config_digest=digest,
        )
        manifest["phase"] = "files_written"
        write_operation_manifest(root_dir, manifest)
        return _commit_and_push_operation(
            root_dir,
            manifest,
            config,
            config_changed=True,
            summary={},
        )


def apply_online_source_config_operation(
    root_dir: Path,
    candidate_config: dict[str, Any],
    *,
    operation_kind: str,
    base_config_digest: str,
    preview_hash: str = "",
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if operation_kind not in {"apply", "unbind"}:
        raise ValueError("unsupported online source operation")
    with online_sources_guard():
        recovery = audit_online_source_operation(root_dir)
        if recovery is not None:
            raise _online_error("online_sources_recovery_pending", 409)
        current_config = _read_online_json_config(root_dir)
        current_digest = online_config_digest(current_config)
        if current_digest != base_config_digest:
            raise _online_error("online_sources_config_stale", 409)
        config_path = online_config_path(root_dir)
        opml_path = online_opml_path(root_dir)
        current_config_bytes = config_path.read_bytes()
        expected_current_opml, _ = render_online_opml_bytes(current_config["sources"])
        if not _online_file_matches(opml_path, expected_current_opml):
            raise _preflight_error("derived_opml_mismatch")
        current_opml_bytes = opml_path.read_bytes()

        normalized_candidate = validate_online_config_schema(candidate_config, existing=True)
        user_sources = online_user_sources_from_config(normalized_candidate)
        candidate = build_online_config(
            user_sources,
            updated_at=current_config.get("updated_at") or utc_timestamp(),
            github_star_sync=normalized_candidate.get("github_star_sync"),
        )
        changed = online_config_digest(candidate) != current_digest
        if not changed:
            return _operation_result(
                current_config,
                outcome="no_change",
                config_changed=False,
                write_complete=True,
                summary=summary,
            )
        candidate = build_online_config(
            user_sources,
            github_star_sync=normalized_candidate.get("github_star_sync"),
        )

        target = fresh_git_preflight(root_dir)
        if (
            config_path.read_bytes() != current_config_bytes
            or opml_path.read_bytes() != current_opml_bytes
        ):
            raise _online_error("online_sources_config_stale", 409)
        post_fetch_config = _read_online_json_config(root_dir)
        if online_config_digest(post_fetch_config) != current_digest:
            raise _online_error("online_sources_config_stale", 409)
        config_content = render_json_bytes(candidate)
        opml_content, _ = render_online_opml_bytes(user_sources)
        path_map = {
            _allowed_online_paths()[0]: config_path,
            _allowed_online_paths()[1]: opml_path,
        }
        before_hashes = {
            path: _online_content_sha256(_git_blob_bytes(root_dir, target["pre_head"], path))
            for path in _allowed_online_paths()
        }
        if any(
            _online_file_sha256(local_path) != before_hashes[path]
            for path, local_path in path_map.items()
        ):
            raise _online_error("online_sources_config_stale", 409)
        after_hashes = {
            _allowed_online_paths()[0]: _online_content_sha256(config_content),
            _allowed_online_paths()[1]: _online_content_sha256(opml_content),
        }
        manifest = new_operation_manifest(
            operation_kind=operation_kind,
            target=target,
            before_hashes=before_hashes,
            after_hashes=after_hashes,
            preview_hash=preview_hash,
            base_config_digest=base_config_digest,
        )
        manifest_digest = write_operation_manifest(root_dir, manifest)
        try:
            _assert_head(root_dir, target["pre_head"])
            _assert_online_file_hashes(root_dir, manifest["files"], "before_sha256")
            atomic_replace_bytes(opml_path, opml_content)
            manifest, manifest_digest = update_operation_manifest(
                root_dir,
                manifest,
                phase="write_incomplete",
            )
            _assert_head(root_dir, target["pre_head"])
            if _online_file_sha256(config_path) != before_hashes[_allowed_online_paths()[0]]:
                raise _online_error("online_sources_config_stale", 409)
            atomic_replace_bytes(config_path, config_content)
            _assert_online_file_hashes(root_dir, manifest["files"], "after_sha256")
            manifest, manifest_digest = update_operation_manifest(
                root_dir,
                manifest,
                phase="files_written",
            )
        except Exception as exc:
            try:
                manifest, manifest_digest = update_operation_manifest(
                    root_dir,
                    manifest,
                    phase="write_incomplete",
                )
            except Exception:
                manifest_digest = ""
            restored = False
            safe_states = (
                _safe_write_rollback_states(root_dir, manifest, manifest_digest)
                if manifest_digest
                else None
            )
            if safe_states is not None:
                confirmed_states = _safe_write_rollback_states(
                    root_dir,
                    manifest,
                    manifest_digest,
                )
                if confirmed_states != safe_states:
                    safe_states = None
            if safe_states is not None:
                try:
                    if any(state == "after" for state in safe_states):
                        git_checked(
                            root_dir,
                            [
                                "restore",
                                f"--source={target['pre_head']}",
                                "--staged",
                                "--worktree",
                                "--",
                                *_allowed_online_paths(),
                            ],
                            timeout=60,
                        )
                    _assert_online_file_hashes(root_dir, manifest["files"], "before_sha256")
                    cached = git_run(
                        root_dir,
                        ["diff", "--cached", "--quiet", "--", *_allowed_online_paths()],
                    ).returncode
                    uncached = git_run(
                        root_dir,
                        ["diff", "--quiet", "--", *_allowed_online_paths()],
                    ).returncode
                    restored = cached == 0 and uncached == 0
                except Exception:
                    restored = False
            if restored:
                delete_operation_manifest(root_dir, expected_digest=manifest_digest)
                if isinstance(exc, OnlineSourcesError) and exc.code in {
                    "online_sources_preflight_failed",
                    "online_sources_config_stale",
                }:
                    raise exc
                raise _online_error("online_sources_write_failed", 500) from exc
            current_manifest = read_operation_manifest(root_dir) or manifest
            current_manifest_digest = operation_manifest_digest(current_manifest)
            recovery_states = _safe_write_rollback_states(
                root_dir,
                current_manifest,
                current_manifest_digest,
                allow_trusted_staged=True,
            )
            recovery = public_operation_recovery(
                current_manifest,
                actual_phase="write_incomplete",
                outcome="saved_not_committed",
                recovery_pending=True,
                allowed_actions=(
                    ["rollback"]
                    if recovery_states is not None
                    and any(state == "after" for state in recovery_states)
                    else []
                ),
            )
            current_config_hash = _online_file_sha256(config_path)
            if current_config_hash == before_hashes[_allowed_online_paths()[0]]:
                response_config = current_config
                response_config_changed = False
            elif current_config_hash == after_hashes[_allowed_online_paths()[0]]:
                response_config = candidate
                response_config_changed = True
            else:
                response_config = _read_online_json_config(root_dir)
                response_config_changed = online_config_digest(response_config) != current_digest
            return _operation_result(
                response_config,
                outcome="saved_not_committed",
                config_changed=response_config_changed,
                write_complete=False,
                recovery_pending=True,
                summary=summary,
                recovery=recovery,
            )
        return _commit_and_push_operation(
            root_dir,
            manifest,
            candidate,
            config_changed=True,
            summary=summary,
        )


def _retry_owned_operation_push(
    root_dir: Path,
    manifest: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    _assert_operation_git_context(root_dir, manifest)
    operation_oid = manifest["operation_commit_oid"]
    if not operation_oid:
        raise _online_error("online_sources_recovery_mismatch", 409)
    patch_id = _verify_operation_commit(
        root_dir,
        manifest,
        operation_oid,
        require_pre_head_parent=False,
    )
    if patch_id != manifest["stable_patch_id"]:
        raise _online_error("online_sources_recovery_mismatch", 409)
    _assert_head(root_dir, operation_oid, "retry_push_head_changed")
    if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
        raise _online_error("online_sources_recovery_mismatch", 409)
    _verified_operation_remote_target(root_dir, manifest)
    if not _operation_commit_parent_is_trusted(root_dir, manifest, operation_oid):
        raise _online_error("online_sources_recovery_mismatch", 409)

    manifest_digest = operation_manifest_digest(manifest)
    stash_oid = _owned_stash_oid(root_dir, manifest) if manifest["stash"]["paths"] else ""
    dirty_paths = [proof["path"] for proof in manifest["stash"]["paths"]]
    if stash_oid and not _stash_restore_can_continue(root_dir, manifest):
        raise _online_error("online_sources_recovery_mismatch", 409)
    if not stash_oid:
        dirty_paths = [
            path
            for path in git_nul_name_list(root_dir, ["diff", "--name-only", "-z"])
            if path not in _allowed_online_paths()
        ]
    if dirty_paths and not stash_oid:
        proofs = [_stash_path_proof(root_dir, path) for path in dirty_paths]
        manifest, manifest_digest = update_operation_manifest(
            root_dir,
            manifest,
            stash={**manifest["stash"], "paths": proofs},
        )
        _assert_head(root_dir, operation_oid, "retry_push_head_changed")
        if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
            raise _online_error("online_sources_recovery_mismatch", 409)
        for proof in proofs:
            if not _stash_path_matches(root_dir, proof):
                raise _online_error("online_sources_recovery_mismatch", 409)
        previous = git_run(root_dir, ["rev-parse", "--verify", "refs/stash"])
        previous_oid = previous.stdout.strip() if previous.returncode == 0 else ""
        _assert_operation_git_context(root_dir, manifest)
        git_checked(
            root_dir,
            [
                "--literal-pathspecs",
                "stash",
                "push",
                "--keep-index",
                "-m",
                manifest["stash"]["message"],
                "--",
                *dirty_paths,
            ],
            timeout=60,
        )
        stash_oid = git_checked(root_dir, ["rev-parse", "--verify", "refs/stash"]).stdout.strip()
        if not stash_oid or stash_oid == previous_oid:
            raise _online_error("online_sources_recovery_mismatch", 409)
        manifest, manifest_digest = update_operation_manifest(
            root_dir,
            manifest,
            stash={**manifest["stash"], "oid": stash_oid},
        )
        _assert_operation_git_context(root_dir, manifest)
        _assert_head(root_dir, operation_oid, "retry_push_head_changed")
        if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
            raise _online_error("online_sources_recovery_mismatch", 409)

    pushed = False
    try:
        _assert_operation_git_context(root_dir, manifest)
        fetched_oid = _fetch_operation_remote(root_dir, manifest)
        _assert_operation_git_context(root_dir, manifest)
        if git_run(root_dir, ["merge-base", "--is-ancestor", operation_oid, fetched_oid]).returncode == 0:
            pushed = True
        else:
            _assert_remote_data_only_advance(root_dir, manifest["pre_head"], fetched_oid)
            if fetched_oid != manifest["pre_head"]:
                manifest, manifest_digest = update_operation_manifest(
                    root_dir,
                    manifest,
                    phase="rebasing",
                )
                _verified_operation_remote_target(root_dir, manifest)
                _assert_operation_git_context(root_dir, manifest)
                _assert_head(root_dir, operation_oid, "retry_push_head_changed")
                _assert_online_file_hashes(root_dir, manifest["files"], "after_sha256")
                if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
                    raise _online_error("online_sources_recovery_mismatch", 409)
                git_checked(root_dir, ["rebase", "--merge", fetched_oid], timeout=120)
                _assert_operation_git_context(root_dir, manifest)
                operation_oid = _git_head(root_dir)
                rebased_patch_id = _verify_operation_commit(
                    root_dir,
                    manifest,
                    operation_oid,
                    require_pre_head_parent=False,
                )
                if rebased_patch_id != manifest["stable_patch_id"]:
                    raise _online_error("online_sources_recovery_mismatch", 409)
                if _operation_commit_parent_oid(root_dir, operation_oid) != fetched_oid:
                    raise _online_error("online_sources_recovery_mismatch", 409)
                manifest, manifest_digest = update_operation_manifest(
                    root_dir,
                    manifest,
                    phase="committed",
                    operation_commit_oid=operation_oid,
                )
            _assert_operation_git_context(root_dir, manifest)
            _assert_head(root_dir, operation_oid, "retry_push_head_changed")
            manifest, manifest_digest = update_operation_manifest(
                root_dir,
                manifest,
                phase="push_unknown",
            )
            push_target = _verified_operation_remote_target(root_dir, manifest)
            _assert_operation_git_context(root_dir, manifest)
            _assert_head(root_dir, operation_oid, "retry_push_head_changed")
            _assert_online_file_hashes(root_dir, manifest["files"], "after_sha256")
            if git_name_list(root_dir, ["diff", "--cached", "--name-only"]):
                raise _online_error("online_sources_recovery_mismatch", 409)
            try:
                git_checked(
                    root_dir,
                    [
                        "push",
                        "--",
                        push_target["push_url"],
                        f"{operation_oid}:{manifest['remote_ref']}",
                    ],
                    timeout=120,
                )
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass
            pushed = _remote_contains_commit(root_dir, manifest, operation_oid)
    except Exception:
        rebase_blocked = False
        if _active_rebase_paths(root_dir):
            if _abort_owned_operation_rebase(root_dir, manifest):
                manifest, manifest_digest = update_operation_manifest(
                    root_dir,
                    manifest,
                    phase="committed",
                )
            else:
                rebase_blocked = True
        pushed = False if rebase_blocked else _remote_contains_commit(root_dir, manifest, operation_oid)
    else:
        rebase_blocked = False

    restore_ok = True
    if stash_oid and not rebase_blocked:
        try:
            manifest, manifest_digest = _restore_owned_stash(root_dir, manifest)
            if not pushed:
                manifest, manifest_digest = update_operation_manifest(
                    root_dir,
                    manifest,
                    phase="committed",
                )
        except Exception:
            restore_ok = False
    elif stash_oid:
        restore_ok = False

    local_state_matches = _operation_local_state_matches(root_dir, manifest, operation_oid)
    remote_target_matches = _operation_remote_target_matches(root_dir, manifest)
    if pushed and restore_ok and local_state_matches and remote_target_matches:
        delete_operation_manifest(root_dir, expected_digest=manifest_digest)
        return _operation_result(
            config,
            outcome="pushed",
            config_changed=True,
            write_complete=True,
            commit=operation_oid,
            pushed=True,
        )
    remote_status = (
        "unsafe"
        if rebase_blocked
        else ("pushed" if pushed else _operation_remote_status(root_dir, manifest, operation_oid))
    )
    stash_pending = bool(manifest["stash"]["oid"] or manifest["stash"]["paths"])
    dirty_paths = [proof["path"] for proof in manifest["stash"]["paths"]]
    restore_destination_clean = _stash_restore_can_continue(root_dir, manifest) if stash_pending else True
    if (
        remote_status == "pushed"
        and stash_pending
        and local_state_matches
        and remote_target_matches
        and restore_destination_clean
    ):
        allowed_actions = ["restore_worktree"]
    elif (
        remote_status in {"retryable", "unknown"}
        and local_state_matches
        and remote_target_matches
        and restore_destination_clean
    ):
        allowed_actions = ["retry_push"]
    else:
        allowed_actions = []
    recovery = public_operation_recovery(
        manifest,
        actual_phase=manifest["phase"],
        outcome="pushed" if remote_status == "pushed" else "committed_not_pushed",
        recovery_pending=True,
        allowed_actions=allowed_actions,
    )
    latest_config = _read_online_json_config(root_dir)
    return _operation_result(
        latest_config,
        outcome="pushed" if remote_status == "pushed" else "committed_not_pushed",
        config_changed=True,
        write_complete=True,
        commit=operation_oid,
        pushed=remote_status == "pushed",
        recovery_pending=True,
        recovery=recovery,
    )


def recover_online_source_operation(
    root_dir: Path,
    *,
    action: Any,
    operation_id: Any,
    manifest_digest: Any,
    confirmed: bool = False,
) -> dict[str, Any]:
    with online_sources_guard():
        recovery = audit_online_source_operation(root_dir)
        manifest = read_operation_manifest(root_dir)
        if recovery is None or manifest is None:
            raise _online_error("online_sources_recovery_mismatch", 409)
        current_digest = operation_manifest_digest(manifest)
        if operation_id != manifest["operation_id"] or manifest_digest != current_digest:
            raise _online_error("online_sources_recovery_mismatch", 409)
        if not isinstance(action, str) or action not in recovery["allowed_actions"]:
            raise _online_error("online_sources_recovery_mismatch", 409)

        if action == "repair_derived_file":
            repaired = _manual_save_recovery(root_dir, manifest)
            if repaired is not None:
                raise _online_error(
                    "online_sources_write_failed",
                    500,
                    {"recovery_pending": True},
                )
            config = _read_online_json_config(root_dir)
            return _operation_result(
                config,
                outcome="no_change",
                config_changed=False,
                write_complete=True,
            )

        if action == "rollback":
            if not confirmed:
                raise _online_error("online_sources_recovery_mismatch", 409)
            states = _safe_write_rollback_states(
                root_dir,
                manifest,
                current_digest,
                allow_trusted_staged=True,
            )
            if states is None:
                raise _online_error("online_sources_recovery_mismatch", 409)
            if recovery["phase"] == "files_written" and any(state != "after" for state in states):
                raise _online_error("online_sources_recovery_mismatch", 409)
            if recovery["phase"] == "write_incomplete" and all(state == "before" for state in states):
                raise _online_error("online_sources_recovery_mismatch", 409)
            if _safe_write_rollback_states(
                root_dir,
                manifest,
                current_digest,
                allow_trusted_staged=True,
            ) != states:
                raise _online_error("online_sources_recovery_mismatch", 409)
            git_checked(
                root_dir,
                [
                    "restore",
                    f"--source={manifest['pre_head']}",
                    "--staged",
                    "--worktree",
                    "--",
                    *_allowed_online_paths(),
                ],
                timeout=60,
            )
            _assert_online_file_hashes(root_dir, manifest["files"], "before_sha256")
            if git_run(
                root_dir,
                ["diff", "--cached", "--quiet", "--", *_allowed_online_paths()],
            ).returncode != 0 or git_run(
                root_dir,
                ["diff", "--quiet", "--", *_allowed_online_paths()],
            ).returncode != 0:
                raise _online_error("online_sources_recovery_mismatch", 409)
            delete_operation_manifest(root_dir, expected_digest=current_digest)
            config = _read_online_json_config(root_dir)
            return _operation_result(
                config,
                outcome="no_change",
                config_changed=False,
                write_complete=True,
            )

        if action == "retry_commit":
            _assert_head(root_dir, manifest["pre_head"], "retry_head_changed")
            _assert_online_file_hashes(root_dir, manifest["files"], "after_sha256")
            config = _read_online_json_config(root_dir)
            return _commit_and_push_operation(
                root_dir,
                manifest,
                config,
                config_changed=True,
                summary={},
                allow_trusted_staged=True,
            )

        if action == "retry_push":
            config = _read_online_json_config(root_dir)
            return _retry_owned_operation_push(root_dir, manifest, config)

        if action == "restore_worktree":
            operation_oid = manifest["operation_commit_oid"]
            if not operation_oid or not _remote_contains_commit(root_dir, manifest, operation_oid):
                raise _online_error("online_sources_recovery_mismatch", 409)
            manifest, new_digest = _restore_owned_stash(root_dir, manifest)
            delete_operation_manifest(root_dir, expected_digest=new_digest)
            config = _read_online_json_config(root_dir)
            return _operation_result(
                config,
                outcome="pushed",
                config_changed=True,
                write_complete=True,
                commit=operation_oid,
                pushed=True,
            )

        raise _online_error("online_sources_recovery_mismatch", 409)


def git_stash_selector_for_oid(root_dir: Path, stash_oid: str) -> str:
    stash_lines = git_checked(root_dir, ["stash", "list", "--format=%gd%x09%H"]).stdout.splitlines()
    matches = []
    for line in stash_lines:
        selector, separator, oid = line.partition("\t")
        if separator and oid.strip() == stash_oid:
            matches.append(selector.strip())
    if len(matches) != 1:
        raise RuntimeError("online sync stash ownership is missing or ambiguous")
    selector = matches[0]
    resolved_oid = git_checked(root_dir, ["rev-parse", "--verify", selector]).stdout.strip()
    if resolved_oid != stash_oid:
        raise RuntimeError("online sync stash selector changed before drop")
    return selector


def sync_online_source_config(root_dir: Path, payload: Any | None = None, *, push: bool = True) -> dict[str, Any]:
    if not push:
        write_result = (
            write_online_source_config(root_dir, payload)
            if payload is not None
            else read_online_source_config(root_dir)
        )
        top = git_checked(root_dir, ["rev-parse", "--show-toplevel"]).stdout.strip()
        if Path(top).resolve() != root_dir.resolve():
            raise ValueError("online sync must run from the repo root")
        pre_staged = git_name_list(root_dir, ["diff", "--cached", "--name-only"])
        blocked_staged = [path for path in pre_staged if path not in _allowed_online_paths()]
        if blocked_staged:
            raise ValueError("unrelated_files_already_staged:" + ",".join(blocked_staged))
        git_checked(root_dir, ["add", "--", *_allowed_online_paths()])
        staged_allowed = git_name_list(
            root_dir,
            ["diff", "--cached", "--name-only", "--", *_allowed_online_paths()],
        )
        if not staged_allowed:
            return {
                **write_result,
                "synced": False,
                "no_changes": True,
                "staged_paths": [],
                "commit": "",
                "pushed": False,
            }
        git_checked(
            root_dir,
            ["commit", "-m", ONLINE_COMMIT_MESSAGE, "--", *_allowed_online_paths()],
            timeout=60,
        )
        return {
            **write_result,
            "synced": True,
            "no_changes": False,
            "staged_paths": staged_allowed,
            "commit": _git_head(root_dir),
            "pushed": False,
            "push_output": "",
        }

    if payload is not None:
        current = _read_online_json_config(root_dir)
        saved = save_online_source_config_transaction(
            root_dir,
            payload,
            if_match=online_config_etag(current),
        )
        etag = saved["etag"]
    else:
        current = _read_online_json_config(root_dir)
        etag = online_config_etag(current)
    result = sync_saved_online_source_config(root_dir, if_match=etag)
    return {
        **result,
        "synced": result["outcome"] != "no_change",
        "no_changes": result["outcome"] == "no_change",
        "staged_paths": _allowed_online_paths() if result["config_changed"] else [],
        "push_output": "",
    }
