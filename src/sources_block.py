"""The sources list that closes an article — JVL Content Engine.

Citing sources is not a ranking factor. Google documents no such thing, and the
2026 industry reading is consistent: outbound links are not direct signals, they
support E-E-A-T, and E-E-A-T reaches ranking indirectly through quality
assessment. So this block is built for the reader first, and the search benefit
follows from that rather than the other way round.

Two consequences shape everything here. A short, chosen list reads as editorial
judgement; a long one reads as an automated dump, and the second is worse than
having none. And a bare URL demonstrates nothing — what a person and a machine
both read is a descriptive title, the publisher, and a date.

The block appears whenever the article leaned on anything at all, down to a
single entry. It disappears only when there was no research to show — a heading
over an empty list is worse than no heading.
"""

from __future__ import annotations

from urllib.parse import urlparse

#: One source is enough to list. If the article leaned on something, the
#: reader gets to see what — the alternative is a figure the reader is invited
#: to trust and cannot check, which is the problem this block exists to solve.
MIN_SOURCES = 1

#: More than this and it stops looking chosen.
MAX_SOURCES = 7

#: Ranked by what a reader should weigh most. An operator running machines knows
#: something a business-plan blog is guessing at, and a seller has an interest.
_KIND_RANK = {
    "operator": 0,
    "industry": 1,
    "press": 2,
    "forum": 3,
    "unknown": 4,
    "vendor": 5,
    "own_site": 6,
}

#: Our own site is never a source. Citing jvl.ca as independent evidence for
#: what a machine earns is circular, and a reader who follows the link and
#: lands on our own blog discounts everything above it.
_EXCLUDED_KINDS = {"own_site"}


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return url.lower()
    return host[4:] if host.startswith("www.") else host


def select_sources(facts: dict, limit: int = MAX_SOURCES) -> list[dict]:
    """Pick the few sources worth showing, best first.

    One per publisher: the same site appearing three times is one voice, and
    listing it three times overstates the weight of its evidence.
    """
    if not facts:
        return []

    candidates: list[dict] = []
    for finding in facts.get("findings", []) or []:
        for source in finding.get("sources", []) or []:
            kind = (source.get("kind") or "unknown").lower()
            url = source.get("url") or ""
            if not url or kind in _EXCLUDED_KINDS:
                continue
            candidates.append({
                "title": (source.get("title") or "").strip(),
                "url": url,
                "publisher": _domain(url),
                "kind": kind,
                "date": (source.get("date") or "").strip(),
                "figure": (source.get("figure") or "").strip(),
            })

    candidates.sort(
        key=lambda s: (
            _KIND_RANK.get(s["kind"], 9),
            0 if s["date"] else 1,       # a dated source can be judged for age
            0 if s["title"] else 1,
        )
    )

    chosen: list[dict] = []
    seen: set[str] = set()
    for source in candidates:
        if source["publisher"] in seen:
            continue
        seen.add(source["publisher"])
        chosen.append(source)
        if len(chosen) >= limit:
            break
    return chosen


def render(facts: dict, heading: str = "Sources") -> str:
    """Render the block, or an empty string when it would not earn its place."""
    chosen = select_sources(facts)
    if len(chosen) < MIN_SOURCES:
        return ""

    lines = [f"## {heading}", ""]
    for source in chosen:
        title = source["title"] or source["publisher"]
        parts = [f"- [{title}]({source['url']})", f"— {source['publisher']}"]
        if source["date"]:
            parts.append(f", {source['date']}")
        line = " ".join(parts[:2]) + (parts[2] if len(parts) > 2 else "")
        if source["kind"] == "vendor":
            line += " (supplier)"
        lines.append(line)
    return "\n".join(lines).strip()


def append_to_article(draft_markdown: str, sources_markdown: str) -> str:
    """Put the block at the end, after the FAQ, before any review block."""
    if not sources_markdown:
        return draft_markdown

    import re

    # Any heading a writer might reach for when it decides to list its links.
    # A QA revision does not drop this block, it *rewrites* it: shown an article
    # that ends in a list of links, the Writer produces its own list. Matching
    # only "Sources" would leave a "References" section beside the real one.
    existing = re.compile(
        r"(?ms)^##\s+(?:Sources|References|Citations|Further\s+reading)\b"
        r".*?(?=^##\s|\n---\s*\n+##\s+(?:Claims to Verify|Open TODOs)|\Z)",
        re.IGNORECASE,
    )
    stripped = existing.sub("", draft_markdown).rstrip() + "\n"

    marker = re.search(
        r"\n---\s*\n+##\s+(?:Claims to Verify|Open TODOs)", stripped
    )
    if marker:
        head = stripped[: marker.start()].rstrip()
        tail = stripped[marker.start():]
        return f"{head}\n\n{sources_markdown}\n{tail}"
    return f"{stripped.rstrip()}\n\n{sources_markdown}\n"
