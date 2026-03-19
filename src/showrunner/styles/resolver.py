"""Style preset loading and resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources


PRESETS_PACKAGE = "showrunner.styles.presets"


@dataclass
class ResolvedStyle:
    """A resolved style: base preset + optional free-form overrides."""
    preset_name: str
    preset: dict
    overrides: str | None = None

    def to_prompt_context(self) -> str:
        """Format style information for LLM prompts."""
        colors = self.preset.get("colors", {})
        typo = self.preset.get("typography", {})
        anim = self.preset.get("animation", {})

        lines = [
            f"Style preset: {self.preset_name}",
            f"  Background: {colors.get('background', '#000')}",
            f"  Primary: {colors.get('primary', '#fff')}",
            f"  Secondary: {colors.get('secondary', '#888')}",
            f"  Accent: {colors.get('accent', '#ff0')}",
            f"  Text: {colors.get('text', '#fff')}",
            f"  Text muted: {colors.get('textMuted', '#aaa')}",
            f"  Font: {typo.get('fontFamily', 'Inter')}",
            f"  Title size: {typo.get('titleSize', 72)}px",
            f"  Body size: {typo.get('bodySize', 36)}px",
            f"  Pacing: {anim.get('pacing', 'measured')}",
            f"  Default transition: {anim.get('defaultTransition', 'fade')}",
        ]
        if self.overrides:
            lines.append(f"\nStyle overrides from user: {self.overrides}")
        return "\n".join(lines)


def list_presets() -> list[str]:
    preset_files = resources.files(PRESETS_PACKAGE)
    return sorted(
        p.name.removesuffix(".json")
        for p in preset_files.iterdir()
        if p.name.endswith(".json")
    )


def list_presets_detailed() -> list[dict]:
    result = []
    for name in list_presets():
        preset = load_preset(name)
        result.append({"name": name, "description": preset.get("description", "")})
    return result


def load_preset(name: str) -> dict:
    preset_files = resources.files(PRESETS_PACKAGE)
    target = preset_files.joinpath(f"{name}.json")
    try:
        text = target.read_text(encoding="utf-8")
    except (FileNotFoundError, TypeError):
        raise FileNotFoundError(f"Style preset '{name}' not found. Available: {list_presets()}")
    return json.loads(text)


def resolve_style(preset_name: str, overrides: str | None = None) -> ResolvedStyle:
    preset = load_preset(preset_name)
    return ResolvedStyle(preset_name=preset_name, preset=preset, overrides=overrides)
