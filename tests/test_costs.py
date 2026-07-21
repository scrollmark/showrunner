"""Tests for cost estimation + usage aggregation (showrunner.costs)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from showrunner.config import Config
from showrunner.costs import (
    CostEstimate,
    collect_usage,
    estimate_pipeline_cost,
    llm_usd,
    tts_usd,
    usage_cost_usd,
    video_usd,
)
from showrunner.pipeline import Pipeline


# ── Pipeline.estimate (acceptance: non-zero for both built-in formats) ───


def test_estimate_faceless_explainer_nonzero_with_defaults():
    pipeline = Pipeline(format_name="faceless-explainer", config=Config())
    estimate = pipeline.estimate("any topic")

    assert isinstance(estimate, CostEstimate)
    assert estimate.format == "faceless-explainer"
    assert estimate.total_usd > 0
    stages = {s.stage for s in estimate.stages}
    # Code-driven format: LLM plan + per-scene codegen, no video gen.
    assert {"plan", "scene_code", "narration", "render"} <= stages
    assert "video_gen" not in stages
    # LLM stages carry the cost (kokoro TTS is local/free by default).
    scene_code = next(s for s in estimate.stages if s.stage == "scene_code")
    assert scene_code.usd > 0
    assert scene_code.unit == "llm_tokens"


def test_estimate_ai_video_nonzero_with_defaults():
    pipeline = Pipeline(format_name="ai-video", config=Config())
    estimate = pipeline.estimate("any topic", num_scenes=5, avg_scene_seconds=8)

    assert estimate.total_usd > 0
    assert estimate.num_scenes == 5
    assert estimate.estimated_duration_seconds == 40
    stages = {s.stage: s for s in estimate.stages}
    # Video generation is present and is the dominant cost.
    assert "video_gen" in stages
    assert stages["video_gen"].quantity == 40
    assert stages["video_gen"].usd > 0
    assert stages["video_gen"].usd == max(s.usd for s in estimate.stages)
    # ai-video has no per-scene TSX codegen stage.
    assert "scene_code" not in stages


def test_estimate_scales_with_scene_count():
    pipeline = Pipeline(format_name="faceless-explainer", config=Config())
    small = pipeline.estimate("t", num_scenes=3)
    large = pipeline.estimate("t", num_scenes=9)
    assert large.total_usd > small.total_usd


def test_estimate_to_dict_roundtrip_shape():
    estimate = Pipeline(format_name="faceless-explainer", config=Config()).estimate("t")
    d = estimate.to_dict()
    assert d["total_usd"] == estimate.total_usd
    assert len(d["stages"]) == len(estimate.stages)
    assert {"stage", "provider", "unit", "quantity", "usd", "note"} == set(
        d["stages"][0]
    )


def test_estimate_provider_hook_overrides_table():
    """A live provider instance's estimate_cost() beats the static table."""
    llm = MagicMock()
    llm.estimate_cost.return_value = 42.0
    estimate = estimate_pipeline_cost(
        format_name="faceless-explainer",
        llm_name="anthropic",
        tts_name="kokoro",
        render_name="remotion",
        num_scenes=2,
        providers={"llm": llm},
    )
    plan_stage = next(s for s in estimate.stages if s.stage == "plan")
    assert plan_stage.usd == 42.0


# ── Pricing helpers ──────────────────────────────────────────────────────


def test_llm_usd_table_math():
    # anthropic: $3/M input + $15/M output
    assert llm_usd("anthropic", input_tokens=1_000_000, output_tokens=0) == 3.0
    assert llm_usd("anthropic", input_tokens=0, output_tokens=1_000_000) == 15.0


def test_tts_usd_kokoro_is_free():
    assert tts_usd("kokoro", characters=100_000) == 0.0
    assert tts_usd("elevenlabs", characters=1_000) > 0


def test_video_usd_unknown_provider_uses_default():
    assert video_usd("some-new-provider", seconds=10) > 0


def test_hook_errors_fall_back_to_table():
    llm = MagicMock()
    llm.estimate_cost.side_effect = RuntimeError("boom")
    assert llm_usd("anthropic", input_tokens=1_000_000, output_tokens=0, provider=llm) == 3.0


# ── Usage aggregation ────────────────────────────────────────────────────


def test_collect_usage_skips_providers_without_real_dicts():
    good = MagicMock()
    good.get_usage.return_value = {"input_tokens": 10, "output_tokens": 5}
    bare_mock = MagicMock()  # get_usage() returns a MagicMock, not a dict
    no_hook = object()
    raising = MagicMock()
    raising.get_usage.side_effect = RuntimeError("boom")

    usage = collect_usage(
        {"llm": good, "tts": bare_mock, "render": no_hook, "video": raising}
    )
    assert usage == {"llm": {"input_tokens": 10, "output_tokens": 5}}


def test_collect_usage_handles_none():
    assert collect_usage(None) == {}


def test_usage_cost_usd_prices_actuals():
    usage = {
        "llm": {"input_tokens": 1_000_000, "output_tokens": 0},
        "tts": {"characters": 2_000},
        "video": {"video_seconds": 10.0},
    }
    cost = usage_cost_usd(usage, llm_name="anthropic", tts_name="elevenlabs", video_name="gemini")
    # 3.00 (llm) + 0.30 (tts) + 4.00 (video)
    assert cost == pytest.approx(7.30)


def test_usage_cost_usd_zero_usage_is_zero():
    assert usage_cost_usd({}, llm_name="anthropic", tts_name="kokoro") == 0.0


def test_provider_abc_defaults_are_null():
    """The optional ABC hooks default to None/zeros so existing
    providers are unaffected."""
    from showrunner.providers.llm.base import LLMProvider
    from showrunner.providers.render.base import RenderProvider
    from showrunner.providers.tts.base import TTSProvider
    from showrunner.providers.video.base import VideoProvider

    class NullLLM(LLMProvider):
        def generate(self, *, system, prompt, max_tokens=4096):
            return ""

        def generate_json(self, *, system, prompt, max_tokens=4096):
            return {}

    class NullTTS(TTSProvider):
        def synthesize(self, text, *, output_path, voice, speed=1.0):
            raise NotImplementedError

        def list_voices(self):
            return []

    class NullVideo(VideoProvider):
        def generate(self, prompt, *, duration, aspect_ratio, output_path):
            raise NotImplementedError

        def poll(self, generation_id):
            return "pending", None

    class NullRender(RenderProvider):
        def setup(self, work_dir):
            pass

        def render(self, *, work_dir, output_path):
            return output_path

        def preview(self, work_dir):
            pass

    assert NullLLM().estimate_cost(input_tokens=1, output_tokens=1) is None
    assert NullLLM().get_usage() == {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    assert NullTTS().estimate_cost(characters=1) is None
    assert NullTTS().get_usage() == {"characters": 0, "calls": 0}
    assert NullVideo().estimate_cost(seconds=1.0) is None
    assert NullVideo().get_usage() == {"video_seconds": 0.0, "clips": 0}
    assert NullRender().get_usage() == {"render_seconds": 0.0}
