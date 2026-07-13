"""Tests for the shared provider factory."""

import pytest

from showrunner.providers import factory


def test_create_llm_default_anthropic():
    llm = factory.create_llm("anthropic", {})
    from showrunner.providers.llm.anthropic import AnthropicLLMProvider
    assert isinstance(llm, AnthropicLLMProvider)


def test_create_llm_unknown_raises():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        factory.create_llm("nope", {})


def test_create_tts_kokoro():
    tts = factory.create_tts("kokoro", {})
    from showrunner.providers.tts.kokoro import KokoroTTSProvider
    assert isinstance(tts, KokoroTTSProvider)


def test_create_render_remotion_and_ffmpeg():
    from showrunner.providers.render.ffmpeg import FFmpegRenderProvider
    from showrunner.providers.render.remotion import RemotionRenderProvider
    assert isinstance(factory.create_render("remotion"), RemotionRenderProvider)
    assert isinstance(factory.create_render("ffmpeg"), FFmpegRenderProvider)
    with pytest.raises(ValueError, match="Unknown render provider"):
        factory.create_render("nope")


def test_create_video_unknown_raises():
    with pytest.raises(ValueError, match="Unknown video provider"):
        factory.create_video("nope", {})


def test_pipeline_still_creates_providers():
    """Pipeline delegates to the factory — existing behavior intact."""
    from showrunner.pipeline import Pipeline
    providers = Pipeline()._create_providers("anthropic", "kokoro", "remotion", {})
    assert set(providers) == {"llm", "tts", "render"}
