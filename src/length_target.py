"""Turn the SERP's `comparable_length` into a word target the Writer can aim at.

The Writer used to be told "an article runs about 3000 words across 10–14 H2
sections". That number was written before the SERP agent could measure anything,
and it outranked the measurement in practice: a run whose competitors measured
1,835 words produced 5,340, because a hard-coded figure is more concrete than an
instruction to look at a field in a JSON blob.

So the target is computed here, stated in words rather than buried in the
research payload, and handed to the Writer before it writes its first draft.

Nothing here caps the article. Going longer is allowed and sometimes right — but
it has to be paid for with information the ranking articles do not carry, and
the Writer is asked to name that information rather than assert it.
"""

from __future__ import annotations

import re

#: How far either side of the median still counts as "written to the target".
#: The band, not the point, is the instruction: matching a median to the word is
#: not a thing a writer can do, or should try to.
BAND = 0.15

#: What to aim at when no article ranked, or none could be read. It is a weak
#: default and says so — the alternative is inventing a target, which is how the
#: 3000 got there in the first place.
FALLBACK_WORDS = 2000

#: Past this multiple of the median, extra length stops being a judgement call.
#: A draft three times its competitors is not answering an unanswered question;
#: it is padding, and padding is what the run above produced.
HARD_MULTIPLE = 1.6


def resolve(comparable_length: dict | None) -> dict:
    """Compute the target band from the SERP measurement.

    Returns a dict with `median`, `low`, `high`, `ceiling`, `measured` and the
    SERP's own `sample_size` and `note`, so the prompt can show its working.
    """
    data = comparable_length or {}
    median = data.get("median_words")
    measured = isinstance(median, int) and median > 0
    if not measured:
        median = FALLBACK_WORDS
    return {
        "median": median,
        "low": int(median * (1 - BAND)),
        "high": int(median * (1 + BAND)),
        "ceiling": int(median * HARD_MULTIPLE),
        "measured": measured,
        "sample_size": data.get("sample_size") or 0,
        "positions": [p for p in (data.get("positions") or []) if isinstance(p, int)],
        "note": data.get("note") or "",
    }


def render(target: dict) -> str:
    """Render the target as the length block of the Writer's user message."""
    if not target["measured"]:
        return (
            "# LENGTH TARGET\n\n"
            f"No article ranked in the top results, or none could be read, so "
            f"there is no measurement to work from. Aim at roughly "
            f"{FALLBACK_WORDS} words and let the material decide. Do not treat "
            f"that figure as evidence of anything — it is a default, not a "
            f"finding.\n"
        )

    sample = target["sample_size"]
    basis = (
        f"the single article that ranked"
        if sample == 1
        else f"the {sample} articles that ranked"
    )
    # Where the sample sat matters. The SERP is read to ten because commercial
    # queries often put nothing but shop pages in the first five, and the guides
    # start at six — but an article at nine is weaker evidence about this query
    # than one at two, and the Writer should be told which it got.
    positions = target["positions"]
    if positions and min(positions) > 5:
        rank_note = (
            f" Every article counted ranked below position 5 (at "
            f"{', '.join(str(p) for p in sorted(positions))}), so treat the "
            f"figure as a weaker signal than a top-five article would be."
        )
    elif positions:
        rank_note = f" Ranked at {', '.join(str(p) for p in sorted(positions))}."
    else:
        rank_note = ""

    lines = [
        "# LENGTH TARGET",
        "",
        f"Write **{target['low']}–{target['high']} words**. The median of "
        f"{basis} on this query is {target['median']} words; commerce pages "
        f"were excluded, because a shop category page's word count measures its "
        f"product grid and footer.{rank_note}",
        "",
        "This is a measurement of what this query rewards, not a preference. "
        "Land inside the band unless you can do the following.",
        "",
        "**Going longer has to be earned, and earning it is a specific act.** "
        "You may exceed the band when the draft carries information the ranking "
        "articles do not — a figure they omit, a scenario they never model, a "
        "cost they leave out, a question their readers are left holding. When "
        "you do, name it: put the justification in the companion JSON field "
        "`length_justification`, stating what the extra words carry and which "
        "competitor gap they close. One sentence is enough, and a sentence you "
        "cannot write is the proof that the words are padding.",
        "",
        f"**Past {target['ceiling']} words that stops being a judgement call.** "
        "A draft well over half again its competitors' length is not answering "
        "an unanswered question, whatever the outline says. If the material "
        "genuinely runs that long, the article was scoped too broadly — cut a "
        "section rather than compress every explanation in it.",
        "",
        "Length is prose plus tables, lists and quotes together — the whole "
        "article as the reader meets it, excluding the FAQ, which is generated "
        "separately and does not count toward this target.",
    ]
    if target["note"]:
        lines += ["", f"How the measurement was made: {target['note']}"]
    return "\n".join(lines) + "\n"


#: Below this share of the band's floor the article is thin against what ranks.
#: Symmetric with the ceiling and measured the same way; a draft well under the
#: articles it competes with has left the reader's question half answered.
THIN_MULTIPLE = 1.0

_FAQ_HEADING = re.compile(r"^##\s+(?:FAQ|Frequently\s+Asked)", re.IGNORECASE | re.MULTILINE)
_SOURCES_HEADING = re.compile(r"^##\s+Sources\b", re.IGNORECASE | re.MULTILINE)


def article_word_count(markdown: str) -> int:
    """Count the article as the reader meets it, minus the appended blocks.

    Prose, tables, lists and quotes all count — the target measures competitor
    pages the same way. The FAQ and the sources block do not: both are generated
    by later steps and shipped as their own units, so counting them would move
    the target for reasons the Writer has no control over.
    """
    body = markdown
    for pattern in (_FAQ_HEADING, _SOURCES_HEADING):
        match = pattern.search(body)
        if match:
            body = body[: match.start()]
    stripped = re.sub(r"[#*>`\[\]()|_~-]", " ", body)
    return len(stripped.split())


def assess(target: dict, word_count: int, justification: str | None = None) -> dict:
    """Judge a finished draft against the target and say what to do about it.

    This exists because the rule it enforces cannot be enforced where it was
    written. The Writer was told to fill `length_justification` when it ran past
    the band — but it never learns its own word count, because the count does not
    exist until it has stopped writing. A measured draft landed 6% over the band
    with the field empty, which read as disobedience and was closer to an
    impossible instruction.

    So the trigger moves here, where the number is known.
    """
    low, high, ceiling = target["low"], target["high"], target["ceiling"]
    named = bool(justification and justification.strip())

    if word_count > ceiling:
        # Past the hard multiple a justification cannot buy the words back. A
        # draft this far over was scoped too broadly, and the fix is a section
        # fewer rather than every explanation compressed.
        return {
            "verdict": "over_ceiling",
            "word_count": word_count,
            "justified": named,
            "problem": (
                f"The draft runs {word_count} words against a target band of "
                f"{low}-{high}, past the {ceiling}-word point where extra length "
                "stops being a judgement call. Cut a whole section rather than "
                "compressing every explanation in the article: decide which "
                "section the reader would miss least, and remove it."
            ),
        }

    if word_count > high:
        if named:
            return {
                "verdict": "over_band_justified",
                "word_count": word_count,
                "justified": True,
                "problem": None,
            }
        over = round((word_count - high) / high * 100)
        return {
            "verdict": "over_band",
            "word_count": word_count,
            "justified": False,
            "problem": (
                f"The draft runs {word_count} words, {over}% past the top of the "
                f"{low}-{high} band, and `length_justification` is empty. Either "
                "cut back into the band, or fill that field with the specific "
                "thing those words carry that the ranking articles do not — a "
                "figure none of them publishes, a scenario none of them models. "
                "Do not write that the topic is complex."
            ),
        }

    if word_count < low:
        short = round((low - word_count) / low * 100)
        return {
            "verdict": "thin",
            "word_count": word_count,
            "justified": named,
            "problem": (
                f"The draft runs {word_count} words, {short}% under the {low}-{high} "
                "band, so it is thinner than the articles it competes with. Find "
                "the question the article raises and leaves hanging, and answer "
                "it. Do not pad an existing section to make up the difference."
            ),
        }

    return {
        "verdict": "inside",
        "word_count": word_count,
        "justified": named,
        "problem": None,
    }
