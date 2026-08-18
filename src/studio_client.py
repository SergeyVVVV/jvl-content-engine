"""Transport for publishing a draft to jvl.ca.

Deliberately independent of Streamlit: any entry point — the web UI, a CLI
run, a Claude Code session, a cron job — imports these two functions and gets
the same contract and the same error handling.

Configuration (env or Streamlit secrets):
    JVL_PUBLISH_URL    e.g. https://www.jvl.ca   (base URL, no path)
    JVL_PUBLISH_TOKEN  the site's CONTENT_PUBLISH_TOKEN
"""

# NOTE: deliberately no `from __future__ import annotations` here.
# It turns every annotation into a string, which makes @dataclass resolve
# them through sys.modules[cls.__module__].__dict__ at class-creation time.
# Streamlit leaves that entry as None while hot-reloading after a push, and
# the whole app then dies on import with
#   AttributeError: 'NoneType' object has no attribute '__dict__'
# Real annotation objects need no such lookup. See tests/test_dataclass_imports.py

import json
import os
from dataclasses import dataclass, field

import requests

DRAFT_PATH = "/api/content/draft"
TAGS_PATH = "/api/content/tags"
DEFAULT_TIMEOUT = 60


class PublishConfigError(RuntimeError):
    """Raised when the publish URL or token is missing."""


@dataclass
class PublishResult:
    ok: bool
    status: int
    #: Server-side error text — the 422 body carries the exact contract
    #: violation, which is the whole reason we surface it verbatim.
    error: str | None = None
    slug: str | None = None
    page_id: int | None = None
    news_id: int | None = None
    tags_attached: list[str] = field(default_factory=list)
    #: Tag names the site had no match for. Nothing was created for them —
    #: an editor adds the tag in AdminLTE if it should exist.
    tags_unknown: list[str] = field(default_factory=list)

    @property
    def admin_hint(self) -> str:
        if not self.ok:
            return ""
        return (
            f"Draft created (active = 0), slug '{self.slug}'. "
            "Review and publish it in AdminLTE."
        )


def resolve_config(
    url: str | None = None,
    token: str | None = None,
) -> tuple[str, str]:
    """Resolve (base_url, token) from arguments, Streamlit secrets, or env."""
    url = url or _from_secrets("JVL_PUBLISH_URL") or os.environ.get("JVL_PUBLISH_URL")
    token = token or _from_secrets("JVL_PUBLISH_TOKEN") or os.environ.get("JVL_PUBLISH_TOKEN")
    missing = [
        name
        for name, value in (("JVL_PUBLISH_URL", url), ("JVL_PUBLISH_TOKEN", token))
        if not value
    ]
    if missing:
        raise PublishConfigError(
            f"Publishing is not configured: {', '.join(missing)} is not set. "
            "Add it to Streamlit secrets or the environment."
        )
    return url.rstrip("/"), token


def _from_secrets(key: str) -> str | None:
    """Read a Streamlit secret without making Streamlit a hard dependency."""
    try:
        import streamlit as st

        return st.secrets.get(key)  # type: ignore[no-any-return]
    except Exception:
        return None


def publish_draft(
    payload: dict,
    *,
    url: str | None = None,
    token: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> PublishResult:
    """POST a draft payload to the site. Never raises on an HTTP error."""
    base_url, bearer = resolve_config(url, token)
    try:
        response = requests.post(
            f"{base_url}{DRAFT_PATH}",
            headers={
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload).encode("utf-8"),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return PublishResult(ok=False, status=0, error=f"Request failed: {exc}")

    return _interpret(response.status_code, _json_or_none(response))


def list_drafts(
    *,
    url: str | None = None,
    token: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[bool, list[dict] | str]:
    """Return (True, drafts) or (False, error message)."""
    base_url, bearer = resolve_config(url, token)
    try:
        response = requests.get(
            f"{base_url}{DRAFT_PATH}",
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, f"Request failed: {exc}"

    body = _json_or_none(response) or {}
    if response.status_code == 200 and body.get("success"):
        return True, body.get("drafts", [])
    return False, _explain(response.status_code, body)


def list_tags(
    *,
    url: str | None = None,
    token: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[bool, list[str] | str]:
    """Tag names a draft may be published with.

    The site attaches existing tags only, so offering this list is the
    difference between picking a tag and typing one that silently won't match.
    Returns (True, names) or (False, error message).
    """
    base_url, bearer = resolve_config(url, token)
    try:
        response = requests.get(
            f"{base_url}{TAGS_PATH}",
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, f"Request failed: {exc}"

    body = _json_or_none(response) or {}
    if response.status_code == 200 and body.get("success"):
        return True, body.get("tags", [])
    return False, _explain(response.status_code, body)


def _json_or_none(response: "requests.Response") -> dict | None:
    try:
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None


def _interpret(status: int, body: dict | None) -> PublishResult:
    if status == 201 and body and body.get("success"):
        return PublishResult(
            ok=True,
            status=status,
            slug=body.get("slug"),
            page_id=body.get("pageId"),
            news_id=body.get("newsId"),
            tags_attached=body.get("tagsAttached") or [],
            tags_unknown=body.get("tagsUnknown") or [],
        )
    return PublishResult(ok=False, status=status, error=_explain(status, body or {}))


def _explain(status: int, body: dict) -> str:
    """Turn a failure into something an operator can act on."""
    server_error = body.get("error")
    guidance = {
        401: "Check JVL_PUBLISH_TOKEN — it must match CONTENT_PUBLISH_TOKEN on the server.",
        403: "The server refused the request.",
        404: "Endpoint not found — check JVL_PUBLISH_URL points at the site root.",
        422: "The payload does not match the site's contract.",
        503: "Publishing is disabled on the server (CONTENT_PUBLISH_TOKEN is not configured).",
    }.get(status, "")
    parts = [f"HTTP {status}"]
    if server_error:
        parts.append(str(server_error))
    if guidance:
        parts.append(guidance)
    return " — ".join(parts)
