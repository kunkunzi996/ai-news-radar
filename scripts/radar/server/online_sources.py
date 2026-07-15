from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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


def write_online_opml(root_dir: Path, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _, path = ensure_public_online_paths(root_dir)
    feeds = [source for source in sources if source["type"] == "rss" and source.get("enabled") is not False]
    path.parent.mkdir(parents=True, exist_ok=True)
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
    tmp_path = path.with_suffix(".opml.tmp")
    tree.write(tmp_path, encoding="utf-8", xml_declaration=True)
    os.replace(tmp_path, path)
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
        sources = []
        updated_at = None
    opml_sources = read_online_opml(root_dir)
    existing_feed_urls = {source["locator"] for source in sources if source["type"] == "rss"}
    sources.extend(source for source in opml_sources if source["locator"] not in existing_feed_urls)
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


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


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


def write_online_source_config(root_dir: Path, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    config_path, _ = ensure_public_online_paths(root_dir)
    current_sources: list[dict[str, Any]] = []
    current_binding: dict[str, Any] | None = None
    if config_path.exists():
        existing_payload = json.loads(config_path.read_text(encoding="utf-8"))
        current_config = validate_online_config_schema(existing_payload, existing=True)
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
    config = build_online_config(sources, github_star_sync=current_binding)
    validate_online_config_schema(config, existing=True)
    if protected_online_config_projection(config) != protected_online_config_projection(
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
    write_json_atomic(config_path, config)
    written_feeds = write_online_opml(root_dir, sources)
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
        "config": config,
        "sources": sources,
    }


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
    write_result = write_online_source_config(root_dir, payload) if payload is not None else read_online_source_config(root_dir)
    allowed_paths = [
        str(ONLINE_CONFIG_FILENAME).replace("\\", "/"),
        str(ONLINE_OPML_FILENAME).replace("\\", "/"),
    ]
    top = git_checked(root_dir, ["rev-parse", "--show-toplevel"]).stdout.strip()
    if Path(top).resolve() != root_dir.resolve():
        raise ValueError("online sync must run from the repo root")

    pre_staged = git_name_list(root_dir, ["diff", "--cached", "--name-only"])
    blocked_staged = [path for path in pre_staged if path not in allowed_paths]
    if blocked_staged:
        raise ValueError("unrelated_files_already_staged:" + ",".join(blocked_staged))

    git_checked(root_dir, ["add", "--", *allowed_paths])
    staged = git_name_list(root_dir, ["diff", "--cached", "--name-only"])
    blocked_after_add = [path for path in staged if path not in allowed_paths]
    if blocked_after_add:
        raise ValueError("blocked_staged_files:" + ",".join(blocked_after_add))

    staged_allowed = git_name_list(root_dir, ["diff", "--cached", "--name-only", "--", *allowed_paths])
    if not staged_allowed:
        return {
            **write_result,
            "synced": False,
            "no_changes": True,
            "staged_paths": [],
            "commit": "",
            "pushed": False,
        }

    git_checked(root_dir, ["commit", "-m", ONLINE_COMMIT_MESSAGE, "--", *allowed_paths], timeout=60)
    pushed = False
    push_stdout = ""
    if push:
        branch = git_checked(root_dir, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        dirty_tracked_paths = git_nul_name_list(root_dir, ["diff", "--name-only", "-z"])
        operation_stash_oid = ""
        if dirty_tracked_paths:
            previous_stash = git_run(root_dir, ["rev-parse", "--verify", "refs/stash"])
            previous_stash_oid = previous_stash.stdout.strip() if previous_stash.returncode == 0 else ""
            git_checked(
                root_dir,
                ["stash", "push", "-m", ONLINE_SYNC_STASH_MESSAGE, "--", *dirty_tracked_paths],
                timeout=60,
            )
            operation_stash_oid = git_checked(
                root_dir,
                ["rev-parse", "--verify", "refs/stash"],
            ).stdout.strip()
            if not operation_stash_oid or operation_stash_oid == previous_stash_oid:
                raise RuntimeError("online sync failed to identify its operation stash")
        try:
            try:
                git_checked(root_dir, ["pull", "--rebase", "origin", branch], timeout=120)
            except RuntimeError as exc:
                git_run(root_dir, ["rebase", "--abort"], timeout=60)
                raise ValueError(f"online_sources_rebase_failed: git pull --rebase 失败，已中止推送：{exc}") from exc
            pushed_result = git_checked(root_dir, ["push"], timeout=120)
            pushed = True
            push_stdout = (pushed_result.stdout or pushed_result.stderr or "").strip()
        finally:
            if operation_stash_oid:
                git_checked(
                    root_dir,
                    [
                        "restore",
                        f"--source={operation_stash_oid}",
                        "--worktree",
                        "--",
                        *dirty_tracked_paths,
                    ],
                    timeout=60,
                )
                stash_selector = git_stash_selector_for_oid(root_dir, operation_stash_oid)
                git_checked(root_dir, ["stash", "drop", stash_selector], timeout=60)
    commit = git_checked(root_dir, ["rev-parse", "--short", "HEAD"]).stdout.strip()
    return {
        **write_result,
        "synced": True,
        "no_changes": False,
        "staged_paths": staged_allowed,
        "commit": commit,
        "pushed": pushed,
        "push_output": push_stdout,
    }
