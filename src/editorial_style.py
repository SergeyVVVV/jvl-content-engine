"""Two editorial styles, one switch, and a default that changes nothing.

Every number below already existed, scattered across readability_agent,
length_target and the Writer's prompt. Collecting them here is what makes a
style something you can change and change back, rather than a day of edits
spread over three files.

STYLE_1 is the engine as it shipped: the values are copied across unchanged, so
selecting it produces byte-identical behaviour to before this module existed.
It is the default, and it stays the default until STYLE_2 has been run and read.

STYLE_2 is the shorter-block style, measured against a site that does it well.
Its whole content is: paragraphs get a ceiling, sections get shorter so more of
them fit, and the prompt asks for more frequent breaks. Nothing in it is a
floor — no rule forces a heading, a list or a table where the material does not
want one, because a rule that compels structure produces structure whether or
not there is anything to structure.

What no style touches: article length against the ranking articles, the
sentence-length tail, vocabulary weight, reading ease, the unbroken-prose
ceiling, and every rule about claims, prices and the product. A style is the
rhythm of delivery. It is not a licence to say different things.
"""

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class EditorialStyle:
    """The knobs that decide how an article is broken up."""

    name: str

    #: Longest paragraph, in words. None means unbounded — which is what the
    #: engine did until STYLE_2, and how a 153-word paragraph shipped.
    max_paragraph_words: int | None

    #: Prose words a single H2 section carries. The floor keeps a section from
    #: being a stub; the ceiling keeps it from absorbing its neighbour's point.
    section_prose_min: int
    section_prose_max: int

    #: What one section costs when the length allowance is divided up. Lower
    #: means more sections fit inside the same word target — which is how
    #: STYLE_2 gets more headings without ever requiring one.
    words_per_section: int

    #: Sentences in a paragraph, as guidance in the prompt rather than a check.
    paragraph_sentences: str

    #: Headings the prompt suggests for a mid-length article. Guidance only:
    #: making this a floor would force signposts onto prose that flows without
    #: them, and a forced heading is worse than a missing one.
    heading_hint: str

    #: A prompt file that replaces writer_agent.md rather than adjusting it.
    #: None keeps the shared prompt, which is what STYLE_1 and STYLE_2 do.
    prompt_file: str | None = None


STYLE_1 = EditorialStyle(
    name="Editorial_Style_1",
    max_paragraph_words=None,
    section_prose_min=250,
    section_prose_max=350,
    words_per_section=350,
    paragraph_sentences="three to six sentences",
    heading_hint="no more than one heading per 190 words of the length target",
)

STYLE_2 = EditorialStyle(
    name="Editorial_Style_2",
    # 110 rather than the 70 the reference site averages: measured across five
    # of our own articles the paragraphs already run 50-59 words on average and
    # 90-132 at the longest, so this trims the tail without rewriting the voice.
    max_paragraph_words=110,
    section_prose_min=200,
    section_prose_max=300,
    words_per_section=300,
    paragraph_sentences="two to five sentences",
    heading_hint=(
        "no more than one heading per 190 words of the length target, and on a "
        "2,500-word article around ten is the comfortable number — under eight "
        "and the reader walks a long way between signposts"
    ),
)

STYLE_3 = EditorialStyle(
    name="Editorial_Style_3",
    # Measured across ten articles on a site that does this well, then loosened
    # by 15% because our subjects argue where theirs enumerate. Every figure is
    # the 25th-75th percentile of the sample, not a single article's number.
    #
    #                     sample 25-75      +15%      taken as
    #   words/heading        107-129       123-148     120-150
    #   paragraph mean         33-51         38-59       —
    #   paragraph 90th         59-84         68-97       —
    #   paragraph max         94-129       108-148       140
    #   sentences/paragraph  1.5-2.6           2-3       2-4
    max_paragraph_words=140,
    section_prose_min=150,
    section_prose_max=280,
    words_per_section=260,
    paragraph_sentences="two to four sentences",
    heading_hint=(
        "aim for a heading roughly every 120 to 150 words of the length target "
        "— a 2,500-word article carries somewhere between sixteen and twenty "
        "H2 and H3 headings together, and the H3s do most of that work"
    ),
    prompt_file="prompts/writer_agent_style3.md",
)

_STYLES = {s.name: s for s in (STYLE_1, STYLE_2, STYLE_3)}

#: The active style. Change this line to switch, and change it back to revert.
#: EDITORIAL_STYLE in the environment overrides it for a single run.
ACTIVE = STYLE_1


def active() -> EditorialStyle:
    """The style this run writes in."""
    name = os.environ.get("EDITORIAL_STYLE", "").strip()
    if not name:
        return ACTIVE
    if name in _STYLES:
        return _STYLES[name]
    print(
        f"EDITORIAL_STYLE={name!r} is not one of {', '.join(_STYLES)} — "
        f"using {ACTIVE.name}.",
        file=sys.stderr,
    )
    return ACTIVE
