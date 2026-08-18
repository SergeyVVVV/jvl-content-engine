"""Guard the import path that hot-reloading has broken twice.

Streamlit purges the app's own modules when it redeploys after a push, and a
half-purged sys.modules is what took the app down with KeyError:
'serp_providers' and then with

    AttributeError: 'NoneType' object has no attribute '__dict__'

raised inside dataclasses. The second one needs string annotations to happen:
@dataclass resolves them through sys.modules[cls.__module__].__dict__ while
creating the class, and that entry is None mid-purge. Real annotation objects
are never looked up that way.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SRC = REPO_ROOT / "src"


def _defines_dataclass(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for dec in node.decorator_list:
                name = dec.func if isinstance(dec, ast.Call) else dec
                if getattr(name, "id", None) == "dataclass":
                    return True
                if getattr(name, "attr", None) == "dataclass":
                    return True
    return False


def _has_future_annotations(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in ast.walk(tree)
    )


class DataclassAnnotationTests(unittest.TestCase):
    def test_no_module_combines_dataclasses_with_string_annotations(self) -> None:
        offenders = []
        for path in sorted(SRC.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if _defines_dataclass(tree) and _has_future_annotations(tree):
                offenders.append(path.name)
        self.assertEqual(
            offenders, [],
            "these modules would crash on a Streamlit hot reload — drop the "
            "future import or stop using @dataclass there",
        )

    def test_the_publish_dataclasses_still_construct(self) -> None:
        from src.studio_client import PublishResult
        from src.studio_export import StudioPayload

        self.assertEqual(PublishResult(ok=True, status=201).tags_unknown, [])
        self.assertEqual(StudioPayload(payload={"a": 1}).warnings, [])
