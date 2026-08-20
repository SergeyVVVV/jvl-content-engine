"""Money must not render as mathematics.

A published draft displayed as gibberish: Streamlit reads `$...$` as LaTeX, and
an article about payback periods carried 78 dollar signs, so everything between
the first and second became an italic formula. The markdown was correct. Nothing
in the pipeline renders the article, so no agent could have caught it — which is
why the guard is here rather than in a review step.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.markdown_render import escape_dollars  # noqa: E402


class EscapeDollarsTests(unittest.TestCase):
    def test_the_line_that_broke(self) -> None:
        src = "it includes a bill acceptor taking $1, $5, $10, and $20 notes"
        out = escape_dollars(src)
        self.assertEqual(out.count(r"\$"), 4)
        # Every one of them escaped — an unescaped "$1," would start a formula.
        self.assertEqual(out.count("$"), out.count(r"\$"))

    def test_arithmetic_survives(self) -> None:
        src = "Weekly gross is 85 x $1.00 = **$85**. Payback on $4,250 is 12.4 months."
        out = escape_dollars(src)
        self.assertEqual(out.count(r"\$"), 3)
        self.assertIn(r"**\$85**", out)
        self.assertIn("12.4 months", out)

    def test_text_without_money_is_untouched(self) -> None:
        src = "# Heading\n\nA paragraph with *emphasis* and a [link](https://x)."
        self.assertEqual(escape_dollars(src), src)

    def test_inline_code_is_left_alone(self) -> None:
        # A dollar inside code is already literal; escaping shows a backslash.
        src = "Set `$PATH` before running."
        self.assertEqual(escape_dollars(src), src)

    def test_fenced_blocks_are_left_alone(self) -> None:
        src = "before $5\n\n```bash\necho $HOME\n```\n\nafter $6"
        out = escape_dollars(src)
        self.assertIn("echo $HOME", out)
        self.assertIn(r"before \$5", out)
        self.assertIn(r"after \$6", out)

    def test_an_already_escaped_dollar_is_not_doubled(self) -> None:
        self.assertEqual(escape_dollars(r"costs \$5"), r"costs \$5")

    def test_empty_input(self) -> None:
        self.assertEqual(escape_dollars(""), "")

    def test_a_real_article_escapes_every_bare_dollar(self) -> None:
        draft = REPO_ROOT / "outputs" / "v3" / "drafts" / (
            "how-fast-can-an-arcade-machine-pay-for-itself-in-a-bar-or-ev.md"
        )
        if not draft.exists():
            self.skipTest("sample draft not present")
        text = draft.read_text(encoding="utf-8")
        out = escape_dollars(text)
        # No bare dollar left outside code, and the source itself is unchanged.
        import re
        stripped = re.sub(r"(```.*?```|`[^`\n]+`)", "", out, flags=re.DOTALL)
        self.assertIsNone(re.search(r"(?<!\\)\$", stripped))
        self.assertIn("$", text)


class StructureRuleTests(unittest.TestCase):
    """The prompt must ask for the form the content actually is.

    One draft came back a third bullets; the correction produced unbroken
    columns of prose with a three-scenario comparison buried inside a paragraph.
    Both are failures, and a quota in either direction causes one of them.
    """

    def setUp(self) -> None:
        self.prompt = (REPO_ROOT / "prompts" / "writer_agent.md").read_text(
            encoding="utf-8"
        )

    def test_a_comparison_must_be_a_table(self) -> None:
        self.assertIn("A comparison is a table. This is not optional.", self.prompt)
        self.assertIn("required, not suggested", self.prompt)

    def test_the_blanket_quota_is_gone(self) -> None:
        # The over-correction that squeezed out tables along with lists.
        self.assertNotIn("one list or table per two H2", self.prompt)

    def test_reasoning_still_belongs_in_prose(self) -> None:
        self.assertIn("A list is for items, not for argument.", self.prompt)

    def test_sections_still_open_with_prose(self) -> None:
        self.assertIn("Never open a section with a list or a table", self.prompt)


if __name__ == "__main__":
    unittest.main()
