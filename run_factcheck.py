#!/usr/bin/env python3
"""JVL Content Engine — Factcheck Agent CLI.

Verifies every factual claim in a draft article against JVL knowledge files.
Outputs a structured JSON report to outputs/factcheck/<slug>.json.

No live internet access required — all verification is grounded in knowledge files.

Required:
  --topic           Article topic
  --draft           Path to draft .md OR Writer wrapper .json

Optional:
  --output-dir      Save location (default: outputs/factcheck)

Examples:

  python run_factcheck.py \\
    --topic "how to choose a home arcade machine" \\
    --draft outputs/drafts/how-to-choose-a-home-arcade-machine.json

  python run_factcheck.py \\
    --topic "no wifi arcade machine" \\
    --draft outputs/drafts/no-wifi-arcade-machine.md

Output:
  outputs/factcheck/<slug>.json   — claim classification report
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.factcheck_agent import FactcheckAgent  # noqa: E402


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")[:60]


def _load_draft(path: str) -> str:
    """Return draft markdown for either a .md or .json input."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Draft file not found: {p}")

    if p.suffix.lower() == ".json":
        wrapper = json.loads(p.read_text(encoding="utf-8"))
        md = wrapper.get("draft_markdown", "")
        if not md:
            raise ValueError(
                f"Draft JSON {p} has no 'draft_markdown' field — "
                "pass the .md file instead."
            )
        return md

    return p.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JVL Content Engine — Factcheck Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--draft", required=True, dest="draft_path")
    parser.add_argument("--output-dir", dest="output_dir", default="outputs/factcheck")

    args = parser.parse_args()

    # ----------------------------------------------------------------
    # Load draft (required)
    # ----------------------------------------------------------------
    try:
        draft_markdown = _load_draft(args.draft_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"\nFactcheck Agent starting...", file=sys.stderr)
    print(f"  Topic: {args.topic}", file=sys.stderr)
    print(f"  Draft: {args.draft_path}\n", file=sys.stderr)

    # ----------------------------------------------------------------
    # Run Factcheck Agent
    # ----------------------------------------------------------------
    agent = FactcheckAgent()
    result = agent.run(
        topic=args.topic,
        draft_markdown=draft_markdown,
    )

    # ----------------------------------------------------------------
    # Save
    # ----------------------------------------------------------------
    slug = slugify(args.topic)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{slug}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    print(f"\nFactcheck report saved → {out_path}", file=sys.stderr)
    print(f"  grounded    : {len(result.get('grounded_claims', []))}", file=sys.stderr)
    print(f"  unsupported : {len(result.get('unsupported_claims', []))}", file=sys.stderr)
    print(f"  forbidden   : {len(result.get('forbidden_claims', []))}", file=sys.stderr)
    print(f"  publish_blocking: {result.get('publish_blocking', False)}", file=sys.stderr)

    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
