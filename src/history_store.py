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
    cfg = _config()
    if cfg:
        return _remote_load(*cfg)
    return _local_load()


def save_to_history(entry: dict) -> None:
    """Insert or update an entry (deduped by ``id``)."""
    cfg = _config()
    if cfg:
        _remote_upsert(*cfg, entry)
        return
    history = _local_load()
    history = [h for h in history if h.get("id") != entry["id"]]
    history.insert(0, entry)
    _local_save_all(history)


def delete_from_history(article_id: str) -> None:
    cfg = _config()
    if cfg:
        _remote_delete(*cfg, article_id)
        return
    history = [h for h in _local_load() if h.get("id") != article_id]
    _local_save_all(history)
