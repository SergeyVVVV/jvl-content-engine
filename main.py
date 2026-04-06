#!/usr/bin/env python3
"""JVL Content Engine — Brief Agent CLI.

Usage:
  python main.py --topic "how to choose a home arcade machine" \\
                 --primary-keyword "home arcade machine"

  python main.py --topic "best bartop arcade machine for home bar" \\
                 --primary-keyword "bartop arcade machine for home bar" \\
                 --funnel-stage mid

  python main.py --topic "JVL ECHO games and features" \\
                 --primary-keyword "JVL ECHO games" \\
                 --funnel-stage bottom

Outputs are saved to outputs/briefs/<slug>.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing agent (agent reads env vars at init time)
load_dotenv()

from src.agents import BriefAgent  # noqa: E402


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug (max 60 chars)."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")[:60]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JVL Content Engine — Brief Agent",
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
        help="Content goal",
    )
    parser.add_argument(
        "--funnel-stage",
        dest="funnel_stage",
        choices=["top", "mid", "bottom"],
        default="mid",
        help="Funnel stage: top / mid / bottom  (default: mid)",
    )
    parser.add_argument(
        "--audience",
        default="Mark & Linda Reynolds",
        help="Target audience (default: Mark & Linda Reynolds)",
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
        "--output-dir",
        dest="output_dir",
        default="outputs/briefs",
        help="Output directory (default: outputs/briefs)",
    )

    args = parser.parse_args()

    print(f"\nBrief Agent starting…", file=sys.stderr)
    print(f"  Topic:           {args.topic}", file=sys.stderr)
    print(f"  Primary keyword: {args.primary_keyword}", file=sys.stderr)
    print(f"  Funnel stage:    {args.funnel_stage}", file=sys.stderr)
    print(f"  Country/lang:    {args.country}/{args.language}\n", file=sys.stderr)

    agent = BriefAgent()
    brief = agent.run(
        topic=args.topic,
        primary_keyword=args.primary_keyword,
        content_goal=args.content_goal,
        funnel_stage=args.funnel_stage,
        audience=args.audience,
        country=args.country,
        language=args.language,
    )

    # Derive slug from the brief's primary_keyword (more reliable than topic)
    slug_source = brief.get("primary_keyword", args.primary_keyword)
    slug = slugify(slug_source)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{slug}.json"

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(brief, fh, indent=2, ensure_ascii=False)

    print(f"\nBrief saved → {output_path}", file=sys.stderr)
    # Print the path to stdout so it can be captured by scripts
    print(str(output_path))

    return 0


if __name__ == "__main__":
    sys.exit(main())
