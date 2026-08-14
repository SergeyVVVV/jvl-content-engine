"""The history store must degrade, not take the app down with it.

`load_history()` runs from app.py's module body, so anything it raises is a
blank page. This is not hypothetical: the Supabase project behind it stopped
resolving and the whole UI went down with a ConnectionError.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import requests  # noqa: E402

import src.history_store as store  # noqa: E402
from src.history_store import HistoryUnavailable  # noqa: E402

FAKE_CFG = ("https://project.supabase.co", "key")


class _Boom:
    """Stand-in for requests.<verb> that always fails the same way."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise self.exc


class RemoteFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = (store._config, store.requests, store._last_error)
        store._config = lambda: FAKE_CFG
        store._last_error = None

    def tearDown(self) -> None:
        store._config, store.requests, store._last_error = self._saved

    def fail_with(self, exc: Exception) -> _Boom:
        boom = _Boom(exc)
        store.requests = type("R", (), {
            "get": staticmethod(boom), "post": staticmethod(boom),
            "delete": staticmethod(boom),
            "ConnectionError": requests.ConnectionError,
            "Timeout": requests.Timeout, "HTTPError": requests.HTTPError,
        })
        return boom

    def test_load_returns_empty_instead_of_raising(self) -> None:
        self.fail_with(requests.ConnectionError("dns"))
        self.assertEqual(store.load_history(), [])

    def test_load_explains_an_unreachable_project(self) -> None:
        self.fail_with(requests.ConnectionError("dns"))
        store.load_history()
        self.assertIn("cannot reach the Supabase project", store.history_last_error())

    def test_load_explains_a_timeout(self) -> None:
        self.fail_with(requests.Timeout())
        store.load_history()
        self.assertIn("did not answer", store.history_last_error())

    def test_save_raises_a_typed_error_the_caller_can_catch(self) -> None:
        self.fail_with(requests.ConnectionError("dns"))
        with self.assertRaises(HistoryUnavailable):
            store.save_to_history({"id": "x"})

    def test_delete_raises_rather_than_pretending_it_worked(self) -> None:
        self.fail_with(requests.ConnectionError("dns"))
        with self.assertRaises(HistoryUnavailable):
            store.delete_from_history("x")

    def test_error_clears_after_a_good_load(self) -> None:
        self.fail_with(requests.ConnectionError("dns"))
        store.load_history()
        self.assertIsNotNone(store.history_last_error())

        class _Ok:
            @staticmethod
            def get(*a, **k):
                class R:
                    @staticmethod
                    def raise_for_status() -> None: ...
                    @staticmethod
                    def json() -> list[dict]: return [{"id": "1"}]
                return R()
        store.requests = _Ok
        self.assertEqual(store.load_history(), [{"id": "1"}])
        self.assertIsNone(store.history_last_error())


class NotConfiguredTests(unittest.TestCase):
    """Without Supabase secrets the local JSON fallback is used, and a missing
    file is an empty history, not an error."""

    def setUp(self) -> None:
        self._cfg = store._config
        store._config = lambda: None
        self._path = store._LOCAL_PATH
        store._LOCAL_PATH = REPO_ROOT / "outputs" / "does-not-exist.json"

    def tearDown(self) -> None:
        store._config = self._cfg
        store._LOCAL_PATH = self._path

    def test_missing_local_file_is_empty_history(self) -> None:
        self.assertEqual(store.load_history(), [])
        self.assertIsNone(store.history_last_error())


class PipelineSurvivalTests(unittest.TestCase):
    """A dead history store must not throw away a finished article."""

    def test_orchestrator_catches_history_unavailable(self) -> None:
        source = (REPO_ROOT / "src" / "orchestrator.py").read_text()
        self.assertIn("except HistoryUnavailable", source)
        self.assertEqual(
            source.count("except HistoryUnavailable"),
            source.count("save_to_history(history_entry)"),
            "every save_to_history call must be guarded",
        )

    def test_app_surfaces_both_failure_modes(self) -> None:
        app = (REPO_ROOT / "app.py").read_text()
        self.assertIn("history_last_error()", app)   # sidebar
        self.assertIn('res.get("history_error")', app)  # after a run


if __name__ == "__main__":
    unittest.main()
