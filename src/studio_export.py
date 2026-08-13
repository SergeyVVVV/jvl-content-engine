"""Studio export — turn a finished pipeline run into the site's draft payload.

The site (jvl.ca, Next.js) accepts `POST /api/content/draft` with:

    {
      "metadata": {slug, title, meta_description, excerpt?, ...},
      "article":  {h1, intro_markdown?, sections: [{level, heading, body_markdown}]}
    }

The engine has no `sections` of its own — the Writer emits `draft_markdown`,
and both the FAQ Agent (`append_to_article`) and the Visual Agent
(`_insert_images`) post-process that markdown string rather than a structure.
So the only representation that reflects the *finished* article is the final
markdown, and this module parses it back into sections.

Nothing here does I/O or talks to the network — see `studio_client` for that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# H2 blocks the pipeline appends for the human reviewer. They are part of the
# working document, never part of the published article.
INTERNAL_HEADINGS = (
    "claims to verify",
    "open todos",
)

_H1_RE = re.compile(r"^#\s+(?P<text>.+?)\s*$")
_H2_RE = re.compile(r"^##\s+(?P<text>.+?)\s*$")
_H3_RE = re.compile(r"^###\s+(?P<text>.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_LOCAL_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((?!https?://|//|data:)([^)]+)\)")
_FAQ_HEADING_RE = re.compile(r"^(faq|frequently asked questions)\b", re.I)


@dataclass
class StudioPayload:
    """A payload plus everything worth telling the operator before they send it."""

    payload: dict
    warnings: list[str] = field(default_factory=list)

    @property
    def sections(self) -> list[dict]:
        return self.payload["article"]["sections"]


def _is_internal(heading: str) -> bool:
    low = heading.strip().lower()
    return any(low.startswith(prefix) for prefix in INTERNAL_HEADINGS)


def split_markdown(markdown: str) -> tuple[str | None, str, list[dict]]:
    """Split final article markdown into (h1, intro, sections).

    * `h1` — the `# ` line, if present.
    * `intro` — body text between the H1 and the first H2. The site renders it
      above the first heading; without it every article loses its lead.
    * `sections` — one entry per H2/H3, in document order. Internal reviewer
      blocks (Claims to Verify / Open TODOs) and everything under them are
      dropped.

    Headings inside fenced code blocks are treated as content, not structure.
    """
    h1: str | None = None
    intro_lines: list[str] = []
    sections: list[dict] = []
    current: dict | None = None
    in_intro = False
    in_fence = False
    skipping_internal = False

    for line in markdown.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence

        if not in_fence:
            m1 = _H1_RE.match(line)
            m2 = _H2_RE.match(line)
            m3 = _H3_RE.match(line)

            if m1 and not m2:
                h1 = m1.group("text")
                current, in_intro, skipping_internal = None, True, False
                continue

            if m2 and not m3:
                heading = m2.group("text")
                in_intro = False
                if _is_internal(heading):
                    # An internal block ends the article: H3s under it belong
                    # to it, so keep skipping until the next real H2.
                    current, skipping_internal = None, True
                    continue
                skipping_internal = False
                current = {"level": "h2", "heading": heading, "body_markdown": ""}
                sections.append(current)
                continue

            if m3:
                in_intro = False
                if skipping_internal:
                    current = None
                    continue
                current = {"level": "h3", "heading": m3.group("text"), "body_markdown": ""}
                sections.append(current)
                continue

        if skipping_internal:
            continue
        if current is not None:
            current["body_markdown"] += line + "\n"
        elif in_intro:
            intro_lines.append(line)

    for section in sections:
        section["body_markdown"] = _tidy(section["body_markdown"])

    return h1, _tidy("\n".join(intro_lines)), sections


def _tidy(text: str) -> str:
    """Trim blank edges and any horizontal rule left behind by a dropped block."""
    text = text.strip()
    text = re.sub(r"(?:\n\s*-{3,}\s*)+$", "", text)
    return text.strip()


def lint(payload: dict) -> list[str]:
    """Content problems worth showing the operator before they publish.

    These are warnings, not errors: the site would accept the payload either
    way, and the editor still reviews the draft in AdminLTE.
    """
    warnings: list[str] = []
    metadata = payload["metadata"]
    article = payload["article"]
    sections = article["sections"]

    if not sections:
        warnings.append("No sections parsed — the article body would be empty.")

    faq_headings = [
        s["heading"] for s in sections
        if s["level"] == "h2" and _FAQ_HEADING_RE.match(s["heading"])
    ]
    if len(faq_headings) > 1:
        warnings.append(
            f"{len(faq_headings)} FAQ blocks in the body: {faq_headings!r}. "
            "Expected one — check the FAQ Agent's dedup pass."
        )

    if not article.get("intro_markdown"):
        warnings.append("No intro before the first H2 — the article starts on a heading.")

    empty = [s["heading"] for s in sections if not s["body_markdown"]]
    if empty:
        warnings.append(f"{len(empty)} section(s) with an empty body: {empty[:3]!r}")

    meta_h1 = (metadata.get("h1") or "").strip()
    if meta_h1 and meta_h1 != article["h1"]:
        warnings.append(
            f"metadata.h1 ({meta_h1!r}) differs from the markdown H1 "
            f"({article['h1']!r}) — sending the markdown one."
        )

    local_images = [
        match.group(1)
        for section in sections
        for match in _LOCAL_IMAGE_RE.finditer(section["body_markdown"])
    ]
    if local_images:
        warnings.append(
            f"{len(local_images)} image(s) point at local paths and will 404 on the "
            f"site: {local_images[:3]!r}. Upload the hero in AdminLTE."
        )

    description = metadata.get("meta_description") or ""
    if not 120 <= len(description) <= 160:
        warnings.append(f"meta_description is {len(description)} chars (want 120–160).")

    return warnings


def to_studio_payload(
    metadata: dict,
    draft_markdown: str,
    *,
    slug: str | None = None,
    author_key: str | None = None,
) -> StudioPayload:
    """Build the site's draft payload from a finished run.

    `metadata` is the Metadata Copy Agent's output; `draft_markdown` is the
    FINAL article markdown (after the FAQ block and any images were merged in).

    `author_key` must be one of the bylines the site knows (`news.author_key`,
    currently `sergey-vysotsky` / `andrei-klimovich`); `None` leaves the draft
    on the default "JVL Editorial Team" byline.
    """
    h1, intro, sections = split_markdown(draft_markdown)

    article: dict = {
        "h1": h1 or metadata.get("h1") or metadata.get("meta_title") or "",
        "sections": sections,
    }
    if intro:
        article["intro_markdown"] = intro

    out_meta = {
        "slug": slug or metadata.get("slug", ""),
        # The site's field is `title`; the Metadata Copy Agent calls it
        # `meta_title`. Accept either so this survives a rename on our side.
        "title": metadata.get("meta_title") or metadata.get("title") or "",
        "meta_description": metadata.get("meta_description", ""),
    }
    for optional in ("excerpt", "primary_keyword", "secondary_keywords"):
        if metadata.get(optional):
            out_meta[optional] = metadata[optional]
    if author_key:
        out_meta["author_key"] = author_key

    payload = {"metadata": out_meta, "article": article}
    return StudioPayload(payload=payload, warnings=lint(payload))


# ── Local mirror of the site's validator ────────────────────────────────────
# jvl-next/src/lib/content-publish.ts :: validateDraftPayload + normalizeSlug.
# Kept here so the engine fails fast with the same message the server would
# return, instead of discovering it in an HTTP 422.

def normalize_slug(raw: str) -> str:
    collapsed = re.sub(r"[^a-z0-9]+", "-", raw.lower()[:200])
    return collapsed.strip("-")[:180]


def validate_payload(payload: object) -> str | None:
    """Return the site's error message, or None if the payload would be accepted."""
    if not isinstance(payload, dict):
        return "Body must be a JSON object with {metadata, article}"
    metadata, article = payload.get("metadata"), payload.get("article")
    if not isinstance(metadata, dict):
        return 'Missing "metadata" object'
    if not isinstance(article, dict):
        return 'Missing "article" object'
    for key in ("slug", "title", "meta_description"):
        value = metadata.get(key)
        if not isinstance(value, str) or not value:
            return f"metadata.{key} (string) is required"
    if not isinstance(article.get("h1"), str) or not article["h1"]:
        return "article.h1 (string) is required"
    sections = article.get("sections")
    if not isinstance(sections, list) or not sections:
        return "article.sections (non-empty array) is required"
    for index, section in enumerate(sections):
        if (
            not isinstance(section, dict)
            or not isinstance(section.get("heading"), str)
            or not isinstance(section.get("body_markdown"), str)
        ):
            return f"article.sections[{index}] must have {{heading, body_markdown}} strings"
    if not normalize_slug(metadata["slug"]):
        return "metadata.slug normalizes to an empty string"
    return None
