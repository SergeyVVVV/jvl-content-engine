"""The measurement now comes before everything that plans against it.

The brief ran first. It chose the angle, the audience and the section list with
no idea what ranks on the keyword or how long the ranking articles are — those
are measured two steps later. The outline then elaborated that section list,
also without the measurement: neither prompt mentioned length at all.

The Writer was handed all three and asked to reconcile them. It could not. Three
drafts kept to their outlines and still ran 4,341, 3,797 and 4,177 words against
a 2,787-word ceiling, because eight sections at the prose floor is already the
whole target and nobody upstream had been told there was one.

One thing kept SERP second: it borrowed `questions_to_answer` from the brief to
score PAA coverage. Those were guesses written before anyone looked at the
results. It reads Google's own People-also-ask box now.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import orchestrator  # noqa: E402
from src.agents import BriefAgent  # noqa: E402
from src.orchestrator import pipeline_steps  # noqa: E402
from src.serp_providers import MockSerpProvider, SerpProvider  # noqa: E402


class OrderTests(unittest.TestCase):
    def test_serp_runs_first(self) -> None:
        self.assertEqual(pipeline_steps()[0], "SERP Research")

    def test_every_planning_step_sees_it(self) -> None:
        steps = pipeline_steps()
        serp = steps.index("SERP Research")
        for planner in ("Brief", "SEO Structure", "Writer"):
            self.assertLess(serp, steps.index(planner), planner)

    def test_the_update_pipeline_already_had_it_this_way(self) -> None:
        from src.orchestrator import UPDATE_STEPS

        self.assertLess(
            UPDATE_STEPS.index("SERP Research (fresh)"),
            UPDATE_STEPS.index("Writer (update mode)"),
        )


class HandoffTests(unittest.TestCase):
    """Measured end to end, with the agents replaced."""

    def _run(self):
        seen = {}

        class FakeSerp:
            def run(inner, **kw):
                seen["serp_kwargs"] = kw
                return {
                    "comparable_length": {
                        "median_words": 2424, "sample_size": 2, "positions": [6, 8]
                    },
                    "dominant_search_intent": "informational",
                    "content_gaps": ["what it costs to run"],
                }

        class FakeBrief:
            def run(inner, **kw):
                seen["brief_kwargs"] = kw
                return {"primary_keyword": "k", "required_sections": [],
                        "questions_to_answer": []}

        class Boom:
            def run(inner, **kw):
                raise RuntimeError("stop after the brief")

        patches = [
            mock.patch.object(orchestrator, "SerpResearchAgent", FakeSerp),
            mock.patch.object(orchestrator, "BriefAgent", FakeBrief),
            mock.patch.object(orchestrator, "FactResearchAgent", Boom),
            mock.patch.object(orchestrator, "CompanyInsightAgent", Boom),
            mock.patch.object(orchestrator, "SeoStructureAgent", Boom),
            mock.patch.object(orchestrator, "WriterAgent", Boom),
        ]
        for p in patches:
            p.start()
        try:
            for event in orchestrator.run_pipeline(
                topic="T", primary_keyword="k", secondary_keywords=[],
                funnel_stage="mid", country="us", language="en",
                custom_requirements="", output_root=Path("/tmp/serp-order-test"),
                with_visuals=False,
            ):
                if event.get("label") == "failed":
                    break
        finally:
            for p in patches:
                p.stop()
        return seen

    def test_serp_no_longer_asks_for_a_brief(self) -> None:
        seen = self._run()
        self.assertIsNone(seen["serp_kwargs"].get("brief"))
        self.assertNotIn("paa_questions", seen["serp_kwargs"])

    def test_the_brief_receives_the_measurement(self) -> None:
        seen = self._run()
        self.assertIsNotNone(seen["brief_kwargs"].get("serp_data"))


class BriefBlockTests(unittest.TestCase):
    SERP = {
        "comparable_length": {"median_words": 2424, "sample_size": 2, "positions": [6, 8]},
        "dominant_search_intent": "informational",
        "content_gaps": ["running costs"],
        "competitor_weaknesses": ["no worked example"],
    }

    def test_it_states_the_length_and_the_section_count(self) -> None:
        block = BriefAgent._serp_block(self.SERP)
        self.assertIn("2060-2787 words", block)
        self.assertIn("7 H2 sections", block)

    def test_it_says_why_the_section_count_matters_to_a_brief(self) -> None:
        block = BriefAgent._serp_block(self.SERP)
        self.assertIn("a merge it did not plan", block)

    def test_it_carries_the_gaps_that_should_shape_the_angle(self) -> None:
        block = BriefAgent._serp_block(self.SERP)
        self.assertIn("running costs", block)
        self.assertIn("no worked example", block)

    def test_an_unmeasured_serp_does_not_pose_as_evidence(self) -> None:
        block = BriefAgent._serp_block({"comparable_length": None})
        self.assertIn("a default, not a measurement", block)

    def test_no_serp_means_no_block_rather_than_an_empty_one(self) -> None:
        self.assertEqual(BriefAgent._serp_block(None), "")


class OutlineBudgetTests(unittest.TestCase):
    def test_the_outline_is_told_what_it_may_spend(self) -> None:
        from src.seo_structure_agent import SeoStructureAgent

        agent = SeoStructureAgent.__new__(SeoStructureAgent)
        msg = agent._build_user_message(
            "T", {}, {"median_words": 2424, "sample_size": 2}
        )
        self.assertIn("LENGTH BUDGET", msg)
        self.assertIn("7 H2 sections", msg)

    def test_it_is_told_to_fold_rather_than_leave_it_to_the_writer(self) -> None:
        from src.seo_structure_agent import SeoStructureAgent

        agent = SeoStructureAgent.__new__(SeoStructureAgent)
        msg = agent._build_user_message("T", {}, {"median_words": 2424})
        self.assertIn("a decision rather than a repair", msg)

    def test_without_a_measurement_it_is_left_alone(self) -> None:
        from src.seo_structure_agent import SeoStructureAgent

        agent = SeoStructureAgent.__new__(SeoStructureAgent)
        self.assertNotIn("LENGTH BUDGET", agent._build_user_message("T", {}, None))


class PeopleAlsoAskTests(unittest.TestCase):
    """Real questions replace the brief's guesses."""

    def test_every_provider_answers_the_question(self) -> None:
        self.assertTrue(hasattr(SerpProvider, "people_also_ask"))
        self.assertEqual(MockSerpProvider().people_also_ask(), [])

    def test_a_live_box_is_captured(self) -> None:
        from src.serp_providers import SerpApiProvider

        payload = {
            "organic_results": [{"title": "t", "link": "u", "snippet": "s"}],
            "related_questions": [
                {"question": "How much does one earn a week?"},
                {"question": "Do they still make money?"},
                {"no_question_here": True},
            ],
        }

        class FakeResp:
            def raise_for_status(self): pass
            def json(self): return payload

        provider = SerpApiProvider.__new__(SerpApiProvider)
        provider.api_key = "x"
        provider._requests = mock.Mock(get=mock.Mock(return_value=FakeResp()))
        provider.search("k")
        self.assertEqual(
            provider.people_also_ask(),
            ["How much does one earn a week?", "Do they still make money?"],
        )

    def test_the_agent_prefers_the_live_box(self) -> None:
        source = (REPO_ROOT / "src" / "serp_research_agent.py").read_text(encoding="utf-8")
        self.assertIn("live_paa = self.provider.people_also_ask()", source)
        self.assertIn("if live_paa:", source)

    def test_an_absent_box_is_not_papered_over(self) -> None:
        """No PAA on a query is a fact about the query."""
        source = (REPO_ROOT / "src" / "serp_providers.py").read_text(encoding="utf-8")
        self.assertIn("not a failure to paper over", source)


if __name__ == "__main__":
    unittest.main()
