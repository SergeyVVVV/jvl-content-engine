"""Preparing article markdown for display — JVL Content Engine.

Streamlit's markdown renderer reads `$...$` as LaTeX. An article about payback
periods is full of dollar amounts, so a correct draft renders as gibberish:

    it includes a bill acceptor taking $1, $5, $10, and $20 notes

becomes a run of italic mathematics, because everything between the first and
second dollar sign is treated as a formula. One published draft carried 78
dollar signs. Nothing was wrong with the text — nothing in the pipeline renders
the article, so no agent could have seen it.

The escaping belongs here, at display time. The stored markdown stays clean:
what goes to the site must keep its plain dollar signs.
"""

from __future__ import annotations

import re

#: Fenced blocks and inline code, captured so they can be left alone. A dollar
#: sign inside code is already literal, and escaping it would put a visible
#: backslash on the page.
_CODE_RE = re.compile(r"(```.*?```|`[^`\n]+`)", re.DOTALL)

#: A dollar sign that is not already escaped.
_BARE_DOLLAR_RE = re.compile(r"(?<!\\)\$")


def escape_dollars(markdown: str) -> str:
    """Escape dollar signs so a renderer does not read money as mathematics.

    Code spans and fenced blocks are left untouched.
    """
    if not markdown:
        return markdown

    parts = _CODE_RE.split(markdown)
    # split() with one capturing group alternates: text, code, text, code, …
    for i in range(0, len(parts), 2):
        parts[i] = _BARE_DOLLAR_RE.sub(r"\\$", parts[i])
    return "".join(parts)
