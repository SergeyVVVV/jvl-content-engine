"""Persistent article-history store.

Uses Supabase (Postgres via its REST/PostgREST API) when configured through
``st.secrets["supabase"]`` — this survives Streamlit Cloud restarts, unlike the
local filesystem. Falls back to a local JSON file when Supabase is not
configured, so local development keeps working without secrets.

The full article (markdown + metadata + qa_report) is stored in the row itself,
so viewing a past article never depends on files that the ephemeral filesystem
may have wiped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import requests

TABLE = "article_history"
_TIMEOUT = 15

# Local fallback (used only when Supabase is not configured).
_LOCAL_PATH = Path("outputs") / "history.json"

#: Why the last remote call failed, for the UI to show. History is a
#: convenience: the backing store being unreachable must never take down the
#: generator, which is what happened when the Supabase project went away and
#: load_history() raised straight out of app.py's module body.
_last_error: str | None = None


class HistoryUnavailable(RuntimeError):
    """The history store is configured but could not be reached."""


def history_last_error() -> str | None:
    """Message from the most recent failed history call, or None."""
    return _last_error


def _describe(exc: Exception) -> str:
    if isinstance(exc, requests.ConnectionError):
        return (
            "cannot reach the Supabase project — check that it still exists and "
            "that the URL in secrets is current"
        )
    if isinstance(exc, requests.Timeout):
        return f"Supabase did not answer within {_TIMEOUT}s"
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"Supabase returned HTTP {exc.response.status_code}"
    return str(exc) or exc.__class__.__name__


def _config() -> Optional[tuple[str, str]]:
    """Return (base_url, service_key) from Streamlit secrets, or None."""
    try:
        import streamlit as st

        cfg = st.secrets.get("supabase")
        if not cfg:
            return None
        url = str(cfg.get("url", "")).rstrip("/")
        key = str(cfg.get("service_key", ""))
        if not url or not key:
            return None
        return url, key
    except Exception:
        return None


def is_remote() -> bool:
    return _config() is not None


def _headers(key: str, extra: Optional[dict] = None) -> dict:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


# ─── Supabase-backed implementation ───────────────────────────────────────────

def _remote_load(url: str, key: str) -> list[dict]:
    resp = requests.get(
        f"{url}/rest/v1/{TABLE}",
        params={"select": "*", "order": "created_at.desc"},
        headers=_headers(key),
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _remote_upsert(url: str, key: str, entry: dict) -> None:
    resp = requests.post(
        f"{url}/rest/v1/{TABLE}",
        params={"on_conflict": "id"},
        headers=_headers(key, {"Prefer": "resolution=merge-duplicates,return=minimal"}),
        data=json.dumps(entry, ensure_ascii=False).encode("utf-8"),
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()


def _remote_delete(url: str, key: str, article_id: str) -> None:
    resp = requests.delete(
        f"{url}/rest/v1/{TABLE}",
        params={"id": f"eq.{article_id}"},
        headers=_headers(key, {"Prefer": "return=minimal"}),
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()


# ─── Local JSON fallback ──────────────────────────────────────────────────────

def _local_load() -> list[dict]:
    if not _LOCAL_PATH.exists():
        return []
    try:
        with open(_LOCAL_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []


def _local_save_all(history: list[dict]) -> None:
    _LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOCAL_PATH, "w", encoding="utf-8") as fh:
        json.dump(history, fh, indent=2, ensure_ascii=False)


# ─── Public API ───────────────────────────────────────────────────────────────

def load_history() -> list[dict]:
    """Past articles, newest first. Never raises.

    A history backend that is down is worth a warning, not an outage — this is
    called from the top of app.py, so anything raised here takes the whole UI
    with it.
    """
    global _last_error
    cfg = _config()
    if not cfg:
        _last_error = None
        return _local_load()
    try:
        history = _remote_load(*cfg)
    except Exception as exc:
        _last_error = _describe(exc)
        return []
    _last_error = None
    return history


def save_to_history(entry: dict) -> None:
    """Insert or update an entry (deduped by ``id``).

    Raises HistoryUnavailable if the remote store cannot be reached, so the
    caller can keep the finished article and report the failure rather than
    losing a whole pipeline run at the last step.
    """
    global _last_error
    cfg = _config()
    if cfg:
        try:
            _remote_upsert(*cfg, entry)
        except Exception as exc:
            _last_error = _describe(exc)
            raise HistoryUnavailable(_last_error) from exc
        _last_error = None
        return
    history = _local_load()
    history = [h for h in history if h.get("id") != entry["id"]]
    history.insert(0, entry)
    _local_save_all(history)


def delete_from_history(article_id: str) -> None:
    """Remove an entry. Raises HistoryUnavailable if the store is unreachable,
    so the UI can say the delete did not happen instead of implying it did."""
    global _last_error
    cfg = _config()
    if cfg:
        try:
            _remote_delete(*cfg, article_id)
        except Exception as exc:
            _last_error = _describe(exc)
            raise HistoryUnavailable(_last_error) from exc
        _last_error = None
        return
    history = [h for h in _local_load() if h.get("id") != article_id]
    _local_save_all(history)
