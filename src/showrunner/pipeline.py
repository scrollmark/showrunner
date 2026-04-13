"""Pipeline orchestrator — drives format through plan -> assets -> compose -> render."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from showrunner.config import Config, load_config
from showrunner.formats.registry import get_registry
from showrunner.plan import Plan
from showrunner.styles.resolver import resolve_style


class Pipeline:
    """Orchestrates video generation through a Format plugin."""

    def __init__(self, format_name: str = "faceless-explainer", config: Config | None = None):
        self.format_name = format_name
        self.config = config or load_config()

    def run(
        self,
        topic: str,
        *,
        style: str | None = None,
        style_override: str | None = None,
        output_path: Path | None = None,
        aspect_ratio: str = "9:16",
        voice: str = "af_heart",
        speed: float = 1.0,
        captions: bool = False,
        watermark: str | None = None,
        parallel: bool = False,
        auto_approve: bool = False,
        no_audio: bool = False,
        dry_run: bool = False,
        preview: bool = False,
        music: str | None = "auto",
        music_volume: float | None = None,
        music_seed: str | None = None,
    ) -> Path | Plan:
        """Run the full pipeline."""
        registry = get_registry()
        fmt = registry.get(self.format_name)

        style_name = style or self.config.default_style
        resolved_style = resolve_style(style_name, overrides=style_override)

        # Dry-run only needs the LLM — building the full provider set would
        # instantiate render/TTS/video providers (and their API key checks)
        # for no reason, and breaks when the user hasn't configured them.
        if dry_run:
            llm = self._create_llm(
                self.config.providers.get("llm", "anthropic"),
                self.config.provider_config,
            )
            return fmt.plan(topic, resolved_style, self.config, llm)

        # Each format declares its render pipeline via class attrs (see Format base).
        providers = self._create_providers(
            llm_name=self.config.providers.get("llm", "anthropic"),
            tts_name=self.config.providers.get("tts", "kokoro"),
            render_name=fmt.preferred_render_provider,
            provider_config=self.config.provider_config,
            video_name=self.config.providers.get("video") if fmt.requires_video_provider else None,
        )

        # Set format options
        fmt._style = resolved_style
        fmt._aspect_ratio = aspect_ratio
        fmt._voice = voice
        fmt._speed = speed
        fmt._parallel = parallel
        fmt._music_selection = self._resolve_music(
            music=music, seed=music_seed or topic, volume=music_volume,
            preset=resolved_style.preset,
        )

        # Plan
        plan = fmt.plan(topic, resolved_style, self.config, providers["llm"])

        # Setup work dir
        work_dir = Path(tempfile.mkdtemp(prefix="showrunner-"))
        providers["render"].setup(work_dir)

        # Assets
        if not no_audio:
            assets = fmt.generate_assets(plan, providers, work_dir)
        else:
            assets = {"has_audio": False, "durations": {}, "width": 1080, "height": 1920}

        # Compose
        fmt.compose(plan, assets, work_dir, captions=captions, watermark=watermark)

        if preview:
            providers["render"].preview(work_dir)
            return plan

        # Render
        if output_path is None:
            output_path = Path.cwd() / "output" / f"{_slugify(plan.title)}.mp4"

        result = providers["render"].render(work_dir=work_dir, output_path=output_path)
        return result

    def _resolve_music(self, *, music: str | None, seed: str, volume: float | None, preset: dict):
        """Turn the CLI's `--music` into a concrete track (or None).

        Values: "none" / None → no music. "auto" → mood-picked from the
        preset. Anything else → track id lookup.
        """
        from showrunner.music import MusicCatalog, MusicPicker

        if music in (None, "none"):
            return None
        catalog = MusicCatalog.load()
        if not catalog.tracks:
            # Graceful no-op when the user hasn't provisioned a catalog yet.
            return None

        if music == "auto":
            track = MusicPicker(catalog).pick_for_preset(preset, seed=seed)
        else:
            track = catalog.get(music)
            if track is None:
                raise ValueError(
                    f"Music track '{music}' not in catalog. "
                    "Run `showrunner music list` to see available tracks."
                )
        if track is None:
            return None
        preset_volume = (preset.get("music") or {}).get("volume", 0.2)
        return {
            "track": track,
            "audio_path": catalog.resolve_audio_path(track),
            "volume": volume if volume is not None else preset_volume,
        }

    def _create_llm(self, llm_name: str, provider_config: dict):
        if llm_name == "anthropic":
            from showrunner.providers.llm.anthropic import AnthropicLLMProvider

            cfg = provider_config.get("anthropic", {})
            return AnthropicLLMProvider(model=cfg.get("model", "claude-sonnet-4-5-20250929"))
        if llm_name == "openai":
            from showrunner.providers.llm.openai import OpenAILLMProvider

            cfg = provider_config.get("openai", {})
            return OpenAILLMProvider(model=cfg.get("model", "gpt-4o"))
        raise ValueError(f"Unknown LLM provider: {llm_name}")

    def _create_providers(
        self, llm_name: str, tts_name: str, render_name: str, provider_config: dict,
        video_name: str | None = None,
    ) -> dict:
        providers = {"llm": self._create_llm(llm_name, provider_config)}

        if tts_name == "kokoro":
            from showrunner.providers.tts.kokoro import KokoroTTSProvider

            providers["tts"] = KokoroTTSProvider()
        elif tts_name == "elevenlabs":
            from showrunner.providers.tts.elevenlabs import ElevenLabsTTSProvider

            cfg = provider_config.get("elevenlabs", {})
            providers["tts"] = ElevenLabsTTSProvider(api_key=cfg.get("api_key"))
        else:
            raise ValueError(f"Unknown TTS provider: {tts_name}")

        if render_name == "remotion":
            from showrunner.providers.render.remotion import RemotionRenderProvider

            providers["render"] = RemotionRenderProvider()
        elif render_name == "ffmpeg":
            from showrunner.providers.render.ffmpeg import FFmpegRenderProvider

            providers["render"] = FFmpegRenderProvider()
        else:
            raise ValueError(f"Unknown render provider: {render_name}")

        if video_name:
            if video_name == "minimax":
                from showrunner.providers.video.minimax import MinimaxVideoProvider

                cfg = provider_config.get("minimax", {})
                providers["video"] = MinimaxVideoProvider(
                    api_key=cfg.get("api_key"), model=cfg.get("model", "video-01-live2d")
                )
            elif video_name == "gemini":
                from showrunner.providers.video.gemini import GeminiVideoProvider

                cfg = provider_config.get("gemini", {})
                providers["video"] = GeminiVideoProvider(
                    api_key=cfg.get("api_key"), model=cfg.get("model", "veo-3.1-generate-preview")
                )
            else:
                raise ValueError(f"Unknown video provider: {video_name}")

        return providers


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:80]
