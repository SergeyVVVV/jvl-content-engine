"""Tests for the shared pipeline orchestrator.

No network and no LLM calls: the agents are replaced with fakes and every
optional step is skipped, so what's under test is the wiring — step order,
event numbering, and the guarantee that both entry points run the same agents.
"""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import src.orchestrator as orch  # noqa: E402
from src.orchestrator import (  # noqa: E402
    PIPELINE_STEPS,
    SKIPPABLE,
    UPDATE_STEPS,
    pipeline_steps,
)


class StepRegistryTests(unittest.TestCase):
    def test_default_order(self) -> None:
        self.assertEqual(
            pipeline_steps(),
            ["Brief", "SERP Research", "Company Insight", "SEO Structure", "Writer",
             "Readability Checker", "FAQ Agent", "QA Review", "Metadata"],
        )

    def test_visuals_run_before_the_faq_block_is_appended(self) -> None:
        steps = pipeline_steps(with_visuals=True)
        self.assertIn("Visual Agent", steps)
        self.assertLess(steps.index("Visual Agent"), steps.index("FAQ Agent"))
        self.assertGreater(steps.index("Visual Agent"), steps.index("Writer"))

    def test_visuals_are_off_by_default(self) -> None:
        self.assertNotIn("Visual Agent", pipeline_steps())

    def test_pipeline_steps_returns_a_copy(self) -> None:
        pipeline_steps().append("Nonsense")
        self.assertNotIn("Nonsense", PIPELINE_STEPS)

    def test_skippable_names_are_real_steps(self) -> None:
        every = set(pipeline_steps(with_visuals=True))
        self.assertEqual(SKIPPABLE - every, set())

    def test_brief_and_writer_cannot_be_skipped(self) -> None:
        # Nothing downstream can run without them.
        self.assertNotIn("Brief", SKIPPABLE)
        self.assertNotIn("Writer", SKIPPABLE)


class _FakeBrief:
    def run(self, **kwargs) -> dict:
        return {
            "primary_keyword": kwargs.get("primary_keyword", "kw"),
            "working_title": "Working Title",
            "search_intent": "informational",
            "funnel_stage": kwargs.get("funnel_stage", "mid"),
            "product_fit": "high",
            "questions_to_answer": [],
        }


class _FakeWriter:
    def run(self, **kwargs) -> dict:
        return {
            "h1": "Fake H1",
            "claims_to_verify": [],
            "internal_links_used": [],
            "suggested_visuals": [],
            "todos": [],
        }

    @staticmethod
    def assemble_markdown(result: dict) -> str:
        return "# Fake H1\n\nLead paragraph.\n\n## Section\n\nBody.\n"


class PipelineEventTests(unittest.TestCase):
    """Drive the generator with fakes and check the event stream."""

    def setUp(self) -> None:
        self._saved = (orch.BriefAgent, orch.WriterAgent, orch.save_to_history)
        orch.BriefAgent, orch.WriterAgent = _FakeBrief, _FakeWriter
        orch.save_to_history = lambda entry: None
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        orch.BriefAgent, orch.WriterAgent, orch.save_to_history = self._saved
        self._tmp.cleanup()

    def run_pipeline(self, **kwargs):
        events, results = [], None
        for event in orch.run_pipeline(
            topic="Fake Topic",
            primary_keyword="fake keyword",
            funnel_stage="mid",
            secondary_keywords=[],
            custom_requirements="",
            output_root=self.root,
            skip=set(SKIPPABLE),
            **kwargs,
        ):
            if event["step"] == 0:
                results = event["results"]
            else:
                events.append(event)
        return events, results

    def test_every_step_reports_running_then_done(self) -> None:
        events, _ = self.run_pipeline()
        expected = [(label, status)
                    for label in pipeline_steps()
                    for status in ("running", "done")]
        self.assertEqual([(e["label"], e["status"]) for e in events], expected)

    def test_step_numbers_match_the_registry(self) -> None:
        events, _ = self.run_pipeline()
        for event in events:
            self.assertEqual(event["step"], pipeline_steps().index(event["label"]) + 1)

    def test_numbering_stays_consistent_with_visuals_on(self) -> None:
        events, _ = self.run_pipeline(with_visuals=True)
        labels = [e["label"] for e in events if e["status"] == "running"]
        self.assertEqual(labels, pipeline_steps(with_visuals=True))
        for event in events:
            self.assertEqual(
                event["step"], pipeline_steps(with_visuals=True).index(event["label"]) + 1
            )

    def test_skipped_steps_leave_their_results_empty_but_still_finish(self) -> None:
        _, results = self.run_pipeline()
        self.assertIsNone(results["serp_data"])
        self.assertIsNone(results["qa_report"])
        self.assertIsNone(results["metadata"])

    def test_the_draft_is_still_written_when_everything_optional_is_skipped(self) -> None:
        _, results = self.run_pipeline()
        self.assertTrue(results["draft_md_path"].exists())
        self.assertIn("## Section", results["draft_markdown"])

    def test_output_root_is_honoured(self) -> None:
        _, results = self.run_pipeline()
        self.assertTrue(str(results["draft_md_path"]).startswith(str(self.root)))


class EntryPointTests(unittest.TestCase):
    """The reason this module exists: no entry point may wire agents itself."""

    AGENT_NAMES = {
        "BriefAgent", "SerpResearchAgent", "CompanyInsightAgent", "SeoStructureAgent",
        "WriterAgent", "ReadabilityChecker", "FAQAgent", "QAAgent",
        "MetadataCopyAgent", "ArticleDiagnosticAgent", "VisualAgent",
    }

    def agents_imported_by(self, filename: str) -> set[str]:
        tree = ast.parse((REPO_ROOT / filename).read_text())
        imported = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        return imported & self.AGENT_NAMES

    def test_streamlit_app_does_not_import_agents(self) -> None:
        self.assertEqual(self.agents_imported_by("app.py"), set())

    def test_cli_does_not_import_agents(self) -> None:
        self.assertEqual(self.agents_imported_by("run_article.py"), set())

    def test_orchestrator_is_the_only_place_that_does(self) -> None:
        self.assertEqual(self.agents_imported_by("src/orchestrator.py"), self.AGENT_NAMES)


class CliTests(unittest.TestCase):
    def test_unknown_skip_value_is_rejected(self) -> None:
        import contextlib
        import io
        import run_article

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run_article.main(
                ["--topic", "t", "--primary-keyword", "k", "--skip", "Nope"]
            )
        self.assertEqual(code, 2)
        self.assertIn("Unknown --skip value", stderr.getvalue())

    def test_skip_values_are_the_step_labels(self) -> None:
        import run_article

        parser = run_article.build_parser()
        args = parser.parse_args(
            ["--topic", "t", "--primary-keyword", "k", "--skip", "QA Review"]
        )
        self.assertEqual(set(args.skip) - SKIPPABLE, set())

    def test_visuals_are_opt_in(self) -> None:
        import run_article

        args = run_article.build_parser().parse_args(
            ["--topic", "t", "--primary-keyword", "k"]
        )
        self.assertFalse(args.with_visuals)


class UpdatePipelineTests(unittest.TestCase):
    def test_update_steps_are_distinct_and_ordered(self) -> None:
        self.assertEqual(len(UPDATE_STEPS), len(set(UPDATE_STEPS)))
        self.assertEqual(UPDATE_STEPS[0], "SERP Research (fresh)")
        self.assertEqual(UPDATE_STEPS[-1], "Metadata (refresh)")

    def test_update_pipeline_runs_the_agents_the_cli_used_to_miss(self) -> None:
        self.assertIn("Readability Checker", UPDATE_STEPS)
        self.assertIn("FAQ Agent (refresh)", UPDATE_STEPS)
        self.assertIn("Article Diagnostic", UPDATE_STEPS)


if __name__ == "__main__":
    unittest.main()
