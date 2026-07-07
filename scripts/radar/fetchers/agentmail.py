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

"""AgentMail digest fetcher and public payload sanitizers."""

def contains_any_keyword(haystack: str, keywords: list[str]) -> bool:
    h = haystack.lower()
    return any(k in h for k in keywords)


def contains_meaningful_ai_signal(haystack: str) -> bool:
    h = haystack.lower()
    if MEANINGFUL_EN_SIGNAL_RE.search(h):
        return True
    return any(k in h for k in AI_KEYWORDS if k not in BROAD_AI_TERMS)


def redact_public_text(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    text = EMAIL_RE.sub("[redacted-email]", text)
    text = URL_IN_TEXT_RE.sub(lambda match: normalize_url(match.group(0)), text)
    return SECRET_LIKE_RE.sub("[redacted-secret]", text)


def sanitize_public_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_public_text(value)
    if isinstance(value, list):
        return [sanitize_public_value(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_public_value(val) for key, val in value.items()}
    return value


def sanitize_public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return sanitize_public_value(payload)


def compact_public_snippet(text: str, max_chars: int = 240) -> str:
    """Return a short redacted snippet suitable for public/static JSON."""
    snippet = re.sub(r"\s+", " ", str(text or "")).strip()
    snippet = redact_public_text(snippet)
    if len(snippet) <= max_chars:
        return snippet
    return snippet[: max_chars - 1].rstrip() + "…"


def sender_domain_from_address(raw_sender: str) -> str | None:
    """Extract only the sender domain; never expose the raw email address."""
    _, email_addr = parseaddr(str(raw_sender or ""))
    if "@" not in email_addr:
        return None
    domain = email_addr.rsplit("@", 1)[-1].strip().lower().strip(">")
    return domain or None


def parse_domain_filter(raw: str) -> list[str]:
    """Parse a comma-separated sender-domain allowlist for private newsletter demos."""
    domains: list[str] = []
    for part in re.split(r"[,\s]+", str(raw or "")):
        domain = part.strip().lower().lstrip("@")
        if domain and re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", domain):
            domains.append(domain)
    return sorted(set(domains))


def domain_matches_filter(sender_domain: str | None, allowed_domains: list[str]) -> bool:
    if not allowed_domains:
        return True
    domain = str(sender_domain or "").lower().strip()
    return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in allowed_domains)


def filter_agentmail_messages_by_domain(
    messages: list[dict[str, Any]],
    allowed_domains: list[str],
) -> list[dict[str, Any]]:
    if not allowed_domains:
        return messages
    return [
        msg
        for msg in messages
        if domain_matches_filter(sender_domain_from_address(str(msg.get("from") or "")), allowed_domains)
    ]


def safe_agentmail_item(message: dict[str, Any]) -> dict[str, Any]:
    """Convert an AgentMail MessageItem into a metadata-only public digest item."""
    message_id = str(message.get("message_id") or "")
    stable_id = hashlib.sha1(message_id.encode("utf-8")).hexdigest()[:12] if message_id else "unknown"
    domain = sender_domain_from_address(str(message.get("from") or ""))
    attachments = message.get("attachments") or []
    return {
        "id": f"agentmail:{stable_id}",
        "source_type": "email_newsletter",
        "source": f"AgentMail · {domain}" if domain else "AgentMail",
        "sender_domain": domain,
        "subject": compact_public_snippet(str(message.get("subject") or ""), max_chars=180),
        "preview": compact_public_snippet(str(message.get("preview") or ""), max_chars=240),
        "received_at": message.get("timestamp") or message.get("created_at"),
        "has_attachments": bool(attachments),
        "attachment_count": len(attachments) if isinstance(attachments, list) else 0,
    }


def build_agentmail_digest_payload(
    messages: list[dict[str, Any]],
    generated_at: str,
    window_hours: int,
    allowed_sender_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Build a privacy-preserving digest from AgentMail list-message results."""
    filtered_messages = filter_agentmail_messages_by_domain(messages, allowed_sender_domains or [])
    items = [safe_agentmail_item(msg) for msg in filtered_messages]
    return sanitize_public_payload(
        {
            "generated_at": generated_at,
            "source": "agentmail",
            "enabled": True,
            "window_hours": window_hours,
            "privacy": "metadata_only_no_body",
            "allowed_sender_domains": allowed_sender_domains or [],
            "total_messages": len(items),
            "items": items,
        }
    )


def fetch_agentmail_digest(
    session: requests.Session,
    api_key: str,
    inbox_id: str,
    generated_at: str,
    after: str,
    limit: int = AGENTMAIL_DEFAULT_LIMIT,
    base_url: str = AGENTMAIL_API_BASE_DEFAULT,
    window_hours: int = 24,
    allowed_sender_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch AgentMail MessageItem metadata; deliberately does not request bodies or raw .eml."""
    base = (base_url or AGENTMAIL_API_BASE_DEFAULT).rstrip("/")
    url = f"{base}/v0/inboxes/{inbox_id}/messages"
    response = session.get(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        params={
            "limit": max(1, min(int(limit or AGENTMAIL_DEFAULT_LIMIT), 100)),
            "after": after,
            "ascending": "false",
            "include_spam": "false",
            "include_trash": "false",
            "include_blocked": "false",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    messages = payload.get("messages") if isinstance(payload, dict) else []
    if not isinstance(messages, list):
        messages = []
    return build_agentmail_digest_payload(
        messages,
        generated_at=generated_at,
        window_hours=window_hours,
        allowed_sender_domains=allowed_sender_domains,
    )



