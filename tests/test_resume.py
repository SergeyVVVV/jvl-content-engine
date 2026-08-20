"""A failed run should not have to pay for its research twice.

A run died at the Writer after thirty-five minutes, discarding twelve billed
searches and five completed steps. The intermediate files were on disk the whole
time; nothing could read them back. `--skip` was no help — it omits a step, so
skipping Fact Research leaves the Writer with no figures at all, which is a
different article rather than the same one resumed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.orchestrator import _reuse  # noqa: E402


class ReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "facts.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_nothing_is_reused_unless_asked(self) -> None:
        self.path.write_text(json.dumps({"findings": [1]}), encoding="utf-8")
        self.assertIsNone(_reuse(self.path, "Fact Research", reuse=False))

    def test_a_previous_result_comes_back(self) -> None:
        self.path.write_text(json.dumps({"findings": [1, 2]}), encoding="utf-8")
        self.assertEqual(_reuse(self.path, "Fact Research", True), {"findings": [1, 2]})

    def test_a_missing_file_runs_the_step(self) -> None:
        self.assertIsNone(_reuse(self.path, "Fact Research", True))

    def test_a_corrupt_file_runs_the_step_instead_of_raising(self) -> None:
        # Half-written JSON from a killed run must not take the next one down.
        self.path.write_text('{"findings": [', encoding="utf-8")
        self.assertIsNone(_reuse(self.path, "Fact Research", True))


class ScopeTests(unittest.TestCase):
    """Only the steps whose output depends on the topic, nothing downstream.

    A stale brief for the same topic is the same brief. A stale draft is a
    different article, and reusing one would silently publish yesterday's work.
    """

    def setUp(self) -> None:
        self.source = (REPO_ROOT / "src" / "orchestrator.py").read_text(encoding="utf-8")

    def test_the_expensive_early_steps_are_reusable(self) -> None:
        for path_var in ("brief_path", "facts_path", "serp_path",
                         "insight_path", "seo_path"):
            self.assertIn(f"_reuse({path_var}", self.source, path_var)

    def test_the_draft_is_never_reused(self) -> None:
        # Everything from the Writer on must be regenerated.
        for name in ("draft_md_path", "draft_json_path"):
            self.assertNotIn(f"_reuse({name}", self.source)

    def test_the_cli_exposes_it(self) -> None:
        cli = (REPO_ROOT / "run_article.py").read_text(encoding="utf-8")
        self.assertIn('"--resume"', cli)
        self.assertIn("reuse=args.resume", cli)


if __name__ == "__main__":
    unittest.main()
