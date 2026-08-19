"""The image models the Visual Agent asks for must be ones OpenAI still serves.

DALL-E 3 was retired while `model="dall-e-3"` stayed hard-coded here. Nothing
caught it: the provider swallows its own exception and returns None, so the
pipeline finished, the run looked clean, and every article came out without
pictures. Two guards below, one offline and one live:

* the offline tests pin the call shape — the configured model reaches the API,
  quality comes from the role, and a base64 answer is decoded to bytes;
* test_configured_models_exist actually asks OpenAI. It is the only check that
  can notice a retirement, and it skips without a key.
"""

from __future__ import annotations

import base64
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import image_providers  # noqa: E402
from src.image_providers import OpenAIImageProvider, resolve_model, resolve_quality  # noqa: E402

#: A 1x1 PNG, base64 — enough to prove the decode path without a real image.
ONE_PIXEL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)


class FakeImages:
    """Records the kwargs of the last images.generate call."""

    def __init__(self, b64: str | None = ONE_PIXEL_PNG_B64) -> None:
        self.calls: list[dict] = []
        self._b64 = b64

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        datum = type("Datum", (), {"b64_json": self._b64})()
        return type("Response", (), {"data": [datum]})()


class FakeClient:
    def __init__(self, b64: str | None = ONE_PIXEL_PNG_B64) -> None:
        self.images = FakeImages(b64)


def provider_with(client: FakeClient) -> OpenAIImageProvider:
    """An OpenAIImageProvider wired to a fake client, without touching the network."""
    instance = OpenAIImageProvider.__new__(OpenAIImageProvider)
    instance.client = client
    return instance


class RoleConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        for name in ("IMAGE_MODEL_HERO", "IMAGE_MODEL_INLINE",
                     "IMAGE_QUALITY_HERO", "IMAGE_QUALITY_INLINE"):
            os.environ.pop(name, None)

    tearDown = setUp

    def test_hero_and_inline_have_separate_models(self) -> None:
        self.assertNotEqual(resolve_model("hero"), resolve_model("inline"))

    def test_no_role_asks_for_a_retired_model(self) -> None:
        for role in ("hero", "inline"):
            self.assertNotIn("dall-e", resolve_model(role))

    def test_quality_is_a_tier_the_gpt_image_models_accept(self) -> None:
        # "standard" was DALL-E 3's word for it and is rejected here.
        for role in ("hero", "inline"):
            self.assertIn(resolve_quality(role), {"low", "medium", "high", "auto"})

    def test_env_overrides_win(self) -> None:
        os.environ["IMAGE_MODEL_HERO"] = "gpt-image-1.5"
        os.environ["IMAGE_QUALITY_HERO"] = "high"
        self.assertEqual(resolve_model("hero"), "gpt-image-1.5")
        self.assertEqual(resolve_quality("hero"), "high")

    def test_an_unknown_role_falls_back_to_inline(self) -> None:
        self.assertEqual(resolve_model("sidebar"), resolve_model("inline"))


class GenerateCallTests(unittest.TestCase):
    def test_the_configured_model_and_quality_reach_the_api(self) -> None:
        client = FakeClient()
        provider_with(client).generate("a bar at dusk", "1536x1024", "hero")
        call = client.images.calls[0]
        self.assertEqual(call["model"], resolve_model("hero"))
        self.assertEqual(call["quality"], resolve_quality("hero"))
        self.assertEqual(call["size"], "1536x1024")

    def test_inline_uses_the_inline_model(self) -> None:
        client = FakeClient()
        provider_with(client).generate("a coin door", "1024x1024", "inline")
        self.assertEqual(client.images.calls[0]["model"], resolve_model("inline"))

    def test_base64_is_decoded_to_bytes(self) -> None:
        data = provider_with(FakeClient()).generate("x", "1024x1024", "inline")
        self.assertEqual(data, base64.b64decode(ONE_PIXEL_PNG_B64))
        self.assertTrue(data.startswith(b"\x89PNG"))

    def test_an_empty_payload_is_none_not_a_crash(self) -> None:
        self.assertIsNone(provider_with(FakeClient(b64=None)).generate("x", "1024x1024"))

    def test_an_api_error_is_none_not_a_crash(self) -> None:
        class Exploding:
            def generate(self, **kwargs):
                raise RuntimeError("model does not exist")

        client = FakeClient()
        client.images = Exploding()
        self.assertIsNone(provider_with(client).generate("x", "1024x1024"))


class SaveImageTests(unittest.TestCase):
    def test_bytes_land_on_disk_with_parents_created(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "images" / "hero-01.png"
            written = image_providers.save_image(b"\x89PNG payload", dest)
            self.assertEqual(written, dest)
            self.assertEqual(dest.read_bytes(), b"\x89PNG payload")


def _load_local_env() -> None:
    """Make a local .env visible to the live test, without requiring dotenv."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env = REPO_ROOT / ".env"
    if env.exists():
        load_dotenv(env)


class LiveModelAvailabilityTests(unittest.TestCase):
    """The only check that can catch a model being retired. Skips without a key."""

    @classmethod
    def setUpClass(cls) -> None:
        _load_local_env()

    def test_configured_models_exist(self) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            self.skipTest("no OPENAI_API_KEY — cannot ask OpenAI what it serves")
        try:
            import openai
        except ImportError:
            self.skipTest("openai package not installed")

        try:
            available = {m.id for m in openai.OpenAI(api_key=api_key).models.list()}
        except Exception as exc:  # offline, bad key, rate limit — not a code fault
            self.skipTest(f"could not reach the OpenAI models endpoint: {exc}")

        for role in ("hero", "inline"):
            model = resolve_model(role)
            self.assertIn(
                model,
                available,
                f"the {role} model {model!r} is not served on this account —"
                " image generation will fail silently",
            )


if __name__ == "__main__":
    unittest.main()
