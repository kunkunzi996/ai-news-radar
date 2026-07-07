from __future__ import annotations

from email.utils import parseaddr
import hashlib
import os
from typing import Any

import requests

from scripts.radar.common import (
    AGENTMAIL_API_BASE_DEFAULT,
    AGENTMAIL_DEFAULT_LIMIT,
    AI_KEYWORDS,
    BROAD_AI_TERMS,
    MEANINGFUL_EN_SIGNAL_RE,
    compact_public_snippet,
    env_flag,
    env_int,
    parse_domain_filter,
    sanitize_public_payload,
)

"""AgentMail digest fetcher and public payload sanitizers."""

def contains_any_keyword(haystack: str, keywords: list[str]) -> bool:
    h = haystack.lower()
    return any(k in h for k in keywords)


def contains_meaningful_ai_signal(haystack: str) -> bool:
    h = haystack.lower()
    if MEANINGFUL_EN_SIGNAL_RE.search(h):
        return True
    return any(k in h for k in AI_KEYWORDS if k not in BROAD_AI_TERMS)


def sender_domain_from_address(raw_sender: str) -> str | None:
    """Extract only the sender domain; never expose the raw email address."""
    _, email_addr = parseaddr(str(raw_sender or ""))
    if "@" not in email_addr:
        return None
    domain = email_addr.rsplit("@", 1)[-1].strip().lower().strip(">")
    return domain or None


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


def maybe_fetch_agentmail_digest(
    session: requests.Session,
    generated_at: str,
    after: str,
    window_hours: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Fetch AgentMail only when explicitly enabled and fully configured."""
    status: dict[str, Any] = {
        "enabled": env_flag("EMAIL_DIGEST_ENABLED"),
        "ok": None,
        "item_count": 0,
        "privacy": "metadata_only_no_body",
        "published_by_default": False,
    }
    if not status["enabled"]:
        return None, status

    agentmail_api_key = str(os.environ.get("AGENTMAIL_API_KEY") or "").strip()
    agentmail_inbox_id = str(os.environ.get("AGENTMAIL_INBOX_ID") or "").strip()
    agentmail_base_url = str(os.environ.get("AGENTMAIL_API_BASE_URL") or AGENTMAIL_API_BASE_DEFAULT).strip()
    agentmail_limit = env_int("AGENTMAIL_LIMIT", AGENTMAIL_DEFAULT_LIMIT)
    allowed_sender_domains = parse_domain_filter(str(os.environ.get("AGENTMAIL_ALLOWED_SENDER_DOMAINS") or ""))
    status["allowed_sender_domains"] = allowed_sender_domains
    if not (agentmail_api_key and agentmail_inbox_id):
        status["ok"] = False
        status["error"] = "missing_agentmail_credentials"
        return None, status

    try:
        payload = fetch_agentmail_digest(
            session,
            api_key=agentmail_api_key,
            inbox_id=agentmail_inbox_id,
            generated_at=generated_at,
            after=after,
            limit=agentmail_limit,
            base_url=agentmail_base_url,
            window_hours=window_hours,
            allowed_sender_domains=allowed_sender_domains,
        )
        status["ok"] = True
        status["item_count"] = int(payload.get("total_messages") or 0)
        return payload, status
    except Exception as exc:
        status["ok"] = False
        status["error"] = type(exc).__name__
        return None, status

