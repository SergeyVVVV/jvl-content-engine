#!/usr/bin/env python3
"""JVL Content Engine — SERP / Competitor Research Agent CLI.

Runs competitive SERP analysis for a keyword and topic, then saves the
structured research package to outputs/serp_research/<slug>.json.

Works in mock mode (default — no live internet required) or live mode
when SERP_PROVIDER=serpapi and SERPAPI_KEY are set.

Arguments:
  Required:
    --keyword     Primary SEO keyword to research
    --topic       Article topic description

  Optional:
    --brief       Path to brief JSON from Brief Agent.
                  When omitted the agent runs without brief context and
                  PAA questions default to none. Output is still valid.
    --country     Target country code (default: us)
    --language    Language code (default: en)
    --top-n       Number of SERP results to analyse (default: 5)
    --output-dir  Save location (default: outputs/serp_research)

Mock mode note:
  When no live SERP provider is configured (the default), output is a
  clearly-labeled illustrative competitive pattern — not confirmed rankings.
  All analysis strings are prefixed [MOCK] and serp_status is "mock".
  To use live data set SERP_PROVIDER=serpapi and SERPAPI_KEY in .env.

Usage examples:
  # Mock mode — generate brief first, then chain it in:
  python main.py \\
    --topic "how to choose a home arcade machine" \\
    --primary-keyword "how to choose a home arcade machine"

  python run_serp_research.py \\
    --keyword "how to choose a home arcade machine" \\
    --topic "How to choose a home arcade machine" \\
    --brief outputs/briefs/how-to-choose-a-home-arcade-machine.json

  # Without a brief (runs on keyword + topic alone):
  python run_serp_research.py \\
    --keyword "no wifi arcade machine" \\
    --topic "Arcade machines that work without Wi-Fi"

  # Live SERP mode (requires SERP_PROVIDER=serpapi + SERPAPI_KEY in .env):
  python run_serp_research.py \\
    --keyword "bartop arcade machine for home bar" \\
    --topic "Best bartop arcade machine for home bar" \\
    --brief outputs/briefs/bartop-arcade-machine-for-home-bar.json

Output is saved to: outputs/serp_research/<keyword-slug>.json
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

from src.serp_research_agent import SerpResearchAgent  # noqa: E402


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug (max 60 chars)."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")[:60]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JVL Content Engine — SERP / Competitor Research Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--keyword",
        required=True,
        help="Primary SEO keyword to research",
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
        help="Path to a brief JSON file from Brief Agent (optional)",
    )
    parser.add_argument(
        "--country",
        default="us",
        help="Target country code (default: us)",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Target language code (default: en)",
    )
    parser.add_argument(
        "--top-n",
        dest="top_n",
        type=int,
        default=5,
        help="Number of top SERP results to analyse (default: 5)",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default="outputs/serp_research",
        help="Output directory (default: outputs/serp_research)",
    )

    args = parser.parse_args()

    # Load brief if provided
    brief: dict = {}
    paa_questions: list[str] = []
    if args.brief_path:
        brief_file = Path(args.brief_path)
        if not brief_file.exists():
            print(f"ERROR: Brief file not found: {brief_file}", file=sys.stderr)
            return 1
        brief = json.loads(brief_file.read_text(encoding="utf-8"))
        paa_questions = brief.get("questions_to_answer", [])
        print(
            f"Loaded brief from {brief_file} "
            f"({len(paa_questions)} PAA questions)",
            file=sys.stderr,
        )

    print(f"\nSERP Research Agent starting...", file=sys.stderr)
    print(f"  Keyword:  {args.keyword}", file=sys.stderr)
    print(f"  Topic:    {args.topic}", file=sys.stderr)
    print(f"  Country:  {args.country} / Language: {args.language}", file=sys.stderr)
    print(f"  Top N:    {args.top_n}\n", file=sys.stderr)

    agent = SerpResearchAgent()
    result = agent.run(
        primary_keyword=args.keyword,
        topic=args.topic,
        brief=brief,
        country=args.country,
        language=args.language,
        top_n=args.top_n,
        paa_questions=paa_questions,
    )

    # Save output
    slug = slugify(args.keyword)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{slug}.json"

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    print(f"\nSERP research saved → {output_path}", file=sys.stderr)
    print(f"  serp_status: {result.get('serp_status', 'unknown')}", file=sys.stderr)
    print(
        f"  content_gaps: {len(result.get('content_gaps', []))} items",
        file=sys.stderr,
    )
    print(
        f"  differentiation_opportunities: "
        f"{len(result.get('differentiation_opportunities', []))} items",
        file=sys.stderr,
    )

    # Print path to stdout so it can be captured by scripts
    print(str(output_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
