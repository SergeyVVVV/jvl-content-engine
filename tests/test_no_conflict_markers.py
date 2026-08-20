"""No tracked file may carry an unresolved merge conflict.

A resolution script asserted on the wrong side of a conflict, failed, and the
markers were committed and merged into main inside .env.example. Nothing caught
it: the file is comments, so every test still passed and the app still ran.
This test is the thing that would have caught it.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Split so this file does not match itself.
MARKERS = ("<" * 7, "=" * 7, ">" * 7)

#: Binary and vendored paths that would only produce false positives.
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".woff", ".woff2"}


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [REPO_ROOT / name for name in out.split("\0") if name]


class ConflictMarkerTests(unittest.TestCase):
    def test_no_tracked_file_carries_conflict_markers(self) -> None:
        offenders: list[str] = []
        for path in tracked_files():
            if path.suffix.lower() in SKIP_SUFFIXES or path == Path(__file__):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if any(line.startswith(marker) for marker in MARKERS):
                    rel = path.relative_to(REPO_ROOT)
                    offenders.append(f"{rel}:{line_no}")
        self.assertEqual(offenders, [], "unresolved conflict markers found")


if __name__ == "__main__":
    unittest.main()
