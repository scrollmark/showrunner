"""Provider discovery and registration via entry points.

Mirrors ``formats/registry.py``: providers register under the entry-point
groups ``showrunner.providers.{llm,tts,video,render}`` so external packages
can add providers with zero core wiring. Resolution stays lazy — a
provider's module is imported only when that provider is actually selected.

Built-ins are also seeded directly (as synthetic entry points) so discovery
works even when the installed distribution metadata predates the entry-point
declarations, e.g. when running from a source checkout via PYTHONPATH.
``pyproject.toml`` declares the same built-ins under the same groups.
"""

from __future__ import annotations

import inspect
from importlib.metadata import EntryPoint, entry_points

ENTRY_POINT_PREFIX = "showrunner.providers"

PROVIDER_KINDS = ("llm", "tts", "video", "render")

# Display labels used in error messages ("Unknown LLM provider: ...").
_KIND_LABELS = {"llm": "LLM", "tts": "TTS", "video": "video", "render": "render"}

# Built-in providers: name -> "module:ClassName". These are duplicated as
# real entry points in pyproject.toml; this table is the source-checkout
# fallback and keeps built-ins available without a reinstall.
_BUILTINS: dict[str, dict[str, str]] = {
    "llm": {
        "anthropic": "showrunner.providers.llm.anthropic:AnthropicLLMProvider",
        "openai": "showrunner.providers.llm.openai:OpenAILLMProvider",
    },
    "tts": {
        "kokoro": "showrunner.providers.tts.kokoro:KokoroTTSProvider",
        "elevenlabs": "showrunner.providers.tts.elevenlabs:ElevenLabsTTSProvider",
    },
    "video": {
        "gemini": "showrunner.providers.video.gemini:GeminiVideoProvider",
        "minimax": "showrunner.providers.video.minimax:MinimaxVideoProvider",
    },
    "render": {
        "remotion": "showrunner.providers.render.remotion:RemotionRenderProvider",
        "ffmpeg": "showrunner.providers.render.ffmpeg:FFmpegRenderProvider",
    },
}


class ProviderRegistry:
    """Name -> provider class registry for a single provider kind."""

    def __init__(self, kind: str):
        if kind not in PROVIDER_KINDS:
            raise ValueError(
                f"Unknown provider kind '{kind}'. Expected one of {list(PROVIDER_KINDS)}"
            )
        self.kind = kind
        self._entries: dict[str, EntryPoint] = {}

    def register(self, name: str, target: str | EntryPoint) -> None:
        """Register a provider by name. ``target`` is either an EntryPoint
        or a lazy "module:ClassName" reference (nothing is imported yet)."""
        if isinstance(target, str):
            target = EntryPoint(
                name=name, value=target, group=f"{ENTRY_POINT_PREFIX}.{self.kind}"
            )
        self._entries[name] = target

    def list(self) -> list[str]:
        return sorted(self._entries)

    def load(self, name: str) -> type:
        """Resolve a provider name to its class (imports the module now)."""
        if name not in self._entries:
            label = _KIND_LABELS[self.kind]
            installed = ", ".join(self.list()) or "(none)"
            raise ValueError(
                f"Unknown {label} provider: {name}. Installed {label} providers: {installed}"
            )
        return self._entries[name].load()

    def create(self, name: str, config: dict | None = None):
        """Instantiate a provider, passing only the config keys its
        constructor accepts (unknown config keys are ignored)."""
        cls = self.load(name)
        return cls(**_constructor_kwargs(cls, config or {}))

    def load_entry_points(self) -> None:
        group = f"{ENTRY_POINT_PREFIX}.{self.kind}"
        eps = entry_points()
        found = eps.select(group=group) if hasattr(eps, "select") else eps.get(group, [])
        for ep in found:
            self._entries[ep.name] = ep


def _constructor_kwargs(cls: type, config: dict) -> dict:
    """Filter a provider's config section down to constructor parameters."""
    if cls.__init__ is object.__init__:
        return {}
    try:
        params = inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):
        return {}
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(config)
    return {k: v for k, v in config.items() if k in params and k != "self"}


def get_registry(kind: str) -> ProviderRegistry:
    """Build the registry for one provider kind: built-ins seeded first,
    then entry points overlaid (an entry point may shadow a built-in)."""
    registry = ProviderRegistry(kind)
    for name, target in _BUILTINS[kind].items():
        registry.register(name, target)
    registry.load_entry_points()
    return registry


def create_provider(kind: str, name: str, provider_config: dict | None = None):
    """Resolve and instantiate a provider by kind + configured name.

    ``provider_config`` is the full per-provider config mapping from
    ``Config.provider_config`` — the section named after the provider
    (e.g. ``provider_config["anthropic"]``) is passed to the constructor.
    """
    section = (provider_config or {}).get(name, {})
    return get_registry(kind).create(name, section)
