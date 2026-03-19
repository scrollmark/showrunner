"""Configuration loading from .showrunner.yaml + CLI overrides."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


DEFAULT_PROVIDERS = {
    "llm": "anthropic",
    "tts": "kokoro",
    "render": "remotion",
}

DEFAULT_OUTPUT = {
    "aspect_ratio": "9:16",
    "captions": False,
    "watermark": None,
}


@dataclass
class Config:
    """Showrunner configuration."""
    default_format: str = "faceless-explainer"
    default_style: str = "3b1b-dark"
    providers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PROVIDERS))
    output: dict = field(default_factory=lambda: dict(DEFAULT_OUTPUT))
    provider_config: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> Config:
        providers = dict(DEFAULT_PROVIDERS)
        providers.update(d.get("providers", {}))
        output = dict(DEFAULT_OUTPUT)
        output.update(d.get("output", {}))
        return cls(
            default_format=d.get("default_format", d.get("default-format", "faceless-explainer")),
            default_style=d.get("default_style", d.get("default-style", "3b1b-dark")),
            providers=providers,
            output=output,
            provider_config={
                k: v for k, v in d.items()
                if k not in {"default_format", "default-format", "default_style", "default-style", "providers", "output"}
                and isinstance(v, dict)
            },
        )

    def merge(self, overrides: dict) -> Config:
        base = {
            "default_format": self.default_format,
            "default_style": self.default_style,
            "providers": dict(self.providers),
            "output": dict(self.output),
            **self.provider_config,
        }
        for k, v in overrides.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                base[k] = {**base[k], **v}
            else:
                base[k] = v
        return Config.from_dict(base)


def load_config(path: Path | None = None) -> Config:
    if path is None:
        path = Path.cwd() / ".showrunner.yaml"
    if not path.exists():
        return Config()
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return Config.from_dict(data)
