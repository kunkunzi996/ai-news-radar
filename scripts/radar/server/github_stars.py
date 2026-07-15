from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from requests.utils import parse_header_links
from urllib3.util import Retry

from scripts.radar.server.online_sources import (
    GITHUB_LOGIN_PATTERN,
    ONLINE_OPML_SOURCE_ID,
    normalize_github_repo,
    normalize_github_star_sync,
    normalize_online_source_record,
    online_config_digest,
    positive_integer,
    validate_online_config_schema,
)


GITHUB_API_ROOT = "https://api.github.com"
GITHUB_STAR_LIMIT = 50
ONLINE_SOURCE_LIMIT = 300
GITHUB_NETWORK_BUDGET_SECONDS = 30.0
GITHUB_SOCKET_TIMEOUT_SECONDS = 10.0
GITHUB_RESPONSE_MAX_BYTES = 2 * 1024 * 1024
SUMMARY_KEYS = (
    "added",
    "disabled",
    "re_enabled",
    "adopted",
    "renamed",
    "skipped_manual_disabled",
)
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "AI-News-Radar/0.7 github-star-sync",
    "X-GitHub-Api-Version": "2022-11-28",
}
LEGACY_GITHUB_STAR_NOTE_PATTERN = re.compile(
    r"(?:^|[;\s])managed_by\s*[:=]\s*github_stars(?:$|[;\s])",
    re.IGNORECASE,
)


class GitHubStarsError(ValueError):
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


def _error(code: str, status_code: int, details: dict[str, Any] | None = None) -> GitHubStarsError:
    return GitHubStarsError(code, status_code=status_code, details=details)


def validate_github_username(raw_username: Any) -> str:
    if not isinstance(raw_username, str):
        raise _error("github_username_invalid", 422)
    username = raw_username.strip()
    if not GITHUB_LOGIN_PATTERN.fullmatch(username) or "--" in username:
        raise _error("github_username_invalid", 422)
    return username


def create_github_stars_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=0,
        connect=0,
        read=0,
        redirect=0,
        status=0,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update(GITHUB_HEADERS)
    return session


def _rate_limit_details(headers: Any) -> dict[str, str]:
    safe: dict[str, str] = {}
    candidates = {
        "remaining": "X-RateLimit-Remaining",
        "reset": "X-RateLimit-Reset",
        "retry_after": "Retry-After",
    }
    for output_key, header_name in candidates.items():
        value = str(headers.get(header_name) or "").strip() if headers is not None else ""
        if re.fullmatch(r"\d{1,12}", value):
            safe[output_key] = value
    return safe


def _classify_response_error(
    response: Any,
    payload: Any,
    *,
    not_found_code: str | None,
) -> GitHubStarsError | None:
    try:
        status_code = int(response.status_code)
    except (AttributeError, TypeError, ValueError):
        return _error("github_upstream_invalid_response", 502)
    if status_code == 200:
        return None
    headers = getattr(response, "headers", {})
    details = _rate_limit_details(headers)
    if status_code == 429:
        return _error("github_upstream_rate_limited", 429, details)
    if status_code == 403:
        remaining = str(headers.get("X-RateLimit-Remaining") or "").strip()
        retry_after = str(headers.get("Retry-After") or "").strip()
        message = str(payload.get("message") or "").casefold() if isinstance(payload, dict) else ""
        secondary_evidence = "secondary rate limit" in message or "abuse detection" in message
        if remaining == "0" or bool(retry_after) or secondary_evidence:
            return _error("github_upstream_rate_limited", 429, details)
        return _error("github_upstream_forbidden", 403, details)
    if status_code == 404 and not_found_code:
        return _error(not_found_code, 404)
    return _error("github_upstream_invalid_response", 502)


def _timeout_error(deadline: float, monotonic: Callable[[], float]) -> GitHubStarsError:
    overrun_ms = max(0, int(round((monotonic() - deadline) * 1000)))
    return _error("github_upstream_timeout", 504, {"overrun_ms": overrun_ms})


def _read_bounded_json(
    response: Any,
    *,
    deadline: float,
    monotonic: Callable[[], float],
    max_bytes: int = GITHUB_RESPONSE_MAX_BYTES,
) -> Any:
    content_length = _header_value(getattr(response, "headers", {}), "Content-Length").strip()
    if content_length:
        if not content_length.isdigit() or int(content_length) > max_bytes:
            raise _error("github_upstream_invalid_response", 502)
    iter_content = getattr(response, "iter_content", None)
    if not callable(iter_content):
        raise _error("github_upstream_invalid_response", 502)

    body = bytearray()
    try:
        iterator = iter_content(chunk_size=65536)
        while True:
            if monotonic() >= deadline:
                raise _timeout_error(deadline, monotonic)
            try:
                chunk = next(iterator)
            except StopIteration:
                if monotonic() >= deadline:
                    raise _timeout_error(deadline, monotonic)
                break
            if monotonic() > deadline:
                raise _timeout_error(deadline, monotonic)
            if not isinstance(chunk, (bytes, bytearray)):
                raise _error("github_upstream_invalid_response", 502)
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > max_bytes:
                raise _error("github_upstream_invalid_response", 502)
    except requests.Timeout as exc:
        raise _timeout_error(deadline, monotonic) from exc
    except requests.RequestException as exc:
        raise _error("github_upstream_invalid_response", 502) from exc

    try:
        return json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error("github_upstream_invalid_response", 502) from exc


def _request_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 10.0,
    not_found_code: str | None = None,
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[Any, dict[str, str]]:
    active_deadline = deadline if deadline is not None else monotonic() + GITHUB_NETWORK_BUDGET_SECONDS
    remaining = active_deadline - monotonic()
    if remaining <= 0:
        raise _timeout_error(active_deadline, monotonic)
    request_kwargs: dict[str, Any] = {
        "headers": GITHUB_HEADERS,
        "timeout": min(float(timeout), GITHUB_SOCKET_TIMEOUT_SECONDS, remaining),
        "stream": True,
        "allow_redirects": False,
    }
    if params is not None:
        request_kwargs["params"] = params
    try:
        response = session.get(url, **request_kwargs)
    except requests.Timeout as exc:
        raise _timeout_error(active_deadline, monotonic) from exc
    except requests.RequestException as exc:
        raise _error("github_upstream_invalid_response", 502) from exc

    try:
        try:
            status_code = int(response.status_code)
        except (AttributeError, TypeError, ValueError) as exc:
            raise _error("github_upstream_invalid_response", 502) from exc

        if status_code != 200 and status_code != 403:
            response_error = _classify_response_error(
                response,
                None,
                not_found_code=not_found_code,
            )
            if response_error is not None:
                raise response_error

        if status_code == 403:
            header_error = _classify_response_error(
                response,
                None,
                not_found_code=not_found_code,
            )
            if header_error is not None and header_error.code == "github_upstream_rate_limited":
                raise header_error
            try:
                payload = _read_bounded_json(
                    response,
                    deadline=active_deadline,
                    monotonic=monotonic,
                )
            except GitHubStarsError as exc:
                if exc.code != "github_upstream_invalid_response":
                    raise
                payload = None
            raise _classify_response_error(
                response,
                payload,
                not_found_code=not_found_code,
            ) or _error("github_upstream_forbidden", 403)

        payload = _read_bounded_json(
            response,
            deadline=active_deadline,
            monotonic=monotonic,
        )
        return payload, dict(getattr(response, "headers", {}) or {})
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _normalize_account(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _error("github_upstream_invalid_response", 502)
    account_id = payload.get("id")
    login = payload.get("login")
    if not positive_integer(account_id) or not isinstance(login, str):
        raise _error("github_upstream_invalid_response", 502)
    try:
        canonical_login = validate_github_username(login)
    except GitHubStarsError as exc:
        raise _error("github_upstream_invalid_response", 502) from exc
    return {"id": account_id, "login": canonical_login}


def fetch_github_account(
    session: requests.Session,
    *,
    username: str | None = None,
    account_id: int | None = None,
    timeout: float = 10.0,
    budget_seconds: float = GITHUB_NETWORK_BUDGET_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    _deadline: float | None = None,
) -> dict[str, Any]:
    if username is not None and account_id is not None:
        raise _error("github_star_account_mismatch", 409)
    if username is not None:
        requested_username = validate_github_username(username)
        url = f"{GITHUB_API_ROOT}/users/{quote(requested_username, safe='')}"
        expected_account_id = None
    elif positive_integer(account_id):
        url = f"{GITHUB_API_ROOT}/user/{account_id}"
        expected_account_id = account_id
    else:
        raise _error("github_username_invalid", 422)

    deadline = _deadline if _deadline is not None else monotonic() + float(budget_seconds)
    payload, _ = _request_json(
        session,
        url,
        timeout=timeout,
        not_found_code="github_user_not_found",
        deadline=deadline,
        monotonic=monotonic,
    )
    account = _normalize_account(
        payload
    )
    if expected_account_id is not None and account["id"] != expected_account_id:
        raise _error("github_star_account_mismatch", 409)
    return account


def _header_value(headers: Any, name: str) -> str:
    if headers is None:
        return ""
    direct = headers.get(name)
    if direct is not None:
        return str(direct)
    target = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == target:
            return str(value)
    return ""


def _next_starred_link(
    headers: Any,
    canonical_login: str,
    *,
    expected_page: int,
) -> str | None:
    raw = _header_value(headers, "Link").strip()
    if not raw:
        return None
    links = parse_header_links(raw.rstrip("> ").replace(">,<", ">, <"))
    next_links = [
        str(link.get("url") or "").strip()
        for link in links
        if "next" in str(link.get("rel") or "").casefold().split()
    ]
    if not next_links:
        if re.search(r"rel\s*=\s*[\"']?next\b", raw, re.IGNORECASE):
            raise _error("github_upstream_invalid_response", 502)
        return None
    if len(next_links) != 1:
        raise _error("github_upstream_invalid_response", 502)

    next_url = next_links[0]
    parsed = urlparse(next_url)
    expected_path = f"/users/{canonical_login}/starred".casefold()
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != "api.github.com"
        or unquote(parsed.path).casefold() != expected_path
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise _error("github_upstream_invalid_response", 502)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) != {"page", "per_page"}:
        raise _error("github_upstream_invalid_response", 502)
    for key, values in query.items():
        if len(values) != 1 or not re.fullmatch(r"[1-9]\d*", values[0]):
            raise _error("github_upstream_invalid_response", 502)
        if key == "per_page" and int(values[0]) > 100:
            raise _error("github_upstream_invalid_response", 502)
    if int(query["page"][0]) != expected_page or int(query["per_page"][0]) != 100:
        raise _error("github_upstream_invalid_response", 502)
    return next_url


def _canonical_starred_page_url(url: str, page: int) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}{unquote(parsed.path).casefold()}?page={page}&per_page=100"


def _normalize_repository_identity(repo: Any) -> tuple[int, str, bool]:
    if not isinstance(repo, dict):
        raise _error("github_upstream_invalid_response", 502)
    repo_id = repo.get("id")
    full_name = repo.get("full_name")
    private = repo.get("private")
    visibility = repo.get("visibility")
    if (
        not positive_integer(repo_id)
        or not isinstance(full_name, str)
        or not isinstance(private, bool)
        or visibility not in {"public", "private", "internal"}
    ):
        raise _error("github_upstream_invalid_response", 502)
    try:
        normalized_name = normalize_github_repo(full_name, 0)
    except ValueError as exc:
        raise _error("github_upstream_invalid_response", 502) from exc
    if normalized_name != full_name.strip():
        raise _error("github_upstream_invalid_response", 502)
    is_public = private is False and visibility == "public"
    return repo_id, normalized_name, is_public


def _add_repository_page(
    payload: Any,
    *,
    identities: dict[int, tuple[str, bool]],
    names: dict[str, int],
    public_repositories: dict[int, dict[str, Any]],
    private_repo_ids: set[int],
) -> None:
    if not isinstance(payload, list):
        raise _error("github_upstream_invalid_response", 502)
    for raw_repo in payload:
        repo_id, full_name, is_public = _normalize_repository_identity(raw_repo)
        previous = identities.get(repo_id)
        if previous is not None and previous != (full_name, is_public):
            raise _error("github_upstream_invalid_response", 502)
        name_key = full_name.casefold()
        previous_id = names.get(name_key)
        if previous_id is not None and previous_id != repo_id:
            raise _error("github_upstream_invalid_response", 502)
        identities[repo_id] = (full_name, is_public)
        names[name_key] = repo_id
        if is_public:
            public_repositories[repo_id] = {"id": repo_id, "full_name": full_name}
            private_repo_ids.discard(repo_id)
            if len(public_repositories) > GITHUB_STAR_LIMIT:
                raise _error("github_star_limit_exceeded", 422)
        else:
            private_repo_ids.add(repo_id)


def fetch_github_star_snapshot(
    session: requests.Session,
    *,
    username: str | None = None,
    account_id: int | None = None,
    timeout: float = 10.0,
    budget_seconds: float = GITHUB_NETWORK_BUDGET_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    deadline = monotonic() + float(budget_seconds)
    account = fetch_github_account(
        session,
        username=username,
        account_id=account_id,
        timeout=timeout,
        monotonic=monotonic,
        _deadline=deadline,
    )
    login = account["login"]
    url = f"{GITHUB_API_ROOT}/users/{quote(login, safe='')}/starred"
    params: dict[str, Any] | None = {"per_page": 100}
    visited: set[str] = set()
    identities: dict[int, tuple[str, bool]] = {}
    names: dict[str, int] = {}
    public_repositories: dict[int, dict[str, Any]] = {}
    private_repo_ids: set[int] = set()
    page = 1

    while url:
        canonical_page_url = _canonical_starred_page_url(url, page)
        if canonical_page_url in visited:
            raise _error("github_upstream_invalid_response", 502)
        visited.add(canonical_page_url)
        request_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "deadline": deadline,
            "monotonic": monotonic,
        }
        if params is not None:
            request_kwargs["params"] = params
        payload, response_headers = _request_json(session, url, **request_kwargs)
        _add_repository_page(
            payload,
            identities=identities,
            names=names,
            public_repositories=public_repositories,
            private_repo_ids=private_repo_ids,
        )
        url = _next_starred_link(response_headers, login, expected_page=page + 1)
        params = None
        if url is not None:
            page += 1

    repositories = [public_repositories[repo_id] for repo_id in sorted(public_repositories)]
    return {
        "account": account,
        "repositories": repositories,
        "starred_count": len(repositories),
        "private_skipped_count": len(private_repo_ids),
    }


def _normalize_public_repositories(repositories: Any) -> list[dict[str, Any]]:
    if not isinstance(repositories, list):
        raise _error("github_upstream_invalid_response", 502)
    by_id: dict[int, dict[str, Any]] = {}
    by_name: dict[str, int] = {}
    for raw_repo in repositories:
        if not isinstance(raw_repo, dict):
            raise _error("github_upstream_invalid_response", 502)
        repo_id = raw_repo.get("id")
        full_name = raw_repo.get("full_name")
        if not positive_integer(repo_id) or not isinstance(full_name, str):
            raise _error("github_upstream_invalid_response", 502)
        try:
            normalized_name = normalize_github_repo(full_name, 0)
        except ValueError as exc:
            raise _error("github_upstream_invalid_response", 502) from exc
        if normalized_name != full_name.strip():
            raise _error("github_upstream_invalid_response", 502)
        previous = by_id.get(repo_id)
        if previous is not None and previous["full_name"] != normalized_name:
            raise _error("github_upstream_invalid_response", 502)
        name_key = normalized_name.casefold()
        previous_id = by_name.get(name_key)
        if previous_id is not None and previous_id != repo_id:
            raise _error("github_upstream_invalid_response", 502)
        by_id[repo_id] = {"id": repo_id, "full_name": normalized_name}
        by_name[name_key] = repo_id
        if len(by_id) > GITHUB_STAR_LIMIT:
            raise _error("github_star_limit_exceeded", 422)
    return [by_id[repo_id] for repo_id in sorted(by_id)]


def _normalize_preview_account(account: Any) -> dict[str, Any]:
    return _normalize_account(account)


def _empty_summary() -> dict[str, list[dict[str, Any]]]:
    return {key: [] for key in SUMMARY_KEYS}


def _summary_item(
    source: dict[str, Any],
    repo_id: int,
    repo: str,
    *,
    previous_repo: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "repo_id": repo_id,
        "repo": repo,
        "source_id": source["id"],
    }
    if previous_repo is not None:
        item["previous_repo"] = previous_repo
    return item


def _stable_summary(summary: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(summary, dict) or set(summary) != set(SUMMARY_KEYS):
        raise _error("github_upstream_invalid_response", 502)
    stable: dict[str, list[dict[str, Any]]] = {}
    for key in SUMMARY_KEYS:
        raw_items = summary.get(key)
        if not isinstance(raw_items, list) or not all(isinstance(item, dict) for item in raw_items):
            raise _error("github_upstream_invalid_response", 502)
        stable[key] = sorted(
            (copy.deepcopy(item) for item in raw_items),
            key=lambda item: (
                int(item.get("repo_id") or 0),
                str(item.get("repo") or "").casefold(),
                str(item.get("source_id") or ""),
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
    return stable


def _has_legacy_github_star_note(source: dict[str, Any]) -> bool:
    if source.get("managed_by") == "github_stars":
        return False
    notes = str(source.get("notes") or "")
    return bool(LEGACY_GITHUB_STAR_NOTE_PATTERN.search(notes))


def _is_internal_opml_wrapper(source: Any) -> bool:
    return (
        isinstance(source, dict)
        and source.get("id") == ONLINE_OPML_SOURCE_ID
        and str(source.get("type") or "").strip().casefold() == "opmlrss"
    )


def _validate_merge_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict) or not isinstance(config.get("sources"), list):
        return validate_online_config_schema(copy.deepcopy(config), existing=True)
    cleaned = copy.deepcopy(config)
    user_sources = [
        source
        for source in cleaned["sources"]
        if not _is_internal_opml_wrapper(source)
    ]
    if len(user_sources) > ONLINE_SOURCE_LIMIT:
        raise _error("github_star_capacity_exceeded", 422)
    cleaned["sources"] = user_sources
    return validate_online_config_schema(cleaned, existing=True)


def merge_github_star_sources(
    config: dict[str, Any],
    *,
    account: dict[str, Any],
    repositories: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_config = _validate_merge_config(config)
    normalized_account = _normalize_preview_account(account)
    normalized_repositories = _normalize_public_repositories(repositories)
    binding = normalized_config.get("github_star_sync")
    if binding is not None and binding["account_id"] != normalized_account["id"]:
        raise _error("github_star_account_mismatch", 409)

    sources = copy.deepcopy(normalized_config["sources"])
    if any(_has_legacy_github_star_note(source) for source in sources):
        raise _error("github_star_binding_ambiguous", 409)

    managed_by_repo_id: dict[int, int] = {}
    manual_by_repo: dict[str, int] = {}
    used_ids = {source["id"] for source in sources}
    for index, source in enumerate(sources):
        if source.get("managed_by") == "github_stars":
            if source["managed_account_id"] != normalized_account["id"]:
                raise _error("github_star_account_mismatch", 409)
            managed_by_repo_id[source["managed_repo_id"]] = index
        elif source.get("type") == "github_release":
            manual_by_repo[source["locator"].casefold()] = index

    summary = _empty_summary()
    starred_repo_ids: set[int] = set()
    for repo in normalized_repositories:
        repo_id = repo["id"]
        full_name = repo["full_name"]
        starred_repo_ids.add(repo_id)
        managed_index = managed_by_repo_id.get(repo_id)
        if managed_index is not None:
            source = sources[managed_index]
            previous_repo = source["locator"]
            renamed = previous_repo != full_name or source["target"] != full_name
            if renamed:
                source["locator"] = full_name
                source["target"] = full_name
            if source["managed_state"] == "auto_disabled":
                source["enabled"] = True
                source["managed_state"] = "active"
                summary["re_enabled"].append(_summary_item(source, repo_id, full_name))
            elif renamed:
                summary["renamed"].append(
                    _summary_item(source, repo_id, full_name, previous_repo=previous_repo)
                )
            continue

        manual_index = manual_by_repo.get(full_name.casefold())
        if manual_index is not None:
            source = sources[manual_index]
            if source.get("enabled") is False:
                summary["skipped_manual_disabled"].append(
                    _summary_item(source, repo_id, full_name)
                )
                continue
            source.update(
                {
                    "target": full_name,
                    "locator": full_name,
                    "managed_by": "github_stars",
                    "managed_account_id": normalized_account["id"],
                    "managed_repo_id": repo_id,
                    "managed_state": "active",
                }
            )
            summary["adopted"].append(_summary_item(source, repo_id, full_name))
            managed_by_repo_id[repo_id] = manual_index
            continue

        new_source = normalize_online_source_record(
            {
                "name": full_name,
                "type": "github_release",
                "enabled": True,
                "locator": full_name,
                "managed_by": "github_stars",
                "managed_account_id": normalized_account["id"],
                "managed_repo_id": repo_id,
                "managed_state": "active",
            },
            len(sources),
            existing=False,
            used_ids=used_ids,
        )
        if new_source is None:
            raise _error("github_upstream_invalid_response", 502)
        sources.append(new_source)
        used_ids.add(new_source["id"])
        summary["added"].append(_summary_item(new_source, repo_id, full_name))

    for source in sources:
        if (
            source.get("managed_by") == "github_stars"
            and source["managed_account_id"] == normalized_account["id"]
            and source["managed_repo_id"] not in starred_repo_ids
            and source["managed_state"] == "active"
        ):
            source["enabled"] = False
            source["managed_state"] = "auto_disabled"
            summary["disabled"].append(
                _summary_item(
                    source,
                    source["managed_repo_id"],
                    source["locator"],
                )
            )

    if len(sources) > ONLINE_SOURCE_LIMIT:
        raise _error("github_star_capacity_exceeded", 422)

    candidate = copy.deepcopy(normalized_config)
    candidate["sources"] = sources
    candidate["github_star_sync"] = {
        "version": 1,
        "account_id": normalized_account["id"],
        "account_login": normalized_account["login"],
    }
    candidate = _validate_merge_config(candidate)
    stable_summary = _stable_summary(summary)
    return {
        "config": candidate,
        "summary": stable_summary,
        "requires_confirmation": (
            binding is None
            or bool(stable_summary["disabled"])
            or bool(stable_summary["adopted"])
        ),
        "config_changed": online_config_digest(candidate) != online_config_digest(normalized_config),
    }


def build_github_star_preview_hash(
    *,
    account: dict[str, Any],
    repositories: list[dict[str, Any]],
    base_config_digest: str,
    binding: dict[str, Any] | None,
    summary: dict[str, list[dict[str, Any]]],
) -> str:
    normalized_account = _normalize_preview_account(account)
    normalized_repositories = _normalize_public_repositories(repositories)
    if not re.fullmatch(r"[0-9a-f]{64}", str(base_config_digest or "")):
        raise _error("github_upstream_invalid_response", 502)
    normalized_binding = normalize_github_star_sync(binding)
    payload = {
        "version": 1,
        "account_id": normalized_account["id"],
        "repositories": normalized_repositories,
        "base_config_digest": base_config_digest,
        "binding": {
            "bound": normalized_binding is not None,
            "account_id": normalized_binding["account_id"] if normalized_binding else None,
        },
        "summary": _stable_summary(summary),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_github_star_preview(config: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise _error("github_upstream_invalid_response", 502)
    account = _normalize_preview_account(snapshot.get("account"))
    repositories = _normalize_public_repositories(snapshot.get("repositories"))
    private_skipped_count = snapshot.get("private_skipped_count")
    starred_count = snapshot.get("starred_count")
    if (
        not isinstance(private_skipped_count, int)
        or isinstance(private_skipped_count, bool)
        or private_skipped_count < 0
        or not isinstance(starred_count, int)
        or isinstance(starred_count, bool)
        or starred_count < 0
        or starred_count != len(repositories)
    ):
        raise _error("github_upstream_invalid_response", 502)

    normalized_config = _validate_merge_config(config)
    merge = merge_github_star_sources(
        normalized_config,
        account=account,
        repositories=repositories,
    )
    base_digest = online_config_digest(normalized_config)
    preview_hash = build_github_star_preview_hash(
        account=account,
        repositories=repositories,
        base_config_digest=base_digest,
        binding=normalized_config.get("github_star_sync"),
        summary=merge["summary"],
    )
    return {
        "ok": True,
        "account": account,
        "starred_count": len(repositories),
        "private_skipped_count": private_skipped_count,
        "summary": merge["summary"],
        "requires_confirmation": merge["requires_confirmation"],
        "preview_hash": preview_hash,
        "base_config_digest": base_digest,
        "config_changed": merge["config_changed"],
    }
