"""Each provider must read its own key.

A bulk rename of OPENAI_API_KEY to ANTHROPIC_API_KEY during the move back to
Anthropic hit image_providers too, so DalleProvider handed an Anthropic key to
openai.OpenAI() and every DALL-E call 401'd. It was invisible to a grep for
"OPENAI" because the string survived in the error messages while the lookup
moved. These tests check the lookups, not the prose.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SRC = REPO_ROOT / "src"


def env_lookups(path: Path) -> set[str]:
    """Every literal key passed to os.environ.get / os.environ[...] in a file."""
    found: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "environ"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                found.add(node.args[0].value)
        elif isinstance(node, ast.Subscript):
            value = node.value
            if (
                isinstance(value, ast.Attribute)
                and value.attr == "environ"
                and isinstance(node.slice, ast.Constant)
            ):
                found.add(node.slice.value)
    return found


class ProviderKeyTests(unittest.TestCase):
    def test_image_generation_reads_the_openai_key(self) -> None:
        keys = env_lookups(SRC / "image_providers.py")
        self.assertIn("OPENAI_API_KEY", keys)

    def test_image_generation_never_reads_the_text_provider_key(self) -> None:
        # DALL-E is OpenAI's. An Anthropic key here authenticates nothing and
        # makes the factory pick a provider that cannot work.
        keys = env_lookups(SRC / "image_providers.py")
        self.assertNotIn("ANTHROPIC_API_KEY", keys)

    def test_text_generation_reads_the_anthropic_key(self) -> None:
        keys = env_lookups(SRC / "llm_client.py")
        self.assertIn("ANTHROPIC_API_KEY", keys)
        self.assertNotIn("OPENAI_API_KEY", keys)

    def test_agents_gate_on_the_anthropic_key(self) -> None:
        offenders = []
        for path in sorted(SRC.glob("*_agent.py")) + [SRC / "agents.py"]:
            if "OPENAI_API_KEY" in env_lookups(path):
                offenders.append(path.name)
        self.assertEqual(offenders, [], "these agents still gate on the OpenAI key")
