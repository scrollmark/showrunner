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
    ) -> Path | Plan:
        """Run the full pipeline."""
        registry = get_registry()
        fmt = registry.get(self.format_name)

        style_name = style or self.config.default_style
        resolved_style = resolve_style(style_name, overrides=style_override)

        providers = self._create_providers(
            llm_name=self.config.providers.get("llm", "anthropic"),
            tts_name=self.config.providers.get("tts", "kokoro"),
            render_name=self.config.providers.get("render", "remotion"),
            provider_config=self.config.provider_config,
        )

        # Set format options
        fmt._style = resolved_style
        fmt._aspect_ratio = aspect_ratio
        fmt._voice = voice
        fmt._speed = speed
        fmt._parallel = parallel

        # Plan
        plan = fmt.plan(topic, resolved_style, self.config, providers["llm"])

        if dry_run:
            return plan

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

    def _create_providers(
        self, llm_name: str, tts_name: str, render_name: str, provider_config: dict
    ) -> dict:
        providers = {}

        if llm_name == "anthropic":
            from showrunner.providers.llm.anthropic import AnthropicLLMProvider

            cfg = provider_config.get("anthropic", {})
            providers["llm"] = AnthropicLLMProvider(
                model=cfg.get("model", "claude-sonnet-4-5-20250929")
            )
        elif llm_name == "openai":
            from showrunner.providers.llm.openai import OpenAILLMProvider

            cfg = provider_config.get("openai", {})
            providers["llm"] = OpenAILLMProvider(model=cfg.get("model", "gpt-4o"))
        else:
            raise ValueError(f"Unknown LLM provider: {llm_name}")

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
        else:
            raise ValueError(f"Unknown render provider: {render_name}")

        return providers


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:80]
