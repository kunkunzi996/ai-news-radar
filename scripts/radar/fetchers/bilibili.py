from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parseaddr
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scripts.ai_relevance import add_ai_relevance_fields, score_ai_relevance

try:
    import feedparser
except ModuleNotFoundError:
    feedparser = None

from scripts.radar.common import *  # noqa: F401,F403

"""Bilibili dynamic source fetcher."""

def split_env_list(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;\n]+", str(value or "")) if part.strip()]


def bilibili_dynamic_accounts_from_env() -> list[dict[str, str]]:
    uid_list = split_env_list(str(os.environ.get("BILIBILI_DYNAMIC_UIDS") or ""))
    if uid_list:
        source_names = split_env_list(str(os.environ.get("BILIBILI_DYNAMIC_SOURCE_NAMES") or ""))
        return [
            {
                "uid": uid,
                "source_name": source_names[index] if index < len(source_names) else f"Bilibili {uid}",
            }
            for index, uid in enumerate(uid_list)
        ]

    single_uid = str(os.environ.get("BILIBILI_DYNAMIC_UID") or "").strip()
    if single_uid:
        return [
            {
                "uid": single_uid,
                "source_name": str(
                    os.environ.get("BILIBILI_DYNAMIC_SOURCE_NAME")
                    or f"Bilibili {single_uid}"
                ).strip(),
            }
        ]

    return [
        {"uid": uid, "source_name": source_name}
        for uid, source_name in BILIBILI_DYNAMIC_DEFAULT_ACCOUNTS
    ]


def bilibili_dynamic_status_base() -> dict[str, Any]:
    accounts = bilibili_dynamic_accounts_from_env()
    uids = [account["uid"] for account in accounts if account.get("uid")]
    max_items = max(1, min(env_int("BILIBILI_DYNAMIC_MAX_ITEMS", BILIBILI_DYNAMIC_DEFAULT_MAX_ITEMS), 200))
    max_pages = max(1, min(env_int("BILIBILI_DYNAMIC_MAX_PAGES", BILIBILI_DYNAMIC_DEFAULT_MAX_PAGES), 20))
    cookie_present = bool(bilibili_cookie_header_from_env())
    return {
        "enabled": env_flag("BILIBILI_DYNAMIC_ENABLED"),
        "ok": None,
        "item_count": 0,
        "uid": ",".join(uids),
        "uids": uids,
        "uid_count": len(uids),
        "accounts": accounts,
        "max_items": max_items,
        "max_items_per_account": max_items,
        "max_pages": max_pages,
        "source_kind": "bilibili_dynamic",
        "cookie_present": cookie_present,
        "privacy": "cookie_env_only_not_logged",
        "coverage_note": "tries_cookie_full_dynamic_then_public_opus_fallback",
    }


def bilibili_dynamic_item_title(content: str, opus_id: str) -> str:
    text = re.sub(r"\s+", " ", (content or "").strip())
    if not text:
        return f"B站动态 {opus_id}".strip()
    if len(text) > 90:
        text = text[:87].rstrip() + "..."
    return text


def apply_cookie_header(session: requests.Session, cookie_header: str) -> None:
    for part in str(cookie_header or "").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            session.cookies.set(name, value, domain=".bilibili.com")


def bilibili_cookie_header_from_file_text(cookie_text: str, now_ts: int | None = None) -> str:
    now_ts = now_ts or int(time.time())
    cookies: dict[str, str] = {}

    def keep_cookie(name: str, value: str, domain: str = "", expires: Any = None) -> None:
        if not name or value is None:
            return
        if domain and "bilibili.com" not in domain:
            return
        try:
            exp = float(expires) if expires not in (None, "") else 0
            if exp > 20_000_000_000:
                exp = exp / 1000
            if exp > 0 and exp < now_ts:
                return
        except (TypeError, ValueError):
            pass
        cookies[str(name).strip()] = str(value).strip()

    text = str(cookie_text or "").strip()
    if not text:
        return ""

    try:
        payload = json.loads(text)
        raw_items = payload.get("cookies") if isinstance(payload, dict) else payload
        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                keep_cookie(
                    str(item.get("name") or ""),
                    str(item.get("value") or ""),
                    str(item.get("domain") or ""),
                    item.get("expirationDate") or item.get("expires") or item.get("expiry"),
                )
            if cookies:
                return "; ".join(f"{name}={value}" for name, value in cookies.items())
    except json.JSONDecodeError:
        pass

    # Netscape cookie.txt format: domain, include_subdomains, path, secure,
    # expiry, name, value separated by tabs.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#HttpOnly_"):
            stripped = stripped[len("#HttpOnly_") :]
        elif stripped.startswith("#"):
            continue
        parts = stripped.split("\t")
        if len(parts) >= 7:
            keep_cookie(parts[5], parts[6], parts[0], parts[4])
    if cookies:
        return "; ".join(f"{name}={value}" for name, value in cookies.items())

    if "=" in text:
        return text
    return ""


def bilibili_cookie_header_from_env() -> str:
    cookie = str(os.environ.get("BILIBILI_COOKIE") or os.environ.get("BILIBILI_DYNAMIC_COOKIE") or "").strip()
    if cookie:
        return bilibili_cookie_header_from_file_text(cookie).strip() or cookie
    cookie_file = str(os.environ.get("BILIBILI_COOKIE_FILE") or os.environ.get("BILIBILI_DYNAMIC_COOKIE_FILE") or "").strip()
    if not cookie_file:
        return ""
    try:
        return bilibili_cookie_header_from_file_text(Path(cookie_file).read_text(encoding="utf-8", errors="ignore")).strip()
    except OSError:
        return ""


def bilibili_mixin_key(img_key: str, sub_key: str) -> str:
    raw = f"{img_key}{sub_key}"
    return "".join(raw[i] for i in BILIBILI_WBI_MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def bilibili_wbi_keys(session: requests.Session) -> tuple[str, str]:
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.bilibili.com/",
    }
    resp = session.get(BILIBILI_NAV_API_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"bilibili_nav_code_{payload.get('code')}")
    wbi_img = data.get("wbi_img")
    if not isinstance(wbi_img, dict):
        raise ValueError("bilibili_nav_missing_wbi_img")
    img_key = str(wbi_img.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
    sub_key = str(wbi_img.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
    if not (img_key and sub_key):
        raise ValueError("bilibili_nav_missing_wbi_keys")
    return img_key, sub_key


def sign_bilibili_wbi_params(params: dict[str, Any], img_key: str, sub_key: str, now_ts: int | None = None) -> dict[str, str]:
    signed = {k: str(v) for k, v in params.items() if v is not None}
    signed["wts"] = str(now_ts or int(time.time()))
    cleaned = {
        k: re.sub(r"[!'()*]", "", v)
        for k, v in signed.items()
    }
    query = urlencode(sorted(cleaned.items()))
    cleaned["w_rid"] = hashlib.md5(f"{query}{bilibili_mixin_key(img_key, sub_key)}".encode("utf-8")).hexdigest()
    return cleaned


def first_text_value(obj: Any, keys: tuple[str, ...] = ("text", "title", "desc", "content")) -> str:
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in obj.values():
            found = first_text_value(value, keys)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = first_text_value(value, keys)
            if found:
                return found
    return ""


def bilibili_author_from_detail_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    item = data.get("item")
    if not isinstance(item, dict):
        return {}
    modules = item.get("modules")
    if isinstance(modules, dict):
        author = modules.get("module_author")
        return author if isinstance(author, dict) else {}
    if isinstance(modules, list):
        for module in modules:
            if not isinstance(module, dict):
                continue
            author = module.get("module_author")
            if isinstance(author, dict):
                return author
    return {}


def parse_bilibili_detail_published_at(payload: dict[str, Any]) -> datetime | None:
    author = bilibili_author_from_detail_payload(payload)
    return parse_unix_timestamp(author.get("pub_ts"))


def fetch_bilibili_opus_published_at(
    session: requests.Session,
    opus_id: str,
    *,
    api_url: str = BILIBILI_DYNAMIC_DETAIL_API_URL,
) -> datetime | None:
    oid = str(opus_id or "").strip()
    if not oid:
        return None
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://www.bilibili.com",
        "Referer": f"https://www.bilibili.com/opus/{oid}",
    }
    api_urls = [api_url]
    if api_url != BILIBILI_DYNAMIC_OPUS_DETAIL_API_URL:
        api_urls.append(BILIBILI_DYNAMIC_OPUS_DETAIL_API_URL)
    last_error: Exception | None = None
    for candidate_url in api_urls:
        try:
            resp = session.get(candidate_url, params={"id": oid}, headers=headers, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            if int(payload.get("code") or 0) != 0:
                raise ValueError(f"bilibili_dynamic_detail_api_code_{payload.get('code')}")
            return parse_bilibili_detail_published_at(payload)
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return None


def bilibili_dynamic_publish_times_from_detail(
    session: requests.Session,
    raw_items: list[Any],
    *,
    max_items: int,
) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    checked = 0
    for item in raw_items:
        if checked >= max_items:
            break
        if not isinstance(item, dict):
            continue
        opus_id = str(item.get("opus_id") or "").strip()
        if not opus_id or opus_id in out:
            continue
        checked += 1
        try:
            published = fetch_bilibili_opus_published_at(session, opus_id)
        except Exception:
            continue
        if published:
            out[opus_id] = published
    return out


def bilibili_opus_id_from_record(record: dict[str, Any]) -> str:
    explicit = str(record.get("bilibili_opus_id") or "").strip()
    if explicit:
        return explicit
    url = str(record.get("url") or "").strip()
    match = re.search(r"/opus/(\d+)", url)
    return match.group(1) if match else ""


def backfill_bilibili_archive_publish_times(
    session: requests.Session,
    archive: dict[str, dict[str, Any]],
    *,
    max_items: int = BILIBILI_DYNAMIC_BACKFILL_MAX_ITEMS,
) -> int:
    filled = 0
    checked = 0
    for record in archive.values():
        if checked >= max_items:
            break
        if str(record.get("site_id") or "") != "bilibili_dynamic":
            continue
        if record.get("published_at"):
            continue
        opus_id = bilibili_opus_id_from_record(record)
        if not opus_id:
            continue
        checked += 1
        try:
            published = fetch_bilibili_opus_published_at(session, opus_id)
        except Exception:
            continue
        if not published:
            continue
        record["published_at"] = iso(published)
        record["timestamp_source"] = "bilibili_opus_detail_pub_ts"
        filled += 1
    return filled


def parse_bilibili_full_dynamic_items(
    payload: dict[str, Any],
    *,
    now: datetime,
    uid: str,
    source_name: str,
    max_items: int,
) -> list[RawItem]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return []

    out: list[RawItem] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        dynamic_id = str(item.get("id_str") or item.get("id") or "").strip()
        modules = item.get("modules") if isinstance(item.get("modules"), dict) else {}
        author = modules.get("module_author") if isinstance(modules.get("module_author"), dict) else {}
        dynamic = modules.get("module_dynamic") if isinstance(modules.get("module_dynamic"), dict) else {}
        major = dynamic.get("major") if isinstance(dynamic.get("major"), dict) else {}

        published = parse_unix_timestamp(author.get("pub_ts"))
        dyn_type = str(item.get("type") or "").strip()
        content = first_text_value(dynamic) or first_text_value(item)

        url = ""
        if isinstance(major, dict):
            url = str(major.get("jump_url") or "").strip()
            if not url:
                for value in major.values():
                    if isinstance(value, dict) and value.get("jump_url"):
                        url = str(value.get("jump_url") or "").strip()
                        break
        if not url and dynamic_id:
            url = f"https://t.bilibili.com/{dynamic_id}"
        url = urljoin("https://www.bilibili.com", url)
        if not url or not content:
            continue
        key = dynamic_id or normalize_url(url)
        if key in seen:
            continue
        seen.add(key)

        out.append(
            RawItem(
                site_id="bilibili_dynamic",
                site_name="Bilibili Dynamic",
                source=source_name,
                title=bilibili_dynamic_item_title(content, dynamic_id),
                url=url,
                published_at=published or now,
                meta={
                    "summary": content,
                    "bilibili_uid": uid,
                    "bilibili_dynamic_id": dynamic_id,
                    "bilibili_dynamic_type": dyn_type,
                    "timestamp_source": "bilibili_pub_ts" if published else "fetch_time",
                },
            )
        )
        if len(out) >= max_items:
            break
    return out


def parse_bilibili_dynamic_items(
    payload: dict[str, Any],
    *,
    now: datetime,
    uid: str,
    source_name: str,
    max_items: int,
    published_at_by_opus: dict[str, datetime] | None = None,
) -> list[RawItem]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return []

    out: list[RawItem] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        opus_id = str(item.get("opus_id") or "").strip()
        content = str(item.get("content") or "").strip()
        jump_url = str(item.get("jump_url") or "").strip()
        if not opus_id and not jump_url:
            continue
        url = urljoin("https://www.bilibili.com", jump_url or f"/opus/{opus_id}")
        key = opus_id or normalize_url(url)
        if key in seen:
            continue
        seen.add(key)

        stat = item.get("stat")
        like_count = None
        if isinstance(stat, dict):
            like_count = stat.get("like")
        cover = item.get("cover") if isinstance(item.get("cover"), dict) else {}
        published = (published_at_by_opus or {}).get(opus_id)

        out.append(
            RawItem(
                site_id="bilibili_dynamic",
                site_name="Bilibili Dynamic",
                source=source_name,
                title=bilibili_dynamic_item_title(content, opus_id),
                url=url,
                published_at=published,
                meta={
                    "summary": content,
                    "creator_metrics": {"like_count": like_count} if like_count is not None else None,
                    "bilibili_uid": uid,
                    "bilibili_opus_id": opus_id,
                    "cover_url": cover.get("url") if isinstance(cover, dict) else None,
                    "timestamp_source": "bilibili_opus_detail_pub_ts" if published else "first_seen_at",
                },
            )
        )
        if len(out) >= max_items:
            break
    return out


def fetch_bilibili_dynamic(
    session: requests.Session,
    now: datetime,
    *,
    uid: str,
    source_name: str,
    max_items: int,
    api_url: str = BILIBILI_DYNAMIC_API_URL,
) -> list[RawItem]:
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://space.bilibili.com",
        "Referer": f"https://space.bilibili.com/{uid}/dynamic",
    }
    resp = session.get(
        api_url,
        params={
            "host_mid": uid,
            "page": 1,
            "type": "all",
            "web_location": "333.1387",
        },
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if int(payload.get("code") or 0) != 0:
        raise ValueError(f"bilibili_dynamic_api_code_{payload.get('code')}")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    raw_items = data.get("items") if isinstance(data.get("items"), list) else []
    published_at_by_opus = bilibili_dynamic_publish_times_from_detail(
        session,
        raw_items,
        max_items=max_items,
    )
    items = parse_bilibili_dynamic_items(
        payload,
        now=now,
        uid=uid,
        source_name=source_name,
        max_items=max_items,
        published_at_by_opus=published_at_by_opus,
    )
    if not items:
        raise ValueError("bilibili_dynamic_no_items")
    return items


def fetch_bilibili_full_dynamic(
    session: requests.Session,
    now: datetime,
    *,
    uid: str,
    source_name: str,
    max_items: int,
    max_pages: int = 1,
    api_url: str = BILIBILI_DYNAMIC_FULL_API_URL,
) -> list[RawItem]:
    img_key, sub_key = bilibili_wbi_keys(session)
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://space.bilibili.com",
        "Referer": f"https://space.bilibili.com/{uid}/dynamic",
    }
    out: list[RawItem] = []
    seen: set[str] = set()
    offset = ""
    for page_index in range(max(1, max_pages)):
        raw_params: dict[str, Any] = {
            "host_mid": uid,
            "timezone_offset": -480,
            "features": "itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,decorationCard,forwardListHidden,ugcDelete",
            "web_location": "333.1387",
        }
        if offset:
            raw_params["offset"] = offset
        params = sign_bilibili_wbi_params(raw_params, img_key, sub_key)
        resp = session.get(api_url, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        if int(payload.get("code") or 0) != 0:
            raise ValueError(f"bilibili_full_dynamic_api_code_{payload.get('code')}")

        remaining = max_items - len(out)
        items = parse_bilibili_full_dynamic_items(
            payload,
            now=now,
            uid=uid,
            source_name=source_name,
            max_items=remaining,
        )
        for item in items:
            key = str(item.meta.get("bilibili_dynamic_id") if isinstance(item.meta, dict) else "") or normalize_url(item.url)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        if len(out) >= max_items:
            break

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not data.get("has_more"):
            break
        next_offset = str(data.get("offset") or "").strip()
        if not next_offset or next_offset == offset:
            break
        offset = next_offset
        if page_index + 1 < max_pages:
            time.sleep(0.25)

    if not out:
        raise ValueError("bilibili_full_dynamic_no_items")
    return out


def maybe_fetch_bilibili_dynamic(
    session: requests.Session,
    now: datetime,
) -> tuple[list[RawItem], dict[str, Any]]:
    status = bilibili_dynamic_status_base()
    if not status["enabled"]:
        status["disabled_reason"] = "disabled_by_toggle"
        return [], status
    accounts = [
        account
        for account in status.get("accounts", [])
        if isinstance(account, dict) and str(account.get("uid") or "").strip()
    ]
    if not accounts:
        status["ok"] = False
        status["error"] = "missing_bilibili_dynamic_uid"
        return [], status

    api_url = str(os.environ.get("BILIBILI_DYNAMIC_API_URL") or BILIBILI_DYNAMIC_API_URL).strip()
    full_api_url = str(os.environ.get("BILIBILI_DYNAMIC_FULL_API_URL") or BILIBILI_DYNAMIC_FULL_API_URL).strip()
    cookie = bilibili_cookie_header_from_env()
    status["source_name"] = ", ".join(str(account.get("source_name") or account["uid"]) for account in accounts)
    status["attempted"] = True
    start = time.perf_counter()
    try:
        if cookie:
            apply_cookie_header(session, cookie)

        all_items: list[RawItem] = []
        account_statuses: list[dict[str, Any]] = []
        for account in accounts:
            uid = str(account.get("uid") or "").strip()
            source_name = str(account.get("source_name") or f"Bilibili {uid}").strip()
            account_status: dict[str, Any] = {
                "uid": uid,
                "source_name": source_name,
                "ok": False,
                "item_count": 0,
            }
            try:
                errors: list[str] = []
                if cookie:
                    try:
                        items = fetch_bilibili_full_dynamic(
                            session,
                            now,
                            uid=uid,
                            source_name=source_name,
                            max_items=int(status["max_items_per_account"]),
                            max_pages=int(status["max_pages"]),
                            api_url=full_api_url,
                        )
                        account_status["fetch_mode"] = "cookie_full_dynamic"
                        account_status["ok"] = True
                        account_status["item_count"] = len(items)
                        all_items.extend(items)
                        account_statuses.append(account_status)
                        continue
                    except Exception as exc:
                        errors.append(f"cookie_full_dynamic_failed:{type(exc).__name__}")

                items = fetch_bilibili_dynamic(
                    session,
                    now,
                    uid=uid,
                    source_name=source_name,
                    max_items=int(status["max_items_per_account"]),
                    api_url=api_url,
                )
                account_status["fetch_mode"] = "public_opus_fallback" if errors else "public_opus"
                if errors:
                    account_status["fallback_reason"] = errors[-1]
                account_status["ok"] = True
                account_status["item_count"] = len(items)
                all_items.extend(items)
            except Exception as exc:
                account_status["error"] = str(exc)
            account_statuses.append(account_status)

        status["accounts"] = account_statuses
        status["item_count"] = len(all_items)
        successful_accounts = [account for account in account_statuses if account.get("ok")]
        failed_accounts = [account for account in account_statuses if not account.get("ok")]
        status["ok"] = bool(successful_accounts)
        status["partial_failure_count"] = len(failed_accounts) if successful_accounts else 0

        fetch_modes = sorted(
            {
                str(account.get("fetch_mode"))
                for account in successful_accounts
                if account.get("fetch_mode")
            }
        )
        if len(fetch_modes) == 1:
            status["fetch_mode"] = fetch_modes[0]
        elif fetch_modes:
            status["fetch_mode"] = "mixed"
        fallback_reasons = [
            f"{account.get('uid')}:{account.get('fallback_reason')}"
            for account in account_statuses
            if account.get("fallback_reason")
        ]
        if fallback_reasons:
            status["fallback_reason"] = "; ".join(fallback_reasons)
        if not successful_accounts:
            status["error"] = "; ".join(
                f"{account.get('uid')}:{account.get('error') or 'no_items'}"
                for account in failed_accounts
            ) or "bilibili_dynamic_no_items"
        return all_items, status
    except Exception as exc:
        status["ok"] = False
        status["error"] = str(exc)
        return [], status
    finally:
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)


def mediacrawler_douyin_title(text: str, aweme_id: str) -> str:
    title = re.sub(r"\s+", " ", (text or "").strip())
    if not title:
        return f"抖音作品 {aweme_id}".strip()
    if len(title) > 90:
        title = title[:87].rstrip() + "..."
    return title


def mediacrawler_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def mediacrawler_xhs_title(text: str, note_id: str) -> str:
    title = re.sub(r"\s+", " ", (text or "").strip())
    if not title:
        return f"小红书笔记 {note_id}".strip()
    if len(title) > 90:
        title = title[:87].rstrip() + "..."
    return title


def mediacrawler_env_first(*names: str) -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def mediacrawler_env_flag_any(*names: str) -> bool:
    return any(env_flag(name) for name in names)


def mediacrawler_env_int_any(default: int, *names: str) -> int:
    for name in names:
        if str(os.environ.get(name) or "").strip():
            return env_int(name, default)
    return default


def mediacrawler_local_root() -> Path:
    configured = str(os.environ.get("MEDIACRAWLER_LOCAL_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "MediaCrawler-local-test"


def is_url_like(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def default_mediacrawler_jsonl_dir(site_id: str) -> Path:
    folder = "xhs" if site_id == MEDIACRAWLER_XHS_SITE_ID else "douyin"
    return mediacrawler_local_root() / "output" / folder / "jsonl"


def mediacrawler_jsonl_locator(raw_locator: str, site_id: str) -> str:
    locator = str(raw_locator or "").strip()
    if not locator or is_url_like(locator):
        return str(default_mediacrawler_jsonl_dir(site_id))
    return locator


def resolve_latest_mediacrawler_jsonl(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_dir():
        candidates = sorted(
            path.glob("creator_contents_*.jsonl"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        non_empty_candidates = [candidate for candidate in candidates if candidate.stat().st_size > 0]
        if non_empty_candidates:
            return non_empty_candidates[0]
        return candidates[0] if candidates else path

    if path.parent.exists() and (not path.exists() or path.name.startswith("creator_contents_")):
        candidates = sorted(
            path.parent.glob("creator_contents_*.jsonl"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        non_empty_candidates = [candidate for candidate in candidates if candidate.stat().st_size > 0]
        if non_empty_candidates and (not path.exists() or path.stat().st_size <= 0 or non_empty_candidates[0].stat().st_mtime >= path.stat().st_mtime):
            return non_empty_candidates[0]
        if candidates and (not path.exists() or candidates[0].stat().st_mtime >= path.stat().st_mtime):
            return candidates[0]
    return path


def douyin_sec_uid_from_locator(locator: str) -> str:
    parsed = urlparse(str(locator or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return ""
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part == "user" and index + 1 < len(parts):
            return parts[index + 1].strip()
    return ""


def parse_mediacrawler_douyin_jsonl(
    text: str,
    *,
    now: datetime,
    source_name: str = "",
    max_items: int | None = None,
) -> list[RawItem]:
    out: list[RawItem] = []
    seen: set[str] = set()
    for line in str(text or "").splitlines():
        raw_line = line.strip()
        if not raw_line:
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue

        aweme_id = first_non_empty(row.get("aweme_id"), row.get("id"))
        content = first_non_empty(row.get("desc"), row.get("title"))
        url = first_non_empty(row.get("aweme_url"), row.get("share_url"), row.get("url"))
        if not url and aweme_id:
            url = f"https://www.douyin.com/video/{aweme_id}"
        if not url.startswith("http") or not (content or aweme_id):
            continue

        key = aweme_id or normalize_url(url)
        if key in seen:
            continue
        seen.add(key)

        creator = first_non_empty(
            row.get("nickname"),
            row.get("user_nickname"),
            row.get("user_unique_id"),
            row.get("sec_user_id"),
            source_name,
            "Douyin Creator",
        )
        published = (
            parse_unix_timestamp(row.get("create_time"))
            or parse_unix_timestamp(row.get("create_timestamp"))
            or parse_date_any(row.get("publish_time"), now)
        )
        metrics = {
            "likes": mediacrawler_int(first_non_empty(row.get("liked_count"), row.get("digg_count"))),
            "collects": mediacrawler_int(first_non_empty(row.get("collected_count"), row.get("collect_count"))),
            "comments": mediacrawler_int(row.get("comment_count")),
            "shares": mediacrawler_int(row.get("share_count")),
        }
        sec_user_id = first_non_empty(row.get("sec_uid"), row.get("sec_user_id"), row.get("user_id"))
        out.append(
            RawItem(
                site_id=MEDIACRAWLER_DOUYIN_SITE_ID,
                site_name=MEDIACRAWLER_DOUYIN_SITE_NAME,
                source=creator,
                title=mediacrawler_douyin_title(content, aweme_id),
                url=url,
                published_at=published or now,
                meta={
                    "summary": content,
                    "creator_metrics": metrics,
                    "search_surface": "mediacrawler_douyin_creator_jsonl",
                    "douyin_aweme_id": aweme_id,
                    "douyin_sec_user_id": sec_user_id,
                },
            )
        )
        if max_items and len(out) >= max_items:
            break
    return out


def douyin_item_matches_subscription(item: RawItem, *, locator: str, source_name: str) -> bool:
    expected_sec_uid = douyin_sec_uid_from_locator(locator)
    if expected_sec_uid:
        return str(item.meta.get("douyin_sec_user_id") or "").strip() == expected_sec_uid
    if source_name:
        return str(item.source or "").strip() == source_name
    return True


def xiaohongshu_user_id_from_locator(locator: str) -> str:
    parsed = urlparse(str(locator or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return ""
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part == "profile" and index + 1 < len(parts):
            return parts[index + 1].strip()
    return ""


def maybe_fetch_mediacrawler_douyin(now: datetime) -> tuple[list[RawItem], dict[str, Any]]:
    raw_locator = str(os.environ.get("MEDIACRAWLER_DOUYIN_JSONL") or "").strip()
    jsonl_path_raw = mediacrawler_jsonl_locator(raw_locator, MEDIACRAWLER_DOUYIN_SITE_ID)
    max_items = max(1, min(env_int("MEDIACRAWLER_DOUYIN_MAX_ITEMS", 200), 1000))
    status: dict[str, Any] = {
        "enabled": env_flag("MEDIACRAWLER_DOUYIN_ENABLED"),
        "ok": None,
        "item_count": 0,
        "source_kind": MEDIACRAWLER_DOUYIN_SITE_ID,
        "privacy": "local_jsonl_only_no_cookies",
        "coverage_note": "reads_mediacrawler_douyin_creator_jsonl",
        "jsonl_path_configured": bool(raw_locator or jsonl_path_raw),
        "locator": raw_locator,
        "locator_kind": "homepage_url" if is_url_like(raw_locator) else "jsonl_path",
        "jsonl_file_configured": Path(jsonl_path_raw).name if jsonl_path_raw else None,
        "jsonl_file": Path(jsonl_path_raw).name if jsonl_path_raw else None,
        "max_items": max_items,
    }
    if not status["enabled"]:
        status["disabled_reason"] = "disabled_by_toggle"
        return [], status
    if not jsonl_path_raw:
        status["ok"] = False
        status["error"] = "missing_mediacrawler_douyin_jsonl"
        return [], status

    start = time.perf_counter()
    try:
        jsonl_path = resolve_latest_mediacrawler_jsonl(jsonl_path_raw)
        status["jsonl_file"] = jsonl_path.name
        if jsonl_path.name != status.get("jsonl_file_configured"):
            status["jsonl_file_resolved_from"] = status.get("jsonl_file_configured")
        if not jsonl_path.exists():
            status["ok"] = False
            status["error"] = "mediacrawler_douyin_jsonl_not_found"
            return [], status
        source_name = str(os.environ.get("MEDIACRAWLER_DOUYIN_SOURCE_NAME") or "").strip()
        items = parse_mediacrawler_douyin_jsonl(
            jsonl_path.read_text(encoding="utf-8", errors="ignore"),
            now=now,
            source_name=source_name,
            max_items=max_items,
        )
        status["ok"] = bool(items)
        status["item_count"] = len(items)
        if source_name:
            status["source_name"] = source_name
        if not items:
            status["error"] = "mediacrawler_douyin_no_items"
        return items, status
    except Exception as exc:
        status["ok"] = False
        status["error"] = str(exc)
        return [], status
    finally:
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)



