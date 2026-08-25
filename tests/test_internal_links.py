"""Every internal link the engine is told to use must resolve.

`https://jvl.ca/en/home` was in the knowledge base and both agent prompts as a
link to insert, described variously as the homepage, the "Home overview page"
and the "Echo for Home page". It returns 404, and had been shipping inside
articles.

The homepage is `https://www.jvl.ca/en`.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

#: Where the engine is told which URLs to link to.
SOURCES = (
    "knowledge/internal_links.md",
    "knowledge/claims_constraints.md",
    "knowledge/product_echo_home.md",
    "knowledge/content_directions.md",
    "prompts/writer_agent.md",
    "prompts/brief_agent.md",
    "prompts/seo_structure_agent.md",
)

#: Paths confirmed to return 200.
LIVE_PATHS = {"/en", "/en/echo"}

_JVL_URL_RE = re.compile(r"https?://(?:www\.)?jvl\.ca(/[\w./-]*)")


def linked_paths() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for rel in SOURCES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for path in _JVL_URL_RE.findall(text):
            found.setdefault(path.rstrip("/") or "/", []).append(rel)
    return found


class LinkTargetTests(unittest.TestCase):
    def test_the_dead_home_path_is_gone(self) -> None:
        self.assertNotIn("/en/home", linked_paths())

    def test_every_linked_path_is_one_known_to_resolve(self) -> None:
        # A new target is fine — but confirm it returns 200 and add it here,
        # rather than discovering the 404 in a published article.
        for path, files in linked_paths().items():
            self.assertIn(path, LIVE_PATHS, f"{path} appears in {files}")

    def test_the_homepage_is_named_consistently(self) -> None:
        # It was called three different things in three files, which is how a
        # 404 survives: nobody agreed on what the page was.
        claims = (REPO_ROOT / "knowledge" / "claims_constraints.md").read_text(encoding="utf-8")
        self.assertIn("- Homepage: https://www.jvl.ca/en", claims)
        self.assertNotIn("Home overview page", claims)

    def test_the_unconfirmed_business_page_is_not_linked(self) -> None:
        claims = (REPO_ROOT / "knowledge" / "claims_constraints.md").read_text(encoding="utf-8")
        self.assertIn("whether a separate Echo-for-Business", claims)


if __name__ == "__main__":
    unittest.main()
