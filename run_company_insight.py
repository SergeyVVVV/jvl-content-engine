#!/usr/bin/env python3
"""JVL Content Engine — Company Insight Agent CLI.

Reads JVL internal knowledge files and extracts topic-specific company insight
for downstream writing. Outputs structured JSON to outputs/company_insight/<slug>.json.

No live internet access required — all output is grounded in knowledge files.

Arguments:
  Required:
    --topic           Article topic description

  Optional:
    --brief           Path to brief JSON from Brief Agent.
                      When omitted the agent runs on topic alone. Passing
                      the brief focuses the output on the brief's angle and
                      surfaces the most relevant claims and risks.
    --serp-research   Path to SERP research JSON from SERP Research Agent.
                      When provided, content gaps and differentiation
                      opportunities are passed as prioritisation context only.
                      SERP context does not add JVL facts — all factual
                      claims still come from the internal knowledge files.
                      When omitted the agent runs on knowledge files + brief.
    --output-dir      Save location (default: outputs/company_insight)

Usage examples:
  # Full recommended pipeline for "no wifi arcade machine":
  python main.py \\
    --topic "no wifi arcade machine" \\
    --primary-keyword "no wifi arcade machine" \\
    --funnel-stage mid

  python run_serp_research.py \\
    --keyword "no wifi arcade machine" \\
    --topic "Arcade machines that work without Wi-Fi" \\
    --brief outputs/briefs/no-wifi-arcade-machine.json

  python run_company_insight.py \\
    --topic "no wifi arcade machine" \\
    --brief outputs/briefs/no-wifi-arcade-machine.json \\
    --serp-research outputs/serp_research/no-wifi-arcade-machine.json

  # Minimal usage — topic only, no chaining:
  python run_company_insight.py \\
    --topic "how to choose a home arcade machine"

Output is saved to: outputs/company_insight/<topic-slug>.json
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

from src.company_insight_agent import CompanyInsightAgent  # noqa: E402


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug (max 60 chars)."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")[:60]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JVL Content Engine — Company Insight Agent",
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
        help=(
            "Path to a SERP research JSON file from SERP Research Agent (optional). "
            "When provided, content gaps and differentiation opportunities are passed "
            "as extra context to help the insight agent focus on what matters most."
        ),
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default="outputs/company_insight",
        help="Output directory (default: outputs/company_insight)",
    )

    args = parser.parse_args()

    # Load brief if provided
    brief: dict = {}
    if args.brief_path:
        brief_file = Path(args.brief_path)
        if not brief_file.exists():
            print(f"ERROR: Brief file not found: {brief_file}", file=sys.stderr)
            return 1
        brief = json.loads(brief_file.read_text(encoding="utf-8"))
        print(f"Loaded brief from {brief_file}", file=sys.stderr)

    # Load SERP research as extra context if provided
    extra_context = ""
    if args.serp_research_path:
        serp_file = Path(args.serp_research_path)
        if not serp_file.exists():
            print(
                f"Warning: SERP research file not found: {serp_file} — skipping.",
                file=sys.stderr,
            )
        else:
            serp_data = json.loads(serp_file.read_text(encoding="utf-8"))
            # Pass only the most writer-relevant fields to avoid context bloat
            context_fields = {
                "serp_status": serp_data.get("serp_status"),
                "dominant_search_intent": serp_data.get("dominant_search_intent"),
                "content_gaps": serp_data.get("content_gaps", []),
                "differentiation_opportunities": serp_data.get(
                    "differentiation_opportunities", []
                ),
                "competitor_weaknesses": serp_data.get("competitor_weaknesses", []),
                "notes_for_writer": serp_data.get("notes_for_writer", []),
            }
            extra_context = (
                "SERP research summary (from SERP Research Agent):\n"
                + json.dumps(context_fields, indent=2, ensure_ascii=False)
            )
            print(f"Loaded SERP research context from {serp_file}", file=sys.stderr)

    print(f"\nCompany Insight Agent starting...", file=sys.stderr)
    print(f"  Topic: {args.topic}\n", file=sys.stderr)

    agent = CompanyInsightAgent()
    result = agent.run(
        topic=args.topic,
        brief=brief,
        extra_context=extra_context,
    )

    # Save output
    slug = slugify(args.topic)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{slug}.json"

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    print(f"\nCompany insight saved → {output_path}", file=sys.stderr)
    print(
        f"  relevant_jvl_angles: {len(result.get('relevant_jvl_angles', []))} items",
        file=sys.stderr,
    )
    print(
        f"  claims_to_verify: {len(result.get('claims_to_verify', []))} items",
        file=sys.stderr,
    )
    print(
        f"  forbidden_claims: {len(result.get('forbidden_claims', []))} items",
        file=sys.stderr,
    )

    # Print path to stdout so it can be captured by scripts
    print(str(output_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
