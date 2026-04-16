#!/usr/bin/env python3
"""JVL Content Engine — SEO Structure Agent CLI.

Converts an article brief into a clean, SEO-sound article outline (H1, H2s,
optional H3s). Outputs structured JSON to outputs/seo_structure/<slug>.json.

No live internet access required — all output is grounded in knowledge files.

Arguments:
  Required:
    --topic           Article topic description

  Optional:
    --brief           Path to brief JSON from Brief Agent.
                      When omitted the agent runs on topic alone. Passing
                      the brief produces a sharper, intent-matched outline.
    --output-dir      Save location (default: outputs/seo_structure)

Usage examples:
  python run_seo_structure.py \\
    --topic "how to choose a home arcade machine" \\
    --brief outputs/briefs/how-to-choose-a-home-arcade-machine.json

  # Minimal usage — topic only:
  python run_seo_structure.py \\
    --topic "no wifi arcade machine"

Output is saved to: outputs/seo_structure/<topic-slug>.json
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

from src.seo_structure_agent import SeoStructureAgent  # noqa: E402


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug (max 60 chars)."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")[:60]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JVL Content Engine — SEO Structure Agent",
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
        "--output-dir",
        dest="output_dir",
        default="outputs/seo_structure",
        help="Output directory (default: outputs/seo_structure)",
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

    print(f"\nSEO Structure Agent starting...", file=sys.stderr)
    print(f"  Topic: {args.topic}\n", file=sys.stderr)

    agent = SeoStructureAgent()
    result = agent.run(
        topic=args.topic,
        brief=brief,
    )

    # Save output
    slug = slugify(args.topic)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{slug}.json"

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    print(f"\nSEO structure saved → {output_path}", file=sys.stderr)
    print(f"  h1: {result.get('h1', '')}", file=sys.stderr)
    print(f"  slug: {result.get('slug', '')}", file=sys.stderr)
    print(
        f"  outline sections: {len(result.get('outline', []))}",
        file=sys.stderr,
    )
    print(
        f"  internal_link_targets: {len(result.get('internal_link_targets', []))} items",
        file=sys.stderr,
    )

    # Print path to stdout so it can be captured by scripts
    print(str(output_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
