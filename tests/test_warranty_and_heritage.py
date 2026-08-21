"""Claims settled in money, and two spans of time that keep getting swapped.

An article inferred that because the warranty is "all-inclusive" and a
Commercial Edition exists, commercial installation must be covered on the same
terms. It happened to be right — the business confirmed it afterwards. The next
inference will not be, and a reader holding our page while a manufacturer
refuses a claim is a different kind of problem from a wrong statistic.

Separately, the product page says "40+ years of JVL bartop expertise" while the
knowledge base said "30+". Both numbers are real: 40+ is the company, 30+ is the
bartop line, which began in 1995.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class WarrantyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.claims = read("knowledge/claims_constraints.md")

    def test_both_editions_are_covered_on_the_same_terms(self) -> None:
        self.assertIn("Commercial Edition, on the same terms", self.claims)

    def test_conditions_beyond_term_and_scope_may_not_be_inferred(self) -> None:
        self.assertIn("Warranty claim rules", self.claims)
        self.assertIn("Say nothing else about it", self.claims)

    def test_who_pays_return_shipping_is_no_longer_a_free_claim(self) -> None:
        # It arrived in an April import and was never re-confirmed. A promise
        # settled in money does not belong in "use freely" on that basis.
        # The phrase survives inside the TODO that questions it; what must be
        # gone is the bullet asserting it as fact.
        for rel in ("knowledge/claims_constraints.md",
                    "knowledge/product_echo_home.md",
                    "knowledge/positioning_uvp.md"):
            for line in read(rel).splitlines():
                stripped = line.strip()
                if stripped.startswith("- ") and "TODO" not in stripped:
                    self.assertNotIn("covers shipping both ways", stripped, rel)

    def test_the_open_question_is_recorded_rather_than_deleted(self) -> None:
        self.assertIn("who pays return\n  shipping", self.claims.replace("\r", ""))


class HeritageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.claims = read("knowledge/claims_constraints.md")

    def test_both_spans_are_recorded(self) -> None:
        self.assertIn("40+ years of JVL as a company", self.claims)
        self.assertIn("30+ years of JVL **bartop** expertise", self.claims)

    def test_the_rule_says_not_to_swap_them(self) -> None:
        self.assertIn("must not be swapped", self.claims)

    def test_the_bartop_span_stays_anchored_to_1995(self) -> None:
        # 1995 is what makes "30+" checkable rather than a slogan, and it is
        # also what makes "40+ years of bartop expertise" wrong.
        self.assertIn("bartop line began in 1995", self.claims)
        self.assertIn("since 1995", read("knowledge/firsthand_experience.md"))


class AcceptorAndCaptionTests(unittest.TestCase):
    def test_the_payment_hardware_spec_is_now_an_allowed_claim(self) -> None:
        # QA flagged it as unsourced on two consecutive runs; it was real, it
        # just lived only in product_echo_home.md.
        self.assertIn("500-bill capacity", read("knowledge/claims_constraints.md"))

    def test_a_caption_may_not_name_the_product_above_the_closing_section(self) -> None:
        rules = read("knowledge/visual_style_rules.md")
        self.assertIn("may not name the product outside the closing product section", rules)


if __name__ == "__main__":
    unittest.main()
