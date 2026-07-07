from __future__ import annotations

from scripts.radar.server import *  # noqa: F401,F403

"""Source config and subscription persistence helpers."""

def validate_source_config(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("config root must be a JSON object")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise ValueError("config must contain a sources array")
    if len(sources) > 500:
        raise ValueError("too many sources")
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"sources[{index}] must be an object")
        source_id = str(source.get("id") or "").strip()
        name = str(source.get("name") or "").strip()
        if not source_id:
            raise ValueError(f"sources[{index}].id is required")
        if not name:
            raise ValueError(f"sources[{index}].name is required")
    return payload


def youtube_channel_id_from_feed_url(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.netloc not in {"www.youtube.com", "youtube.com"}:
        return ""
    query = urllib.parse.parse_qs(parsed.query)
    return str((query.get("channel_id") or [""])[0]).strip()


def youtube_feed_url(channel_id: str) -> str:
    clean = str(channel_id or "").strip()
    if not clean:
        return ""
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={clean}"


def validate_youtube_subscription(payload: dict[str, Any], index: int) -> dict[str, str]:
    title = str(payload.get("title") or payload.get("text") or "").strip()
    channel_id = str(payload.get("channel_id") or "").strip()
    html_url = str(payload.get("html_url") or payload.get("htmlUrl") or "").strip()
    xml_url = str(payload.get("xml_url") or payload.get("xmlUrl") or "").strip()
    if not channel_id and xml_url:
        channel_id = youtube_channel_id_from_feed_url(xml_url)
    if not xml_url and channel_id:
        xml_url = youtube_feed_url(channel_id)
    if not title:
        raise ValueError(f"subscriptions[{index}].title is required")
    if not channel_id:
        raise ValueError(f"subscriptions[{index}].channel_id is required")
    if not xml_url.startswith("https://www.youtube.com/feeds/videos.xml?channel_id="):
        raise ValueError(f"subscriptions[{index}].xml_url must be a YouTube channel feed")
    if html_url and not (
        html_url.startswith("https://www.youtube.com/")
        or html_url.startswith("https://youtube.com/")
    ):
        raise ValueError(f"subscriptions[{index}].html_url must be a YouTube URL")
    return {
        "title": title[:120],
        "channel_id": channel_id[:120],
        "xml_url": xml_url,
        "html_url": html_url[:300],
    }


def opml_path(root_dir: Path) -> Path:
    return (root_dir / OPML_FILENAME).resolve()


def read_youtube_subscriptions(root_dir: Path) -> list[dict[str, str]]:
    path = opml_path(root_dir)
    if path.parent != (root_dir / "feeds").resolve() or path.name != "follow.opml":
        raise ValueError("invalid_opml_path")
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    subscriptions: list[dict[str, str]] = []
    seen: set[str] = set()
    for outline in root.findall(".//outline"):
        xml_url = str(outline.attrib.get("xmlUrl") or "").strip()
        channel_id = youtube_channel_id_from_feed_url(xml_url)
        if not channel_id or channel_id in seen:
            continue
        seen.add(channel_id)
        title = str(outline.attrib.get("title") or outline.attrib.get("text") or channel_id).strip()
        subscriptions.append(
            {
                "title": title,
                "channel_id": channel_id,
                "xml_url": youtube_feed_url(channel_id),
                "html_url": str(outline.attrib.get("htmlUrl") or "").strip(),
            }
        )
    return subscriptions


def write_youtube_subscriptions(root_dir: Path, raw_subscriptions: Any) -> list[dict[str, str]]:
    if not isinstance(raw_subscriptions, list):
        raise ValueError("subscriptions must be an array")
    if len(raw_subscriptions) > 200:
        raise ValueError("too many subscriptions")
    subscriptions: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_subscriptions):
        if not isinstance(item, dict):
            raise ValueError(f"subscriptions[{index}] must be an object")
        subscription = validate_youtube_subscription(item, index)
        if subscription["channel_id"] in seen:
            continue
        seen.add(subscription["channel_id"])
        subscriptions.append(subscription)

    path = opml_path(root_dir)
    if path.parent != (root_dir / "feeds").resolve() or path.name != "follow.opml":
        raise ValueError("invalid_opml_path")
    path.parent.mkdir(parents=True, exist_ok=True)
    opml = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(opml, "head")
    title = ET.SubElement(head, "title")
    title.text = "AI News Radar Personal Subscriptions"
    body = ET.SubElement(opml, "body")
    for subscription in subscriptions:
        ET.SubElement(
            body,
            "outline",
            {
                "text": subscription["title"],
                "title": subscription["title"],
                "type": "rss",
                "xmlUrl": subscription["xml_url"],
                "htmlUrl": subscription["html_url"],
            },
        )
    tree = ET.ElementTree(opml)
    ET.indent(tree, space="  ")
    tmp_path = path.with_suffix(".opml.tmp")
    tree.write(tmp_path, encoding="utf-8", xml_declaration=True)
    os.replace(tmp_path, path)
    return subscriptions


def read_source_config(root_dir: Path) -> dict[str, Any] | None:
    path = root_dir / CONFIG_FILENAME
    if not path.exists():
        return None
    return validate_source_config(json.loads(path.read_text(encoding="utf-8")))


def source_config_runtime_ids(source: dict[str, Any]) -> set[str]:
    raw_id = str(source.get("id") or "").strip().lower()
    raw_type = str(source.get("type") or "").strip().lower()
    channel = str(source.get("channel") or "").lower()
    target = str(source.get("target") or "").lower()
    locator = str(source.get("locator") or "").lower()
    haystack = f"{raw_id} {raw_type} {channel} {target} {locator}"
    runtime_ids: set[str] = set()
    if raw_type == "wewe_rss" or raw_id.startswith("wewe_rss") or "wewe_rss" in haystack or "wewe rss" in haystack:
        runtime_ids.add("wewe_rss")
    if raw_type == "bilibili_dynamic" or "bilibili" in haystack or "b站" in haystack:
        runtime_ids.add("bilibili_dynamic")
    if raw_type in {"rss", "opml"} or "youtube.com/feeds/videos.xml" in haystack or "youtube" in haystack or "油管" in haystack:
        runtime_ids.add("opmlrss")
    if "github" in haystack and ("release" in haystack or "releases" in haystack):
        runtime_ids.add("github_foundation_sunshine_releases")
    if raw_type == "mediacrawler_jsonl":
        if "xhs" in haystack or "xiaohongshu" in haystack or "小红书" in haystack:
            runtime_ids.add("mediacrawler_xhs")
        if "douyin" in haystack or "抖音" in haystack:
            runtime_ids.add("mediacrawler_douyin")
    return runtime_ids


PURGE_TRACKED_SITE_IDS = frozenset(
    {
        "wewe_rss",
        "bilibili_dynamic",
        "mediacrawler_douyin",
        "mediacrawler_xhs",
        "github_foundation_sunshine_releases",
    }
)


def purge_tracked_site_ids(source: dict[str, Any]) -> set[str]:
    ids = set(source_config_runtime_ids(source))
    if str(source.get("type") or "").strip().lower() == "github_release":
        ids.add("github_foundation_sunshine_releases")
    return ids & PURGE_TRACKED_SITE_IDS


def source_identity_names(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    identities: dict[str, dict[str, str]] = {site_id: {} for site_id in PURGE_TRACKED_SITE_IDS}
    sources = config.get("sources") if isinstance(config, dict) else None
    if not isinstance(sources, list):
        return identities
    for source in sources:
        if not isinstance(source, dict):
            continue
        site_ids = purge_tracked_site_ids(source)
        if not site_ids:
            continue
        if "bilibili_dynamic" in site_ids:
            names = [part.strip() for part in str(source.get("target") or "").split(",")]
            locators = [part.strip() for part in str(source.get("locator") or "").split(",")]
            for index in range(max(len(names), len(locators))):
                locator = locators[index] if index < len(locators) else ""
                identity_key = locator or (names[index] if index < len(names) else "")
                if not identity_key:
                    continue
                name = names[index] if index < len(names) and names[index] else locator
                identities["bilibili_dynamic"][identity_key] = name
        for site_id in site_ids:
            if site_id == "bilibili_dynamic":
                continue
            record_id = str(source.get("id") or "").strip()
            display = str(source.get("target") or source.get("name") or "").strip()
            if record_id and display:
                identities[site_id][record_id] = display
    return identities


def alive_source_names_by_site(
    config: dict[str, Any],
    previous_config: dict[str, Any] | None = None,
) -> dict[str, set[str]]:
    current = source_identity_names(config)
    previous = source_identity_names(previous_config) if previous_config else {}
    alive: dict[str, set[str]] = {}
    for site_id in PURGE_TRACKED_SITE_IDS:
        names = set(current.get(site_id, {}).values())
        for identity_key, old_name in previous.get(site_id, {}).items():
            if identity_key in current.get(site_id, {}):
                names.add(old_name)
        alive[site_id] = names
    return alive


def is_item_orphaned(record: dict[str, Any], alive_names: dict[str, set[str]]) -> bool:
    site_id = str(record.get("site_id") or "").strip()
    if site_id not in alive_names:
        return False
    source_name = str(record.get("source") or "").strip()
    return source_name not in alive_names[site_id]


def purge_orphaned_from_flat_list(
    items: list[Any],
    alive_names: dict[str, set[str]],
) -> tuple[list[Any], int]:
    kept = [item for item in items if not (isinstance(item, dict) and is_item_orphaned(item, alive_names))]
    return kept, len(items) - len(kept)


def purge_orphaned_from_story_list(
    stories: list[Any],
    alive_names: dict[str, set[str]],
) -> tuple[list[Any], int]:
    kept = []
    removed = 0
    for story in stories:
        if not isinstance(story, dict):
            kept.append(story)
            continue
        members = story.get("items")
        if not isinstance(members, list):
            members = story.get("sources") if isinstance(story.get("sources"), list) else []
        if any(isinstance(member, dict) and is_item_orphaned(member, alive_names) for member in members):
            removed += 1
            continue
        kept.append(story)
    return kept, removed


def write_json_atomic(path: Path, payload: Any, *, compact: bool) -> None:
    text = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if compact
        else json.dumps(payload, ensure_ascii=False, indent=2)
    )
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def purge_deleted_source_data(
    root_dir: Path,
    config: dict[str, Any],
    *,
    previous_config: dict[str, Any] | None = None,
) -> dict[str, int]:
    alive_names = alive_source_names_by_site(config, previous_config)
    data_dir = root_dir / "data"
    summary: dict[str, int] = {}

    def rewrite_flat(filename: str, list_keys: tuple[str, ...], *, compact: bool) -> None:
        path = data_dir / filename
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        removed_total = 0
        for key in list_keys:
            items = payload.get(key)
            if not isinstance(items, list):
                continue
            kept, removed = purge_orphaned_from_flat_list(items, alive_names)
            payload[key] = kept
            removed_total += removed
        if "total_items" in payload and "items" in list_keys:
            payload["total_items"] = len(payload.get("items") or [])
        if removed_total:
            write_json_atomic(path, payload, compact=compact)
        summary[filename] = removed_total

    def rewrite_stories(filename: str, list_key: str, total_key: str, *, compact: bool) -> None:
        path = data_dir / filename
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict) or not isinstance(payload.get(list_key), list):
            return
        kept, removed = purge_orphaned_from_story_list(payload[list_key], alive_names)
        payload[list_key] = kept
        if total_key in payload:
            payload[total_key] = len(kept)
        if removed:
            write_json_atomic(path, payload, compact=compact)
        summary[filename] = removed

    rewrite_flat("archive.json", ("items",), compact=True)
    rewrite_flat(
        "latest-24h.json",
        ("items", "items_ai", "creator_items_ai", "creator_items_all"),
        compact=False,
    )
    rewrite_flat(
        "latest-24h-all.json",
        ("items_all", "items_all_raw", "creator_items_all"),
        compact=True,
    )
    rewrite_stories("stories-merged.json", "stories", "total_stories", compact=True)
    rewrite_stories("daily-brief.json", "items", "total_items", compact=False)
    return summary


def enabled_source_config_records(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not config:
        return []
    sources = config.get("sources")
    if not isinstance(sources, list):
        return []
    return [source for source in sources if isinstance(source, dict) and source.get("enabled") is not False]


def resolve_config_path(root_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = root_dir / path
    return path



