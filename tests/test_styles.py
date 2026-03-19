import pytest
from showrunner.styles.resolver import ResolvedStyle, list_presets, list_presets_detailed, load_preset, resolve_style


def test_list_presets_returns_all_seven():
    presets = list_presets()
    assert len(presets) == 7
    assert "3b1b-dark" in presets
    assert "bold-neon" in presets


def test_load_preset():
    preset = load_preset("3b1b-dark")
    assert preset["name"] == "3b1b-dark"
    assert "colors" in preset
    assert "typography" in preset
    assert "animation" in preset


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
    assert len(presets) == 7
    assert all("name" in p and "description" in p for p in presets)
