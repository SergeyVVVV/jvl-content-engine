#!/usr/bin/env python3
"""JVL Content Engine — Writer Agent CLI.

Generates a first-draft article from a content brief, optional SERP research,
and optional company insight. Outputs both a markdown draft and a JSON metadata
wrapper to outputs/drafts/<slug>.{md,json}.

Arguments:
  Required:
    --topic           Article topic description

  Optional:
    --brief           Path to brief JSON from Brief Agent (strongly recommended).
                      When omitted, the agent writes from topic + knowledge base only.
    --serp-research   Path to SERP research JSON from SERP Research Agent.
                      Informs content gaps and competitor differentiation.
                      Does not add JVL facts — all product claims come from
                      the internal knowledge base.
    --company-insight Path to company insight JSON from Company Insight Agent.
                      Provides JVL-specific angles, injection points, and
                      claims/forbidden-claims constraints for this topic.
    --output-dir      Save location (default: outputs/drafts)

Usage examples:

  # Full pipeline (recommended):
  python run_writer.py \\
    --topic "how to choose a home arcade machine" \\
    --brief outputs/briefs/how-to-choose-a-home-arcade-machine.json \\
    --serp-research outputs/serp_research/how-to-choose-a-home-arcade-machine.json \\
    --company-insight outputs/company_insight/how-to-choose-a-home-arcade-machine.json

  # Brief only (no SERP, no company insight):
  python run_writer.py \\
    --topic "best bartop arcade machine for home bar" \\
    --brief outputs/briefs/bartop-arcade-machine-for-home-bar.json

  # Minimal — topic only (all optional inputs absent):
  python run_writer.py \\
    --topic "no wifi arcade machine"

Output:
  outputs/drafts/<slug>.md    — full markdown article draft
  outputs/drafts/<slug>.json  — companion metadata + QA wrapper
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing agents (they read env vars at init time)
load_dotenv()

from src.writer_agent import WriterAgent  # noqa: E402


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug (max 60 chars)."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")[:60]


def _load_json(path: str, label: str) -> dict | None:
    """Load a JSON file or return None with a warning if missing."""
    p = Path(path)
    if not p.exists():
        print(f"Warning: {label} file not found: {p} — skipping.", file=sys.stderr)
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    print(f"Loaded {label} from {p}", file=sys.stderr)
    return data


def _build_serp_context(serp_data: dict) -> str:
    """Extract the most writer-relevant fields from SERP research."""
    fields = {
        "serp_status": serp_data.get("serp_status"),
        "dominant_search_intent": serp_data.get("dominant_search_intent"),
        "content_gaps": serp_data.get("content_gaps", []),
        "differentiation_opportunities": serp_data.get(
            "differentiation_opportunities", []
        ),
        "competitor_weaknesses": serp_data.get("competitor_weaknesses", []),
        "risks_to_avoid": serp_data.get("risks_to_avoid", []),
        "notes_for_writer": serp_data.get("notes_for_writer", []),
    }
    return json.dumps(fields, indent=2, ensure_ascii=False)


def _build_insight_context(insight_data: dict) -> str:
    """Extract the most writer-relevant fields from company insight."""
    fields = {
        "relevant_jvl_angles": insight_data.get("relevant_jvl_angles", []),
        "relevant_product_facts": insight_data.get("relevant_product_facts", []),
        "natural_product_injection_points": insight_data.get(
            "natural_product_injection_points", []
        ),
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
    """Combine risks from brief and company insight into one review list."""
    risks: list[str] = list(brief.get("risks_to_avoid", []))
    if insight_data:
        for r in insight_data.get("risks_to_avoid", []):
            if r not in risks:
                risks.append(r)
    return risks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JVL Content Engine — Writer Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--topic",
        required=True,
        help="Article topic (plain text description)",
    )
    parser.add_argument(
        "--brief",
        dest="brief_path",
        default=None,
        help="Path to a brief JSON file from Brief Agent (optional but recommended)",
    )
    parser.add_argument(
        "--serp-research",
        dest="serp_research_path",
        default=None,
        help="Path to a SERP research JSON file from SERP Research Agent (optional)",
    )
    parser.add_argument(
        "--company-insight",
        dest="company_insight_path",
        default=None,
        help="Path to a company insight JSON file from Company Insight Agent (optional)",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default="outputs/drafts",
        help="Output directory (default: outputs/drafts)",
    )

    args = parser.parse_args()

    # ----------------------------------------------------------------
    # Load upstream inputs
    # ----------------------------------------------------------------

    brief: dict = {}
    if args.brief_path:
        loaded = _load_json(args.brief_path, "brief")
        if loaded is None:
            print(f"ERROR: Brief file not found: {args.brief_path}", file=sys.stderr)
            return 1
        brief = loaded

    serp_data: dict | None = None
    if args.serp_research_path:
        serp_data = _load_json(args.serp_research_path, "SERP research")

    insight_data: dict | None = None
    if args.company_insight_path:
        insight_data = _load_json(args.company_insight_path, "company insight")

    # ----------------------------------------------------------------
    # Build context strings for the agent
    # ----------------------------------------------------------------

    serp_context = _build_serp_context(serp_data) if serp_data else ""
    insight_context = _build_insight_context(insight_data) if insight_data else ""

    # ----------------------------------------------------------------
    # Run Writer Agent
    # ----------------------------------------------------------------

    print(f"\nWriter Agent starting...", file=sys.stderr)
    print(f"  Topic: {args.topic}", file=sys.stderr)
    print(f"  Brief: {'yes' if brief else 'no (degraded mode)'}", file=sys.stderr)
    print(f"  SERP research: {'yes' if serp_data else 'no'}", file=sys.stderr)
    print(f"  Company insight: {'yes' if insight_data else 'no'}\n", file=sys.stderr)

    agent = WriterAgent()
    result = agent.run(
        topic=args.topic,
        brief=brief,
        serp_context=serp_context,
        insight_context=insight_context,
    )

    # ----------------------------------------------------------------
    # Assemble markdown
    # ----------------------------------------------------------------

    draft_markdown = agent.assemble_markdown(result)

    # ----------------------------------------------------------------
    # Build companion JSON (article_draft_schema.json format)
    # ----------------------------------------------------------------

    companion: dict = {
        "topic": args.topic,
        "working_title": brief.get("working_title", result.get("h1", "")),
        "primary_keyword": brief.get("primary_keyword", ""),
        "search_intent": brief.get("search_intent", ""),
        "funnel_stage": brief.get("funnel_stage", ""),
        "product_fit": brief.get("product_fit", ""),
        "draft_markdown": draft_markdown,
        "claims_to_verify": result.get("claims_to_verify", []),
        "source_inputs_used": {
            "brief": args.brief_path,
            "serp_research": args.serp_research_path,
            "company_insight": args.company_insight_path,
        },
        "risks_to_review": _build_risks(brief, insight_data),
        "internal_links_used": result.get("internal_links_used", []),
        "todos": result.get("todos", []),
    }

    # ----------------------------------------------------------------
    # Save outputs
    # ----------------------------------------------------------------

    slug = slugify(args.topic)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{slug}.md"
    json_path = output_dir / f"{slug}.json"

    md_path.write_text(draft_markdown, encoding="utf-8")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(companion, fh, indent=2, ensure_ascii=False)

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------

    print(f"\nDraft saved →", file=sys.stderr)
    print(f"  Markdown : {md_path}", file=sys.stderr)
    print(f"  JSON     : {json_path}", file=sys.stderr)
    print(
        f"  Sections : {len(result.get('sections', []))} H2/H3 sections",
        file=sys.stderr,
    )
    print(
        f"  Claims to verify : {len(result.get('claims_to_verify', []))} items",
        file=sys.stderr,
    )
    print(
        f"  TODOs    : {len(result.get('todos', []))} items",
        file=sys.stderr,
    )
    internal_links = result.get("internal_links_used", [])
    print(
        f"  Internal links : {internal_links}",
        file=sys.stderr,
    )

    # Print paths to stdout for pipeline chaining
    print(str(md_path))
    print(str(json_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
