#!/usr/bin/env python3
"""JVL Content Engine — Full Article Pipeline Runner.

Runs the complete pipeline for one topic:
  Brief → SERP Research → Company Insight → SEO Structure → Writer → QA → Metadata Copy

All artifacts are saved in the existing output folders.

Usage:
  python run_article.py \\
    --topic "how to choose a home arcade machine" \\
    --primary-keyword "how to choose a home arcade machine"

  python run_article.py \\
    --topic "no wifi arcade machine" \\
    --primary-keyword "no wifi arcade machine" \\
    --funnel-stage mid \\
    --skip-serp

Output folders:
  outputs/briefs/
  outputs/serp_research/
  outputs/company_insight/
  outputs/seo_structure/
  outputs/drafts/
  outputs/qa/
  outputs/metadata/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.agents import BriefAgent  # noqa: E402
from src.serp_research_agent import SerpResearchAgent  # noqa: E402
from src.company_insight_agent import CompanyInsightAgent  # noqa: E402
from src.seo_structure_agent import SeoStructureAgent  # noqa: E402
from src.writer_agent import WriterAgent  # noqa: E402
from src.qa_agent import QAAgent  # noqa: E402
from src.metadata_copy_agent import MetadataCopyAgent  # noqa: E402


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")[:60]


def _save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _step(n: int, total: int, label: str) -> None:
    print(f"\n{'─' * 60}", file=sys.stderr)
    print(f"  Step {n}/{total} — {label}", file=sys.stderr)
    print(f"{'─' * 60}", file=sys.stderr)


def _build_serp_context(serp_data: dict) -> str:
    fields = {
        "serp_status": serp_data.get("serp_status"),
        "dominant_search_intent": serp_data.get("dominant_search_intent"),
        "content_gaps": serp_data.get("content_gaps", []),
        "differentiation_opportunities": serp_data.get("differentiation_opportunities", []),
        "competitor_weaknesses": serp_data.get("competitor_weaknesses", []),
        "risks_to_avoid": serp_data.get("risks_to_avoid", []),
        "notes_for_writer": serp_data.get("notes_for_writer", []),
    }
    return json.dumps(fields, indent=2, ensure_ascii=False)


def _build_insight_context(insight_data: dict) -> str:
    fields = {
        "relevant_jvl_angles": insight_data.get("relevant_jvl_angles", []),
        "relevant_product_facts": insight_data.get("relevant_product_facts", []),
        "natural_product_injection_points": insight_data.get("natural_product_injection_points", []),
        "unique_brand_perspective": insight_data.get("unique_brand_perspective"),
        "eeat_signals": insight_data.get("eeat_signals", []),
        "persona_hooks": insight_data.get("persona_hooks", []),
        "trust_signals": insight_data.get("trust_signals", []),
        "claims_to_verify": insight_data.get("claims_to_verify", []),
        "forbidden_claims": insight_data.get("forbidden_claims", []),
        "risks_to_avoid": insight_data.get("risks_to_avoid", []),
        "notes_for_writer": insight_data.get("notes_for_writer", []),
    }
    return json.dumps(fields, indent=2, ensure_ascii=False)


def _build_risks(brief: dict, insight_data: dict | None) -> list[str]:
    risks: list[str] = list(brief.get("risks_to_avoid", []))
    if insight_data:
        for r in insight_data.get("risks_to_avoid", []):
            if r not in risks:
                risks.append(r)
    return risks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JVL Content Engine — Full Article Pipeline Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic", required=True, help="Article topic")
    parser.add_argument(
        "--primary-keyword",
        dest="primary_keyword",
        required=True,
        help="Primary SEO keyword",
    )
    parser.add_argument(
        "--content-goal",
        dest="content_goal",
        default="drive product consideration and support organic search traffic",
        help="Content goal (default: drive product consideration...)",
    )
    parser.add_argument(
        "--funnel-stage",
        dest="funnel_stage",
        choices=["top", "mid", "bottom"],
        default="mid",
        help="Funnel stage: top / mid / bottom (default: mid)",
    )
    parser.add_argument(
        "--country",
        default="US",
        help="Target country (default: US)",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Content language (default: en)",
    )
    parser.add_argument(
        "--skip-serp",
        dest="skip_serp",
        action="store_true",
        help="Skip SERP Research step",
    )
    parser.add_argument(
        "--skip-seo-structure",
        dest="skip_seo_structure",
        action="store_true",
        help="Skip SEO Structure step",
    )
    parser.add_argument(
        "--skip-qa",
        dest="skip_qa",
        action="store_true",
        help="Skip QA step",
    )
    parser.add_argument(
        "--skip-metadata",
        dest="skip_metadata",
        action="store_true",
        help="Skip Metadata Copy step",
    )
    parser.add_argument(
        "--output-root",
        dest="output_root",
        default="outputs",
        help="Root output directory (default: outputs)",
    )

    args = parser.parse_args()

    root = Path(args.output_root)
    topic = args.topic
    primary_keyword = args.primary_keyword

    # Collect generated artifact paths for the final summary
    generated: dict[str, Path] = {}

    # ================================================================
    # Step 1 — Brief (hard stop on failure)
    # ================================================================
    _step(1, 7, "Brief Agent")
    try:
        brief_agent = BriefAgent()
        brief = brief_agent.run(
            topic=topic,
            primary_keyword=primary_keyword,
            content_goal=args.content_goal,
            funnel_stage=args.funnel_stage,
            audience="Mark & Linda Reynolds",
            country=args.country,
            language=args.language,
        )
    except Exception as exc:
        print(f"\nERROR: Brief Agent failed — {exc}", file=sys.stderr)
        return 1

    # Brief uses primary_keyword slug (matches main.py behaviour)
    brief_slug = slugify(brief.get("primary_keyword", primary_keyword))
    brief_path = root / "briefs" / f"{brief_slug}.json"
    _save_json(brief, brief_path)
    generated["brief"] = brief_path
    print(f"  Saved → {brief_path}", file=sys.stderr)

    # All other agents key output files on the topic slug
    topic_slug = slugify(topic)

    # ================================================================
    # Step 2 — SERP Research (soft failure — pipeline continues)
    # ================================================================
    serp_data: dict | None = None
    serp_path: Path | None = None

    if args.skip_serp:
        print("\n[SKIP] SERP Research — --skip-serp flag set", file=sys.stderr)
    else:
        _step(2, 7, "SERP Research Agent")
        try:
            serp_agent = SerpResearchAgent()
            serp_data = serp_agent.run(
                primary_keyword=primary_keyword,
                topic=topic,
                brief=brief,
                country=args.country.lower(),
                language=args.language,
                top_n=5,
                paa_questions=brief.get("questions_to_answer", []),
            )
            serp_slug = slugify(primary_keyword)
            serp_path = root / "serp_research" / f"{serp_slug}.json"
            _save_json(serp_data, serp_path)
            generated["serp_research"] = serp_path
            print(f"  Saved → {serp_path}", file=sys.stderr)
            print(f"  serp_status: {serp_data.get('serp_status', 'unknown')}", file=sys.stderr)
        except Exception as exc:
            print(f"\nWarning: SERP Research Agent failed — {exc}", file=sys.stderr)
            print("  Continuing without SERP data.", file=sys.stderr)

    # ================================================================
    # Step 3 — Company Insight (soft failure — pipeline continues)
    # ================================================================
    insight_data: dict | None = None
    insight_path: Path | None = None

    _step(3, 7, "Company Insight Agent")

    extra_context = ""
    if serp_data:
        context_fields = {
            "serp_status": serp_data.get("serp_status"),
            "dominant_search_intent": serp_data.get("dominant_search_intent"),
            "content_gaps": serp_data.get("content_gaps", []),
            "differentiation_opportunities": serp_data.get("differentiation_opportunities", []),
            "competitor_weaknesses": serp_data.get("competitor_weaknesses", []),
            "notes_for_writer": serp_data.get("notes_for_writer", []),
        }
        extra_context = (
            "SERP research summary (from SERP Research Agent):\n"
            + json.dumps(context_fields, indent=2, ensure_ascii=False)
        )

    try:
        insight_agent = CompanyInsightAgent()
        insight_data = insight_agent.run(
            topic=topic,
            brief=brief,
            extra_context=extra_context,
        )
        insight_path = root / "company_insight" / f"{topic_slug}.json"
        _save_json(insight_data, insight_path)
        generated["company_insight"] = insight_path
        print(f"  Saved → {insight_path}", file=sys.stderr)
    except Exception as exc:
        print(f"\nWarning: Company Insight Agent failed — {exc}", file=sys.stderr)
        print("  Continuing without company insight data.", file=sys.stderr)

    # ================================================================
    # Step 4 — SEO Structure (soft failure — pipeline continues)
    # ================================================================
    seo_data: dict | None = None
    seo_path: Path | None = None

    if args.skip_seo_structure:
        print("\n[SKIP] SEO Structure — --skip-seo-structure flag set", file=sys.stderr)
    else:
        _step(4, 7, "SEO Structure Agent")
        try:
            seo_agent = SeoStructureAgent()
            seo_data = seo_agent.run(topic=topic, brief=brief)
            seo_path = root / "seo_structure" / f"{topic_slug}.json"
            _save_json(seo_data, seo_path)
            generated["seo_structure"] = seo_path
            print(f"  Saved → {seo_path}", file=sys.stderr)
            print(f"  h1: {seo_data.get('h1', '')}", file=sys.stderr)
            print(
                f"  outline sections: {len(seo_data.get('outline', []))}",
                file=sys.stderr,
            )
        except Exception as exc:
            print(f"\nWarning: SEO Structure Agent failed — {exc}", file=sys.stderr)
            print("  Continuing without SEO structure.", file=sys.stderr)

    # ================================================================
    # Step 5 — Writer (hard stop on failure)
    # ================================================================
    _step(5, 7, "Writer Agent")

    serp_context = _build_serp_context(serp_data) if serp_data else ""
    insight_context = _build_insight_context(insight_data) if insight_data else ""
    seo_structure_context = (
        json.dumps(seo_data, indent=2, ensure_ascii=False) if seo_data else ""
    )

    try:
        writer_agent = WriterAgent()
        draft_result = writer_agent.run(
            topic=topic,
            brief=brief,
            serp_context=serp_context,
            insight_context=insight_context,
            seo_structure_context=seo_structure_context,
        )
        draft_markdown = writer_agent.assemble_markdown(draft_result)
    except Exception as exc:
        print(f"\nERROR: Writer Agent failed — {exc}", file=sys.stderr)
        return 1

    companion: dict = {
        "topic": topic,
        "working_title": brief.get("working_title", draft_result.get("h1", "")),
        "primary_keyword": brief.get("primary_keyword", ""),
        "search_intent": brief.get("search_intent", ""),
        "funnel_stage": brief.get("funnel_stage", ""),
        "product_fit": brief.get("product_fit", ""),
        "draft_markdown": draft_markdown,
        "claims_to_verify": draft_result.get("claims_to_verify", []),
        "source_inputs_used": {
            "brief": str(brief_path),
            "serp_research": str(serp_path) if serp_path else None,
            "company_insight": str(insight_path) if insight_path else None,
            "seo_structure": str(seo_path) if seo_path else None,
        },
        "risks_to_review": _build_risks(brief, insight_data),
        "internal_links_used": draft_result.get("internal_links_used", []),
        "todos": draft_result.get("todos", []),
    }

    draft_md_path = root / "drafts" / f"{topic_slug}.md"
    draft_json_path = root / "drafts" / f"{topic_slug}.json"
    draft_md_path.parent.mkdir(parents=True, exist_ok=True)
    draft_md_path.write_text(draft_markdown, encoding="utf-8")
    _save_json(companion, draft_json_path)
    generated["draft_md"] = draft_md_path
    generated["draft_json"] = draft_json_path
    print(f"  Saved → {draft_md_path}", file=sys.stderr)
    print(f"         {draft_json_path}", file=sys.stderr)
    print(f"  Sections: {len(draft_result.get('sections', []))}", file=sys.stderr)

    # ================================================================
    # Step 6 — QA (hard stop on failure)
    # ================================================================
    qa_report: dict | None = None
    qa_path: Path | None = None

    if args.skip_qa:
        print("\n[SKIP] QA — --skip-qa flag set", file=sys.stderr)
    else:
        _step(6, 7, "QA Agent")

        qa_source_inputs = {
            "draft": str(draft_json_path),
            "brief": str(brief_path),
            "serp_research": str(serp_path) if serp_path else None,
            "company_insight": str(insight_path) if insight_path else None,
        }

        try:
            qa_agent = QAAgent()
            qa_report = qa_agent.run(
                topic=topic,
                draft_markdown=draft_markdown,
                draft_wrapper=companion,
                brief=brief,
                serp_data=serp_data,
                insight_data=insight_data,
                source_inputs_used=qa_source_inputs,
            )
        except Exception as exc:
            print(f"\nERROR: QA Agent failed — {exc}", file=sys.stderr)
            return 1

        qa_path = root / "qa" / f"{topic_slug}.json"
        _save_json(qa_report, qa_path)
        generated["qa"] = qa_path
        counts = qa_report.get("severity_counts", {})
        print(f"  Saved → {qa_path}", file=sys.stderr)
        print(
            f"  Status: {qa_report.get('status')} "
            f"(high={counts.get('high', 0)} "
            f"medium={counts.get('medium', 0)} "
            f"low={counts.get('low', 0)})",
            file=sys.stderr,
        )

    # ================================================================
    # Step 7 — Metadata Copy (hard stop on failure)
    # ================================================================
    metadata: dict | None = None
    metadata_path: Path | None = None

    if args.skip_metadata:
        print("\n[SKIP] Metadata Copy — --skip-metadata flag set", file=sys.stderr)
    else:
        _step(7, 7, "Metadata Copy Agent")

        meta_source_inputs = {
            "draft": str(draft_json_path),
            "brief": str(brief_path),
            "qa_report": str(qa_path) if qa_path else None,
        }

        try:
            meta_agent = MetadataCopyAgent()
            metadata = meta_agent.run(
                topic=topic,
                draft_markdown=draft_markdown,
                brief=brief,
                qa_report=qa_report,
                source_inputs_used=meta_source_inputs,
            )
        except Exception as exc:
            print(f"\nERROR: Metadata Copy Agent failed — {exc}", file=sys.stderr)
            return 1

        metadata_path = root / "metadata" / f"{topic_slug}.json"
        _save_json(metadata, metadata_path)
        generated["metadata"] = metadata_path
        print(f"  Saved → {metadata_path}", file=sys.stderr)
        print(f"  meta_title: {metadata.get('meta_title', '')}", file=sys.stderr)

    # ================================================================
    # Final Summary (stdout)
    # ================================================================
    print()
    print("=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"Topic  : {topic}")
    print(f"Keyword: {primary_keyword}")
    slug_display = metadata.get("slug", topic_slug) if metadata else topic_slug
    print(f"Slug   : {slug_display}")
    print()
    print("Artifacts:")
    labels = {
        "brief":           "Brief",
        "serp_research":   "SERP Research",
        "company_insight": "Company Insight",
        "seo_structure":   "SEO Structure",
        "draft_md":        "Draft (markdown)",
        "draft_json":      "Draft (JSON)",
        "qa":              "QA Report",
        "metadata":        "Metadata",
    }
    for key, path in generated.items():
        label = labels.get(key, key)
        print(f"  {label:<20} {path}")

    if qa_report:
        counts = qa_report.get("severity_counts", {})
        print()
        print(
            f"QA Status  : {qa_report.get('status', 'unknown')} "
            f"(high={counts.get('high', 0)} "
            f"medium={counts.get('medium', 0)} "
            f"low={counts.get('low', 0)})"
        )
        high_issues = [
            i for i in qa_report.get("issues", []) if i.get("severity") == "high"
        ]
        if high_issues:
            print("QA High Issues:")
            for issue in high_issues:
                problem = str(issue.get("problem", ""))[:80]
                print(f"  [{issue.get('category', '')}] {problem}")

    if metadata:
        print()
        print(f"H1         : {metadata.get('h1', '')}")
        print(f"Meta Title : {metadata.get('meta_title', '')}")

    todos = companion.get("todos", [])
    if todos:
        print()
        print(f"TODOs ({len(todos)}):")
        for todo in todos[:5]:
            print(f"  - {str(todo)[:80]}")
        if len(todos) > 5:
            print(f"  ... and {len(todos) - 5} more (see draft JSON)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
