import pytest
from showrunner.styles.resolver import ResolvedStyle, list_presets, list_presets_detailed, load_preset, resolve_style


def test_list_presets_includes_core_names():
    presets = list_presets()
    for expected in ("3b1b-dark", "bold-neon", "clean-corporate", "minty-fresh",
                     "sunny-editorial", "forest-breath", "paper-press"):
        assert expected in presets
    assert len(presets) >= 11


def test_load_preset():
    preset = load_preset("3b1b-dark")
    assert preset["name"] == "3b1b-dark"
    assert "colors" in preset
    assert "typography" in preset
    assert "spacing" in preset
    assert "rhythm" in preset
    assert "motion" in preset


def test_preset_typography_is_role_based():
    preset = load_preset("bold-neon")
    typo = preset["typography"]
    for role in ("display", "title", "subhead", "body", "caption", "label"):
        assert role in typo, f"missing typography role: {role}"
        entry = typo[role]
        assert {"family", "weight", "size", "lineHeight"} <= set(entry.keys())


def test_preset_rhythm_shape():
    preset = load_preset("bold-neon")
    rhythm = preset["rhythm"]
    assert "bpm" in rhythm and "transitionBeats" in rhythm and "fps" in rhythm


def test_resolved_style_accessors():
    style = resolve_style("bold-neon")
    assert style.colors["background"] == "#0a0a0a"
    assert style.typography["title"]["family"] == "Space Grotesk"
    assert style.rhythm["bpm"] == 140
    fonts = style.fonts_in_use()
    assert "Inter" in fonts and "Space Grotesk" in fonts


def test_to_prompt_context_emits_json():
    style = resolve_style("bold-neon")
    ctx = style.to_prompt_context()
    assert "```json" in ctx
    assert "bold-neon" in ctx
    # Structured preset should be recoverable from the code block.
    body = ctx.split("```json", 1)[1].split("```", 1)[0].strip()
    import json as _json
    parsed = _json.loads(body)
    assert parsed["rhythm"]["bpm"] == 140


def test_load_preset_not_found():
    with pytest.raises(FileNotFoundError):
        load_preset("nonexistent")


def test_resolve_style():
    style = resolve_style("bold-neon")
    assert style.preset_name == "bold-neon"
    assert style.overrides is None


def test_resolve_style_with_overrides():
    style = resolve_style("3b1b-dark", overrides="use red accents")
    assert style.overrides == "use red accents"


def test_to_prompt_context():
    style = resolve_style("3b1b-dark")
    ctx = style.to_prompt_context()
    assert "3b1b-dark" in ctx


def test_list_presets_detailed():
    presets = list_presets_detailed()
    assert len(presets) >= 11
    assert all("name" in p and "description" in p for p in presets)
