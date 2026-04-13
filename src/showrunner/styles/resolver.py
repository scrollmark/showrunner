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
        """Format style information for LLM prompts.

        Emits the structured preset as a JSON code block. Models treat JSON
        inside prompts as binding spec, where a text summary they can easily
        paraphrase or ignore. Appends free-form overrides at the bottom.
        """
        body = json.dumps(
            {"preset": self.preset_name, **self.preset},
            indent=2,
        )
        chunks = ["STYLE PRESET (use these values — do not invent alternatives):", "```json", body, "```"]
        if self.overrides:
            chunks.extend([
                "",
                "USER STYLE OVERRIDES (apply on top of preset where compatible):",
                self.overrides,
            ])
        return "\n".join(chunks)

    # Convenience accessors so callers don't have to dict-dig.
    @property
    def colors(self) -> dict:
        return self.preset.get("colors", {})

    @property
    def typography(self) -> dict:
        return self.preset.get("typography", {})

    @property
    def spacing(self) -> dict:
        return self.preset.get("spacing", {})

    @property
    def rhythm(self) -> dict:
        return self.preset.get("rhythm", {})

    @property
    def motion(self) -> dict:
        return self.preset.get("motion", {})

    def fonts_in_use(self) -> list[str]:
        """Unique font families referenced by the typography roles."""
        seen: list[str] = []
        for role in self.typography.values():
            family = role.get("family") if isinstance(role, dict) else None
            if family and family not in seen:
                seen.append(family)
        return seen


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
