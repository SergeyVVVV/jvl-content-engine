"""Every prompt/schema path referenced in src/ must exist on disk.

Cheap guard against two failure modes this repo has already hit:
a file deleted while something still loads it, and a file kept around that
nothing loads (which then drifts and misleads whoever reads it next).
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

ASSET_RE = re.compile(r"[\"'](?P<path>(?:prompts|schemas)/[\w./-]+\.(?:md|json))[\"']")


def referenced_assets() -> dict[str, list[str]]:
    """Map asset path -> source files that mention it."""
    found: dict[str, list[str]] = {}
    for source in sorted((REPO_ROOT / "src").glob("*.py")):
        for match in ASSET_RE.finditer(source.read_text()):
            found.setdefault(match.group("path"), []).append(source.name)
    return found


class AssetReferenceTests(unittest.TestCase):
    def test_every_referenced_asset_exists(self) -> None:
        missing = {
            path: sources
            for path, sources in referenced_assets().items()
            if not (REPO_ROOT / path).exists()
        }
        self.assertEqual(missing, {}, f"referenced but missing: {missing}")

    def test_reference_map_is_not_empty(self) -> None:
        # Guards the regex itself: a silent zero would make the test above pass
        # no matter what got deleted.
        self.assertGreater(len(referenced_assets()), 5)

    def test_no_schema_is_orphaned(self) -> None:
        """A schema nothing loads is the exact shape of the bug that broke the
        publish contract. schemas/README.md is documentation, not a schema."""
        referenced = set(referenced_assets())
        orphans = sorted(
            f"schemas/{path.name}"
            for path in (REPO_ROOT / "schemas").glob("*.json")
            if f"schemas/{path.name}" not in referenced
        )
        self.assertEqual(orphans, [], f"loaded by nothing: {orphans}")


if __name__ == "__main__":
    unittest.main()
