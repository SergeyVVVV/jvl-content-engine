"""Durable storage for generated images (Supabase Storage).

Generated images land on the local filesystem, which on Streamlit Cloud is
wiped on every restart — an article published a day later would carry links to
files that no longer exist. Worse, a local path is meaningless to jvl.ca even
while the file is there: the site cannot fetch `images/hero-01.png` off the
generator's disk.

So each image is uploaded to a public Supabase bucket and the markdown carries
the public URL instead. The bucket is public on purpose — the site and the
reader's browser both have to fetch these without credentials.

Configured exactly like the history store: st.secrets["supabase"] with `url`
and `service_key`, falling back to SUPABASE_URL / SUPABASE_SERVICE_KEY. When it
is not configured, upload() returns None and the caller keeps the local path —
image generation still works locally, it just does not survive a restart.
"""

from __future__ import annotations

import mimetypes
import os
import sys
from pathlib import Path
from typing import Optional

import requests

BUCKET = "article-images"
_TIMEOUT = 30

#: Set once a bucket check has succeeded, so a run with several images does not
#: re-check for each one.
_bucket_ready = False


def _config() -> Optional[tuple[str, str]]:
    """Return (base_url, service_key) from Streamlit secrets or the environment."""
    try:
        import streamlit as st

        cfg = st.secrets.get("supabase")
        if cfg:
            url = str(cfg.get("url", "")).rstrip("/")
            key = str(cfg.get("service_key", ""))
            if url and key:
                return url, key
    except Exception:
        pass

    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    return (url, key) if url and key else None


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _ensure_bucket(url: str, key: str) -> bool:
    """Create the public bucket if it does not exist yet."""
    global _bucket_ready
    if _bucket_ready:
        return True
    try:
        got = requests.get(
            f"{url}/storage/v1/bucket/{BUCKET}", headers=_headers(key), timeout=_TIMEOUT
        )
        if got.status_code == 200:
            _bucket_ready = True
            return True

        made = requests.post(
            f"{url}/storage/v1/bucket",
            headers={**_headers(key), "Content-Type": "application/json"},
            json={"id": BUCKET, "name": BUCKET, "public": True},
            timeout=_TIMEOUT,
        )
        # 409 means another run created it between our GET and POST.
        if made.status_code in (200, 201) or made.status_code == 409:
            _bucket_ready = True
            return True
        print(
            f"  Image store: could not create bucket {BUCKET!r} "
            f"({made.status_code}) — keeping local paths.",
            file=sys.stderr,
        )
    except requests.RequestException as exc:
        print(f"  Image store unreachable: {exc} — keeping local paths.", file=sys.stderr)
    return False


def public_url(url: str, dest_path: str) -> str:
    return f"{url}/storage/v1/object/public/{BUCKET}/{dest_path}"


def upload(local_path: str | Path, dest_path: str) -> Optional[str]:
    """Upload one image and return its public URL, or None if unavailable.

    Never raises: a storage outage must cost the article its durable images,
    not the whole run.
    """
    cfg = _config()
    if not cfg:
        return None
    url, key = cfg
    if not _ensure_bucket(url, key):
        return None

    path = Path(local_path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        print(f"  Image store: cannot read {path}: {exc}", file=sys.stderr)
        return None

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        resp = requests.post(
            f"{url}/storage/v1/object/{BUCKET}/{dest_path}",
            headers={
                **_headers(key),
                "Content-Type": content_type,
                # Overwrite rather than fail when a slug is regenerated.
                "x-upsert": "true",
            },
            data=data,
            timeout=_TIMEOUT,
        )
        if resp.status_code in (200, 201):
            return public_url(url, dest_path)
        print(
            f"  Image store: upload of {dest_path} failed ({resp.status_code}) "
            f"— keeping the local path.",
            file=sys.stderr,
        )
    except requests.RequestException as exc:
        print(f"  Image store: upload of {dest_path} failed: {exc}", file=sys.stderr)
    return None
