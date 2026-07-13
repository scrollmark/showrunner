"""Shared provider construction — one factory for the CLI and the Pipeline.

Providers are keyed by short names in `.showrunner.yaml`. Imports stay
local so optional dependencies are only required when a provider is
actually selected.
"""

from __future__ import annotations


def create_llm(name: str, provider_config: dict):
    if name == "anthropic":
        from showrunner.providers.llm.anthropic import AnthropicLLMProvider

        cfg = provider_config.get("anthropic", {})
        return AnthropicLLMProvider(model=cfg.get("model", "claude-sonnet-4-5-20250929"))
    if name == "openai":
        from showrunner.providers.llm.openai import OpenAILLMProvider

        cfg = provider_config.get("openai", {})
        return OpenAILLMProvider(model=cfg.get("model", "gpt-4o"))
    raise ValueError(f"Unknown LLM provider: {name}")


def create_tts(name: str, provider_config: dict):
    if name == "kokoro":
        from showrunner.providers.tts.kokoro import KokoroTTSProvider

        return KokoroTTSProvider()
    if name == "elevenlabs":
        from showrunner.providers.tts.elevenlabs import ElevenLabsTTSProvider

        cfg = provider_config.get("elevenlabs", {})
        return ElevenLabsTTSProvider(api_key=cfg.get("api_key"))
    raise ValueError(f"Unknown TTS provider: {name}")


def create_render(name: str):
    if name == "remotion":
        from showrunner.providers.render.remotion import RemotionRenderProvider

        return RemotionRenderProvider()
    if name == "ffmpeg":
        from showrunner.providers.render.ffmpeg import FFmpegRenderProvider

        return FFmpegRenderProvider()
    raise ValueError(f"Unknown render provider: {name}")


def create_video(name: str, provider_config: dict):
    if name == "minimax":
        from showrunner.providers.video.minimax import MinimaxVideoProvider

        cfg = provider_config.get("minimax", {})
        return MinimaxVideoProvider(
            api_key=cfg.get("api_key"), model=cfg.get("model", "video-01-live2d")
        )
    if name == "gemini":
        from showrunner.providers.video.gemini import GeminiVideoProvider

        cfg = provider_config.get("gemini", {})
        return GeminiVideoProvider(
            api_key=cfg.get("api_key"), model=cfg.get("model", "veo-3.1-generate-preview")
        )
    raise ValueError(f"Unknown video provider: {name}")
