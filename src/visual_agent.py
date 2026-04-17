"""Visual Agent — JVL Content Engine.

Pipeline position:
  Writer Agent → Visual Agent → QA Agent

Purpose:
  Given a draft article, produce exactly 3 image specifications (1 hero + 2 inline),
  generate them via DALL-E 3 (or mock placeholders), download locally, and inject
  image markdown into the draft at fixed slot positions.

Auth modes for the LLM specification phase (tried in order):
  1. Direct Anthropic SDK  — when ANTHROPIC_API_KEY is set in env / .env
  2. Claude Agent SDK      — when running inside a Claude Code session

Image generation:
  DALL-E 3 via OpenAI API when OPENAI_API_KEY is set; mock mode otherwise.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import jsonschema

from src.image_providers import download_image, get_image_provider


# Knowledge files loaded into the Visual Agent's LLM context.
_KNOWLEDGE_FILES: list[tuple[str, str]] = [
    ("visual_style_rules.md", "VISUAL STYLE RULES — follow for every image decision"),
    ("product_echo_home.md",  "PRODUCT FACTS — only these facts about JVL ECHO"),
    ("brand_voice.md",        "BRAND VOICE AND TONE"),
]

# DALL-E 3 size per asset type.
_DALLE_SIZE: dict[str, str] = {
    "hero":      "1792x1024",
    "inline":    "1024x1024",
    "detail":    "1024x1024",
    "lifestyle": "1024x1024",
    "diagram":   "1024x1024",
}


class VisualAgent:
    """Specifies, generates, and injects 3 images into a draft article.

    Phase 1 — LLM (Claude): produces 3 asset specs (hero + 2 inline).
    Phase 2 — DALL-E 3: generates and downloads each image.
    Phase 3 — Python: inserts image markdown into the draft at fixed positions.
    """

    def __init__(self) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
        self.repo_root = Path(__file__).parent.parent

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _load_file(self, path: str) -> str:
        return (self.repo_root / path).read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Phase 1: LLM specification
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        prompt = self._load_file("prompts/visual_agent.md")
        schema = self._load_file("schemas/visual_schema.json")

        knowledge_sections: list[str] = []
        for filename, label in _KNOWLEDGE_FILES:
            filepath = f"knowledge/{filename}"
            try:
                content = self._load_file(filepath)
                knowledge_sections.append(f"## {label}\n\n{content}")
            except FileNotFoundError:
                print(f"Warning: {filepath} not found, skipping.", file=sys.stderr)

        knowledge_block = "\n\n---\n\n".join(knowledge_sections)

        return f"""{prompt}

---

# KNOWLEDGE BASE — YOUR ONLY SOURCE OF TRUTH

All visual decisions must be grounded in the sections below.
Do not reference product features not confirmed here.

{knowledge_block}

---

# OUTPUT SCHEMA

Your response must be a single valid JSON object matching this schema exactly:

{schema}

CRITICAL OUTPUT RULES:
- Output ONLY the raw JSON object. No markdown. No code fences. No preamble.
- The JSON must be parseable by json.loads() with no pre-processing.
- assets array must contain EXACTLY 3 items: one "hero" and two "inline".
- generation_prompt must be a detailed, specific DALL-E 3 prompt that matches
  the visual style rules: warm lighting, real adult home setting, no gamer clichés.
- alt_text must describe the image for accessibility — no keyword stuffing.
- Do not invent product features not confirmed by knowledge files."""

    def _build_user_message(self, topic: str, brief: dict, draft_markdown: str) -> str:
        brief_block = json.dumps(brief, indent=2, ensure_ascii=False) if brief else "{}"
        # Pass only first 2000 chars of draft to avoid context bloat — headings + intro
        draft_excerpt = draft_markdown[:2000].strip() if draft_markdown else "(no draft)"
        return (
            f"Produce the 3 visual asset specifications for this article.\n\n"
            f"Topic: {topic}\n\n"
            f"# ARTICLE BRIEF\n\n{brief_block}\n\n"
            f"# DRAFT ARTICLE (excerpt — headings and intro)\n\n{draft_excerpt}\n\n"
            "Return exactly 3 assets: one hero (cover) and two inline (body).\n"
            "Return only a valid JSON object. No markdown, no commentary."
        )

    # ------------------------------------------------------------------
    # JSON extraction and validation
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(raw: str) -> dict:
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```\s*$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
        return json.loads(raw)

    def _validate(self, result: dict) -> None:
        schema = json.loads(self._load_file("schemas/visual_schema.json"))
        try:
            jsonschema.validate(instance=result, schema=schema)
            print("Schema validation: PASSED", file=sys.stderr)
        except jsonschema.ValidationError as exc:
            print(f"Schema validation WARNING: {exc.message}", file=sys.stderr)
            print("Output was saved anyway — review the warnings above.", file=sys.stderr)

    # ------------------------------------------------------------------
    # Auth mode 1: direct Anthropic SDK
    # ------------------------------------------------------------------

    def _run_via_sdk(self, system_prompt: str, user_message: str) -> dict:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = next(
            (block.text for block in response.content if block.type == "text"), ""
        )
        if not raw:
            raise ValueError("Model returned no text content.")
        return self._extract_json(raw)

    # ------------------------------------------------------------------
    # Auth mode 2: Claude Agent SDK (Claude Code environment)
    # ------------------------------------------------------------------

    def _run_via_agent_sdk(self, system_prompt: str, user_message: str) -> dict:
        import anyio
        from claude_code_sdk import (
            AssistantMessage,
            ClaudeCodeOptions,
            ResultMessage,
            TextBlock,
            query,
        )

        result_text: list[str] = []
        assistant_text: list[str] = []

        async def _run() -> None:
            try:
                async for message in query(
                    prompt=user_message,
                    options=ClaudeCodeOptions(
                        system_prompt=system_prompt,
                        allowed_tools=[],
                        model=self.model,
                        max_turns=1,
                    ),
                ):
                    if isinstance(message, ResultMessage):
                        result_text.append(message.result or "")
                    elif isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                assistant_text.append(block.text)
            except Exception as exc:
                if result_text or assistant_text:
                    print(f"SDK warning (non-fatal, have content): {exc}", file=sys.stderr)
                else:
                    raise

        anyio.run(_run)
        raw = "\n".join(result_text).strip() or "\n".join(assistant_text).strip()
        if not raw:
            raise ValueError("Agent SDK returned no content.")
        return self._extract_json(raw)

    # ------------------------------------------------------------------
    # Phase 2: Image acquisition
    # ------------------------------------------------------------------

    def _acquire_images(self, assets: list[dict], output_dir: Path) -> list[dict]:
        """Generate and download images for each asset spec.

        Modifies each asset in-place to add 'local_path' and 'source'.
        Returns the modified list.
        """
        provider = get_image_provider()
        output_dir.mkdir(parents=True, exist_ok=True)

        inline_count = 0
        for i, asset in enumerate(assets):
            asset_type = asset.get("type", "inline")
            if asset_type == "hero":
                filename = "hero-01.png"
            else:
                inline_count += 1
                filename = f"inline-{inline_count:02d}.png"

            size = _DALLE_SIZE.get(asset_type, "1024x1024")
            dest = output_dir / filename

            url = provider.generate(asset.get("generation_prompt", ""), size)
            if url:
                try:
                    local_path = download_image(url, dest)
                    asset["local_path"] = str(local_path)
                    asset["source"] = "dalle3"
                    print(f"  Downloaded → {local_path}", file=sys.stderr)
                except Exception as exc:
                    print(f"  Download failed for {filename}: {exc}", file=sys.stderr)
                    asset["local_path"] = None
                    asset["source"] = "dalle3_download_failed"
            else:
                asset["local_path"] = None
                asset["source"] = "mock"

        return assets

    # ------------------------------------------------------------------
    # Phase 3: Markdown injection
    # ------------------------------------------------------------------

    @staticmethod
    def _insert_images(draft_markdown: str, assets: list[dict]) -> str:
        """Insert image markdown blocks into the draft at fixed positions.

        Slot rules:
          hero   → before the first ## heading
          inline → after the 2nd ## heading (inline #1) and 4th ## heading (inline #2)
                   falls back to last ## heading if article has fewer sections
        """
        lines = draft_markdown.split("\n")

        # Collect positions of all ## (H2) headings
        h2_positions: list[int] = [
            i for i, line in enumerate(lines)
            if re.match(r"^## ", line)
        ]

        def _image_block(asset: dict) -> list[str]:
            local_path = asset.get("local_path")
            alt = asset.get("alt_text", "")
            caption = asset.get("caption", "")
            desc = asset.get("description", asset.get("type", "image"))

            if local_path:
                block = [f"![{alt}]({local_path})"]
                if caption:
                    block.append(f"*{caption}*")
                block.append("")
            else:
                block = [
                    f"<!-- IMAGE PLACEHOLDER: {asset.get('type', 'inline')} — {desc} -->",
                    "",
                ]
            return block

        # Separate assets by type
        hero_assets = [a for a in assets if a.get("type") == "hero"]
        inline_assets = [a for a in assets if a.get("type") != "hero"]

        # Work backwards so earlier insertions don't shift later indices
        insertions: list[tuple[int, list[str]]] = []  # (line_index, lines_to_insert)

        # Hero: insert BEFORE the first ## heading
        if hero_assets and h2_positions:
            first_h2 = h2_positions[0]
            insertions.append((first_h2, _image_block(hero_assets[0])))

        # Inline 1: insert AFTER the 2nd ## heading line
        target_indices = [1, 3]  # 0-indexed into h2_positions (2nd and 4th headings)
        for j, asset in enumerate(inline_assets[:2]):
            target = target_indices[j]
            if target < len(h2_positions):
                pos = h2_positions[target] + 1  # line after the heading
            elif h2_positions:
                pos = h2_positions[-1] + 1  # fallback: after last heading
            else:
                pos = len(lines)
            insertions.append((pos, _image_block(asset)))

        # Apply insertions in reverse order (largest index first)
        for insert_pos, block_lines in sorted(insertions, key=lambda x: x[0], reverse=True):
            lines = lines[:insert_pos] + block_lines + lines[insert_pos:]

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(
        self,
        topic: str,
        brief: dict | None = None,
        draft_markdown: str = "",
        output_dir: Path | None = None,
    ) -> dict:
        """Run the Visual Agent: specify → generate → inject.

        Args:
            topic:          Article topic.
            brief:          Optional brief dict from Brief Agent.
            draft_markdown: Full draft article markdown.
            output_dir:     Directory for downloaded images. Defaults to
                            repo_root/outputs/images/<topic-slug>.

        Returns:
            Dict with keys:
              assets           — list of 3 asset dicts (with local_path + source)
              enriched_markdown — draft markdown with images inserted
              todos            — any follow-up items from the LLM
        """
        print("Visual Agent: loading knowledge files...", file=sys.stderr)

        if output_dir is None:
            slug = re.sub(r"[^a-z0-9-]", "-", topic.lower())[:60].strip("-")
            output_dir = self.repo_root / "outputs" / "images" / slug

        # Phase 1: LLM specification
        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(topic, brief or {}, draft_markdown)

        if self.api_key:
            print(f"Auth: Anthropic SDK (model: {self.model})", file=sys.stderr)
            specs = self._run_via_sdk(system_prompt, user_message)
        else:
            print(f"Auth: Claude Agent SDK (model: {self.model})", file=sys.stderr)
            specs = self._run_via_agent_sdk(system_prompt, user_message)

        self._validate(specs)

        # Phase 2: Image acquisition
        print("Visual Agent: acquiring images...", file=sys.stderr)
        assets = self._acquire_images(specs.get("assets", []), output_dir)

        # Phase 3: Markdown injection
        print("Visual Agent: injecting images into draft...", file=sys.stderr)
        enriched_markdown = self._insert_images(draft_markdown, assets)

        return {
            "assets": assets,
            "enriched_markdown": enriched_markdown,
            "todos": specs.get("todos", []),
        }
