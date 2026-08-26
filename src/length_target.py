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
    lines = [
        "# LENGTH TARGET",
        "",
        f"Write **{target['low']}–{target['high']} words**. The median of "
        f"{basis} on this query is {target['median']} words; commerce pages "
        f"were excluded, because a shop category page's word count measures its "
        f"product grid and footer.",
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
