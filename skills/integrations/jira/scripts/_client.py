"""Jira REST API client (Cloud v3 + Data Center v2).

Internal module — the skill agent dispatches to ``jira.py``; this file is an
implementation detail.  The API token is read from the environment or the
shared jira config file only; it is never logged, echoed, or accepted on
the command line.

Authentication differs by flavor:
  - **Cloud**: Basic Auth — ``email:api_token`` base64-encoded.
  - **Data Center**: Bearer PAT — ``Authorization: Bearer <token>``.

The flavor is auto-detected from the base URL (``*.atlassian.net`` → cloud).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Mapping
from urllib.parse import urlparse

import httpx

log = logging.getLogger("jira.client")

DEFAULT_CONCURRENCY = 4
DEFAULT_MIN_DELAY_MS = 100
DEFAULT_TIMEOUT_S = 30.0
MAX_RETRIES = 5
PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 100

FLAVOR_CLOUD = "cloud"
FLAVOR_DATACENTER = "datacenter"

# Cloud uses v3; Data Center typically uses v2.
API_PREFIX_CLOUD = "/rest/api/3"
API_PREFIX_DC = "/rest/api/2"


class JiraError(Exception):
    pass


class AuthError(JiraError):
    pass


@dataclass(frozen=True)
class Credentials:
    base_url: str
    email: str          # empty string for Data Center (PAT auth)
    token: str
    flavor: str         # "cloud" or "datacenter"


def detect_flavor(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower()
    if host.endswith(".atlassian.net"):
        return FLAVOR_CLOUD
    return FLAVOR_DATACENTER


class JiraClient:
    """Async wrapper around the Jira REST API.

    Provides a uniform surface for both Cloud (v3, Basic Auth) and Data
    Center (v2, Bearer PAT).  Callers pass issue keys, JQL strings, and
    field dicts — the client handles auth, pagination, retries, and rate-
    limit back-off.
    """

    def __init__(
        self,
        credentials: Credentials,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
        min_delay_ms: int = DEFAULT_MIN_DELAY_MS,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        verify_tls: bool = True,
    ) -> None:
        base_url = credentials.base_url
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")

        self._base = base_url.rstrip("/")
        self._flavor = credentials.flavor
        self._api_prefix = (
            API_PREFIX_CLOUD if self._flavor == FLAVOR_CLOUD else API_PREFIX_DC
        )

        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "dropkit-jira/1.0",
        }
        if self._flavor == FLAVOR_CLOUD:
            raw = f"{credentials.email}:{credentials.token}"
            encoded = base64.b64encode(raw.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        else:
            headers["Authorization"] = f"Bearer {credentials.token}"

        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers=headers,
            timeout=timeout_s,
            verify=verify_tls,
            follow_redirects=True,
        )
        self._sem = asyncio.Semaphore(concurrency)
        self._min_delay = min_delay_ms / 1000.0
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "JiraClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    @property
    def flavor(self) -> str:
        return self._flavor

    @property
    def base_url(self) -> str:
        return self._base

    @property
    def api_prefix(self) -> str:
        return self._api_prefix

    # ---- Low-level request with retry / rate-limit --------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> httpx.Response:
        async with self._sem:
            async with self._lock:
                now = asyncio.get_running_loop().time()
                wait = self._min_delay - (now - self._last_request)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request = asyncio.get_running_loop().time()

            last_exc: Exception | None = None
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await self._client.request(
                        method, path, params=params, json=json_body
                    )
                except httpx.TransportError as exc:
                    last_exc = exc
                    await asyncio.sleep(self._backoff(attempt))
                    continue

                if resp.status_code == 401:
                    raise AuthError(
                        "401 Unauthorized — the Jira API token is missing, "
                        "invalid, or expired.  Re-run scripts/setup_credentials.sh."
                    )
                if resp.status_code == 403:
                    raise AuthError(
                        f"403 Forbidden for {path} — the token lacks permission "
                        "for this resource.  Check the user's Jira permissions."
                    )
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    retry_after = resp.headers.get("Retry-After")
                    delay = (
                        float(retry_after)
                        if retry_after
                        and retry_after.replace(".", "", 1).isdigit()
                        else self._backoff(attempt)
                    )
                    log.warning(
                        "HTTP %s on %s — retrying in %.1fs",
                        resp.status_code, path, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                if resp.status_code >= 400:
                    raise JiraError(
                        f"HTTP {resp.status_code} on {path}: {resp.text[:500]}"
                    )
                return resp

            raise JiraError(
                f"Exhausted {MAX_RETRIES} retries for {path}"
                + (f" (last error: {last_exc})" if last_exc else "")
            )

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(
            30.0, (2 ** attempt) * 0.5 + secrets.SystemRandom().uniform(0, 0.5)
        )

    # ---- High-level operations ----------------------------------------------

    async def whoami(self) -> dict:
        resp = await self._request("GET", f"{self._api_prefix}/myself")
        return resp.json()

    async def get_issue(
        self,
        issue_key: str,
        *,
        fields: str | None = None,
        expand: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {}
        if fields:
            params["fields"] = fields
        if expand:
            params["expand"] = expand
        resp = await self._request(
            "GET",
            f"{self._api_prefix}/issue/{issue_key}",
            params=params or None,
        )
        return resp.json()

    async def search_jql(
        self,
        jql: str,
        *,
        fields: str | None = None,
        expand: str | None = None,
        max_results: int = PAGE_SIZE_DEFAULT,
        start_at: int = 0,
    ) -> dict:
        body: dict[str, Any] = {
            "jql": jql,
            "maxResults": min(max_results, PAGE_SIZE_MAX),
            "startAt": start_at,
        }
        if fields:
            body["fields"] = [f.strip() for f in fields.split(",")]
        if expand:
            body["expand"] = [e.strip() for e in expand.split(",")]
        resp = await self._request(
            "POST", f"{self._api_prefix}/search", json_body=body
        )
        return resp.json()

    async def iter_search(
        self,
        jql: str,
        *,
        fields: str | None = None,
        expand: str | None = None,
        page_size: int = PAGE_SIZE_DEFAULT,
        limit: int | None = None,
    ) -> AsyncIterator[dict]:
        """Paginate through JQL results, yielding one issue at a time."""
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        page_size = min(page_size, PAGE_SIZE_MAX)
        start_at = 0
        yielded = 0
        while True:
            remaining = None if limit is None else max(0, limit - yielded)
            if remaining == 0:
                return
            batch_size = (
                page_size if remaining is None else min(page_size, remaining)
            )
            result = await self.search_jql(
                jql,
                fields=fields,
                expand=expand,
                max_results=batch_size,
                start_at=start_at,
            )
            issues = result.get("issues", [])
            if not issues:
                return
            for issue in issues:
                yield issue
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            total = result.get("total", 0)
            start_at += len(issues)
            if start_at >= total or len(issues) < batch_size:
                return

    async def create_issue(self, body: dict[str, Any]) -> dict:
        resp = await self._request(
            "POST", f"{self._api_prefix}/issue", json_body=body
        )
        return resp.json()

    async def update_issue(
        self, issue_key: str, body: dict[str, Any]
    ) -> None:
        await self._request(
            "PUT", f"{self._api_prefix}/issue/{issue_key}", json_body=body
        )

    async def get_transitions(self, issue_key: str) -> list[dict]:
        resp = await self._request(
            "GET", f"{self._api_prefix}/issue/{issue_key}/transitions"
        )
        return resp.json().get("transitions", [])

    async def transition_issue(
        self, issue_key: str, transition_id: str
    ) -> None:
        await self._request(
            "POST",
            f"{self._api_prefix}/issue/{issue_key}/transitions",
            json_body={"transition": {"id": transition_id}},
        )

    async def add_comment(self, issue_key: str, body: Any) -> dict:
        """Add a comment.  ``body`` is a string (Data Center) or an ADF
        document dict (Cloud).  The caller decides which to send."""
        resp = await self._request(
            "POST",
            f"{self._api_prefix}/issue/{issue_key}/comment",
            json_body={"body": body},
        )
        return resp.json()

    async def list_projects(
        self, *, max_results: int = 50, start_at: int = 0
    ) -> list[dict]:
        resp = await self._request(
            "GET",
            f"{self._api_prefix}/project/search",
            params={"maxResults": max_results, "startAt": start_at},
        )
        data = resp.json()
        return data.get("values", data if isinstance(data, list) else [])

    async def list_fields(self) -> list[dict]:
        resp = await self._request("GET", f"{self._api_prefix}/field")
        return resp.json()

    async def get_create_meta(
        self, project_key: str, issue_type: str
    ) -> dict:
        """Fetch required / available fields for creating an issue."""
        params: dict[str, Any] = {
            "projectKeys": project_key,
            "issuetypeNames": issue_type,
            "expand": "projects.issuetypes.fields",
        }
        resp = await self._request(
            "GET",
            f"{self._api_prefix}/issue/createmeta",
            params=params,
        )
        return resp.json()

    async def raw(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        if not path.startswith("/"):
            path = f"{self._api_prefix}/{path}"
        resp = await self._request(
            method, path, params=params, json_body=json_body
        )
        if not resp.content:
            return None
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            return resp.json()
        return resp.text


def load_credentials() -> Credentials:
    """Read base URL, email, token, and flavor from the shared jira config
    file or environment.

    Precedence: explicit env vars > ``~/.config/jira/credentials.env``.
    Secrets are never returned through logging or non-AuthError exceptions.

    Recognized env vars:
      JIRA_BASE_URL     Base URL of the Jira instance.
      JIRA_USER_EMAIL   Email (Cloud only; blank for Data Center PAT).
      JIRA_API_TOKEN    Cloud: API token.  Data Center: Personal Access Token.
      JIRA_FLAVOR       Optional: "cloud" or "datacenter" (auto-detected).
    """
    values: dict[str, str | None] = {
        "JIRA_BASE_URL": os.environ.get("JIRA_BASE_URL"),
        "JIRA_USER_EMAIL": os.environ.get("JIRA_USER_EMAIL"),
        "JIRA_API_TOKEN": os.environ.get("JIRA_API_TOKEN"),
        "JIRA_FLAVOR": os.environ.get("JIRA_FLAVOR"),
    }

    config_dir = Path(
        os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    )
    config_file = config_dir / "jira" / "credentials.env"
    if config_file.is_file():
        try:
            from dotenv import dotenv_values
        except ImportError as exc:
            raise AuthError(
                "python-dotenv is required to read the config file; "
                "install requirements.txt first."
            ) from exc
        file_values = dotenv_values(config_file)
        for key in values:
            if not values[key]:
                values[key] = file_values.get(key)

    base = (values["JIRA_BASE_URL"] or "").rstrip("/")
    token = values["JIRA_API_TOKEN"] or ""
    if not base or not token:
        raise AuthError(
            "Missing credentials.  Run scripts/setup_credentials.sh or set "
            "JIRA_BASE_URL and JIRA_API_TOKEN environment variables."
        )

    flavor = (
        (values["JIRA_FLAVOR"] or "").strip().lower() or detect_flavor(base)
    )
    if flavor not in (FLAVOR_CLOUD, FLAVOR_DATACENTER):
        raise AuthError(f"unsupported JIRA_FLAVOR: {flavor!r}")

    email = (values["JIRA_USER_EMAIL"] or "").strip()
    if flavor == FLAVOR_CLOUD and not email:
        raise AuthError(
            "JIRA_USER_EMAIL is required for Jira Cloud (Basic Auth).  "
            "Re-run scripts/setup_credentials.sh."
        )

    return Credentials(
        base_url=base, email=email, token=token, flavor=flavor
    )
