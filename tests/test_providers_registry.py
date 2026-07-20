"""Tests for provider discovery via entry points (providers/registry.py)."""

import sys
from importlib.metadata import EntryPoint, EntryPoints

import pytest

from showrunner.providers.registry import (
    PROVIDER_KINDS,
    ProviderRegistry,
    create_provider,
    get_registry,
)


class DummyTTSProvider:
    """Stand-in provider used to test entry-point registration."""

    def __init__(self, api_key: str | None = None, speed: float = 1.0):
        self.api_key = api_key
        self.speed = speed


def test_provider_kinds():
    assert PROVIDER_KINDS == ("llm", "tts", "video", "render")


def test_builtin_providers_discovered():
    assert {"anthropic", "openai"} <= set(get_registry("llm").list())
    assert {"kokoro", "elevenlabs"} <= set(get_registry("tts").list())
    assert {"gemini", "minimax"} <= set(get_registry("video").list())
    assert {"remotion", "ffmpeg"} <= set(get_registry("render").list())


def test_discovery_does_not_import_provider_modules():
    saved = {
        k: sys.modules.pop(k)
        for k in list(sys.modules)
        if k.startswith("showrunner.providers.llm.")
    }
    try:
        registry = get_registry("llm")
        assert "anthropic" in registry.list()
        assert not any(k.startswith("showrunner.providers.llm.") for k in sys.modules)
    finally:
        sys.modules.update(saved)


def test_load_resolves_builtin_class():
    cls = get_registry("render").load("ffmpeg")
    assert cls.__name__ == "FFmpegRenderProvider"


def test_unknown_provider_errors_list_installed():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_registry("llm").load("nope")
    with pytest.raises(ValueError) as excinfo:
        get_registry("tts").load("nope")
    message = str(excinfo.value)
    assert "Unknown TTS provider" in message
    assert "kokoro" in message and "elevenlabs" in message


def test_unknown_kind_errors():
    with pytest.raises(ValueError, match="Unknown provider kind"):
        ProviderRegistry("nope")


def test_dummy_provider_via_entry_point(monkeypatch):
    ep = EntryPoint(
        "dummy",
        f"{__name__}:DummyTTSProvider",
        "showrunner.providers.tts",
    )
    monkeypatch.setattr(
        "showrunner.providers.registry.entry_points",
        lambda: EntryPoints([ep]),
    )
    registry = get_registry("tts")
    assert "dummy" in registry.list()
    # Built-ins still present alongside the external entry point.
    assert "kokoro" in registry.list()

    provider = registry.create(
        "dummy", {"api_key": "k", "speed": 2.0, "unknown_key": "ignored"}
    )
    assert isinstance(provider, DummyTTSProvider)
    assert provider.api_key == "k"
    assert provider.speed == 2.0


def test_create_provider_passes_named_config_section(monkeypatch):
    ep = EntryPoint(
        "dummy",
        f"{__name__}:DummyTTSProvider",
        "showrunner.providers.tts",
    )
    monkeypatch.setattr(
        "showrunner.providers.registry.entry_points",
        lambda: EntryPoints([ep]),
    )
    provider = create_provider(
        "tts",
        "dummy",
        {"dummy": {"speed": 3.0}, "other-provider": {"api_key": "not-mine"}},
    )
    assert provider.speed == 3.0
    assert provider.api_key is None


def test_register_string_target_is_lazy_and_loadable():
    registry = ProviderRegistry("tts")
    registry.register("dummy", f"{__name__}:DummyTTSProvider")
    assert registry.list() == ["dummy"]
    provider = registry.create("dummy")
    assert isinstance(provider, DummyTTSProvider)


def test_cli_providers_lists_discovered_vs_configured():
    from click.testing import CliRunner

    from showrunner.cli.main import cli

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["providers"])
    assert result.exit_code == 0
    for name in [
        "anthropic", "openai", "kokoro", "elevenlabs",
        "gemini", "minimax", "remotion", "ffmpeg",
    ]:
        assert name in result.output
    # Defaults (anthropic/kokoro/remotion) are flagged as configured.
    assert result.output.count("(configured)") == 3
