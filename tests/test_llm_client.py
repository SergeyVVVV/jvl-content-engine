"""Configuration lookup for the LLM client.

Every agent goes through `llm_client.chat()`, so where it reads the API key
from decides whether the whole engine works on Streamlit Cloud. Reading only
`os.environ` would rely on the platform exporting secrets as environment
variables — the Streamlit library does not, so this checks secrets first.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import src.llm_client as llm  # noqa: E402


class _Secrets:
    def __init__(self, values: dict) -> None:
        self.values = values

    def get(self, name):
        return self.values.get(name)


class _FakeStreamlit:
    def __init__(self, values: dict) -> None:
        self.secrets = _Secrets(values)


class SettingLookupTests(unittest.TestCase):
    KEYS = ("OPENAI_API_KEY", "OPENAI_MODEL_HEAVY", "OPENAI_MODEL_LIGHT")

    def setUp(self) -> None:
        self._env = {k: os.environ.pop(k, None) for k in self.KEYS}
        self._streamlit = sys.modules.get("streamlit")

    def tearDown(self) -> None:
        for key, value in self._env.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
        if self._streamlit is None:
            sys.modules.pop("streamlit", None)
        else:
            sys.modules["streamlit"] = self._streamlit

    def use_secrets(self, values: dict) -> None:
        sys.modules["streamlit"] = _FakeStreamlit(values)

    def test_secrets_are_read(self) -> None:
        self.use_secrets({"OPENAI_API_KEY": "from-secrets"})
        self.assertEqual(llm.setting("OPENAI_API_KEY"), "from-secrets")

    def test_environment_is_the_fallback(self) -> None:
        self.use_secrets({})
        os.environ["OPENAI_API_KEY"] = "from-env"
        self.assertEqual(llm.setting("OPENAI_API_KEY"), "from-env")

    def test_secrets_win_over_environment(self) -> None:
        self.use_secrets({"OPENAI_API_KEY": "from-secrets"})
        os.environ["OPENAI_API_KEY"] = "from-env"
        self.assertEqual(llm.setting("OPENAI_API_KEY"), "from-secrets")

    def test_missing_streamlit_is_not_an_error(self) -> None:
        sys.modules.pop("streamlit", None)
        os.environ["OPENAI_API_KEY"] = "from-env"
        self.assertEqual(llm.setting("OPENAI_API_KEY"), "from-env")

    def test_a_broken_secrets_object_falls_back_rather_than_raising(self) -> None:
        class _Exploding:
            @property
            def secrets(self):
                raise RuntimeError("no secrets file")

        sys.modules["streamlit"] = _Exploding()
        os.environ["OPENAI_API_KEY"] = "from-env"
        self.assertEqual(llm.setting("OPENAI_API_KEY"), "from-env")

    def test_blank_secret_does_not_mask_the_environment(self) -> None:
        self.use_secrets({"OPENAI_API_KEY": ""})
        os.environ["OPENAI_API_KEY"] = "from-env"
        self.assertEqual(llm.setting("OPENAI_API_KEY"), "from-env")

    def test_default_when_nothing_is_set(self) -> None:
        self.use_secrets({})
        self.assertEqual(llm.setting("OPENAI_API_KEY", "fallback"), "fallback")
        self.assertIsNone(llm.setting("OPENAI_API_KEY"))


class ModelTierTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = {
            k: os.environ.pop(k, None)
            for k in ("OPENAI_MODEL_HEAVY", "OPENAI_MODEL_STANDARD", "OPENAI_MODEL_LIGHT")
        }
        self._streamlit = sys.modules.pop("streamlit", None)

    def tearDown(self) -> None:
        for key, value in self._env.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
        if self._streamlit is not None:
            sys.modules["streamlit"] = self._streamlit

    def test_defaults(self) -> None:
        self.assertEqual(llm.resolve_model("heavy"), "gpt-5")
        self.assertEqual(llm.resolve_model("standard"), "gpt-5-mini")
        self.assertEqual(llm.resolve_model("light"), "gpt-5-nano")

    def test_unknown_tier_falls_back_to_standard(self) -> None:
        self.assertEqual(llm.resolve_model("nonsense"), llm.resolve_model("standard"))

    def test_tier_can_be_overridden(self) -> None:
        os.environ["OPENAI_MODEL_HEAVY"] = "gpt-6-imaginary"
        self.assertEqual(llm.resolve_model("heavy"), "gpt-6-imaginary")


class MissingKeyTests(unittest.TestCase):
    def test_the_error_says_where_to_put_the_key(self) -> None:
        saved_env = os.environ.pop("OPENAI_API_KEY", None)
        saved_st = sys.modules.pop("streamlit", None)
        try:
            with self.assertRaises(EnvironmentError) as ctx:
                llm.chat("system", "user")
            message = str(ctx.exception)
            self.assertIn("Streamlit secrets", message)
            self.assertIn(".env", message)
        finally:
            if saved_env is not None:
                os.environ["OPENAI_API_KEY"] = saved_env
            if saved_st is not None:
                sys.modules["streamlit"] = saved_st


if __name__ == "__main__":
    unittest.main()
