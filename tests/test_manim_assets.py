# tests/test_manim_assets.py
from unittest.mock import MagicMock

import pytest

from showrunner.formats.manim_explainer.assets import (
    FORBIDDEN_APIS,
    MANIM_VERSION,
    MAX_RETRIES,
    build_codegen_system_prompt,
    generate_all_narrations,
    generate_scene_code,
    lint_code,
    scene_class_name,
)
from showrunner.plan import Plan, Scene


VALID_CODE = """from manim import *

class Hook(Scene):
    def construct(self):
        self.camera.background_color = "#1c1c2e"
        eq = MathTex(r"e^{i\\pi} = -1")
        self.play(Write(eq))
        self.wait(3)
"""


def _scene(**overrides):
    defaults = dict(id="hook", duration=5, narration="Hello", visual="Equation centered")
    defaults.update(overrides)
    return Scene(**defaults)


# --- scene_class_name -------------------------------------------------------

def test_scene_class_name_camelcases():
    assert scene_class_name("unit_circle") == "UnitCircle"
    assert scene_class_name("hook") == "Hook"


def test_scene_class_name_handles_leading_digit():
    assert scene_class_name("3_blue_1_brown").startswith("Scene")


# --- lint -------------------------------------------------------------------

@pytest.mark.parametrize("api", ["ShowCreation", "TextMobject", "TexMobject",
                                 "GraphScene", "get_graph", "ApplyMethod"])
def test_lint_catches_forbidden_api(api):
    code = VALID_CODE.replace("Write(eq)", f"{api}(eq)")
    violations = lint_code(code, "Hook")
    assert any(api in v for v in violations)


def test_lint_catches_manimgl_import():
    code = VALID_CODE.replace("from manim import *", "from manimlib import *")
    violations = lint_code(code, "Hook")
    assert any("manimlib" in v for v in violations)


def test_lint_requires_class_and_wait():
    violations = lint_code("from manim import *\nprint('hi')", "Hook")
    assert any("class Hook(Scene)" in v for v in violations)
    assert any("self.wait" in v for v in violations)


def test_lint_passes_valid_code():
    assert lint_code(VALID_CODE, "Hook") == []


# --- prompt regression (acceptance criterion) -------------------------------

def test_prompt_pins_ce_version():
    prompt = build_codegen_system_prompt(
        class_name="Hook", duration=5, width=1080, height=1920, style_context="ctx",
    )
    assert f"Manim Community Edition v{MANIM_VERSION}.x" in prompt
    assert MANIM_VERSION == "0.20"


def test_prompt_contains_full_forbidden_api_list():
    prompt = build_codegen_system_prompt(
        class_name="Hook", duration=5, width=1080, height=1920, style_context="ctx",
    )
    for name, _hint in FORBIDDEN_APIS:
        assert name in prompt, f"forbidden API {name!r} missing from codegen prompt"
    # ManimGL is explicitly banned
    assert "NEVER use ManimGL" in prompt


def test_prompt_enforces_layout_and_duration_sync():
    prompt = build_codegen_system_prompt(
        class_name="Hook", duration=9, width=1080, height=1920, style_context="ctx",
    )
    # relative-layout discipline
    assert ".next_to(" in prompt
    assert "VGroup" in prompt
    assert "NEVER hard-code absolute coordinates" in prompt
    # duration sync via wait padding
    assert "self.wait(" in prompt
    assert "9 seconds" in prompt
    # frame bounds adapt to the render aspect ratio (portrait → 4.5 wide)
    assert "4.50" in prompt


def test_prompt_includes_class_name_and_style():
    prompt = build_codegen_system_prompt(
        class_name="UnitCircle", duration=5, width=1920, height=1080,
        style_context="STYLE_MARKER", background_color="#123456",
    )
    assert "class UnitCircle(Scene):" in prompt
    assert "STYLE_MARKER" in prompt
    assert "#123456" in prompt


# --- codegen repair loop ----------------------------------------------------

def test_generate_scene_code_success_first_try():
    llm = MagicMock()
    llm.generate.return_value = f"```python\n{VALID_CODE}```"
    validate_fn = MagicMock(return_value=(True, ""))

    code = generate_scene_code(
        scene=_scene(), style_context="ctx", llm=llm, validate_fn=validate_fn, quiet=True,
    )
    assert "class Hook(Scene):" in code
    assert llm.generate.call_count == 1
    validate_fn.assert_called_once()


def test_generate_scene_code_repairs_on_render_traceback():
    llm = MagicMock()
    llm.generate.return_value = f"```python\n{VALID_CODE}```"
    validate_fn = MagicMock(side_effect=[
        (False, "NameError: name 'Circle2' is not defined"),
        (True, ""),
    ])

    code = generate_scene_code(
        scene=_scene(), style_context="ctx", llm=llm, validate_fn=validate_fn, quiet=True,
    )
    assert code
    assert llm.generate.call_count == 2
    # The traceback is fed back to the LLM in the repair prompt
    repair_prompt = llm.generate.call_args.kwargs["prompt"]
    assert "NameError" in repair_prompt
    assert "Previous code" in repair_prompt


def test_generate_scene_code_lint_failure_skips_render():
    """A ManimGL hallucination is caught statically — no render is spent."""
    bad = VALID_CODE.replace("Write(eq)", "ShowCreation(eq)")
    llm = MagicMock()
    llm.generate.side_effect = [f"```python\n{bad}```", f"```python\n{VALID_CODE}```"]
    validate_fn = MagicMock(return_value=(True, ""))

    generate_scene_code(
        scene=_scene(), style_context="ctx", llm=llm, validate_fn=validate_fn, quiet=True,
    )
    # validate_fn (the render) only ran for the clean second attempt
    validate_fn.assert_called_once()
    repair_prompt = llm.generate.call_args.kwargs["prompt"]
    assert "ShowCreation" in repair_prompt


def test_generate_scene_code_raises_after_max_retries():
    llm = MagicMock()
    llm.generate.return_value = f"```python\n{VALID_CODE}```"
    validate_fn = MagicMock(return_value=(False, "Boom traceback"))

    with pytest.raises(RuntimeError, match="hook.*failed"):
        generate_scene_code(
            scene=_scene(), style_context="ctx", llm=llm, validate_fn=validate_fn, quiet=True,
        )
    assert llm.generate.call_count == MAX_RETRIES + 1


def test_generate_scene_code_accepts_unfenced_response():
    llm = MagicMock()
    llm.generate.return_value = VALID_CODE
    validate_fn = MagicMock(return_value=(True, ""))
    code = generate_scene_code(
        scene=_scene(), style_context="ctx", llm=llm, validate_fn=validate_fn, quiet=True,
    )
    assert "class Hook(Scene):" in code


# --- narration --------------------------------------------------------------

def test_generate_all_narrations_returns_durations(tmp_path):
    plan = Plan(title="T", total_duration=10, scenes=[
        _scene(id="hook"), _scene(id="payoff"),
    ])
    tts = MagicMock()
    tts.synthesize.return_value = MagicMock(duration=3.0)

    durations = generate_all_narrations(plan, tts=tts, output_dir=tmp_path / "audio")
    assert durations == {"hook": 3.0, "payoff": 3.0}
    assert tts.synthesize.call_count == 2


def test_generate_all_narrations_extends_short_scenes(tmp_path):
    plan = Plan(title="T", total_duration=5, scenes=[_scene(duration=5)])
    tts = MagicMock()
    tts.synthesize.return_value = MagicMock(duration=7.2)

    generate_all_narrations(plan, tts=tts, output_dir=tmp_path / "audio")
    assert plan.scenes[0].duration == 9  # ceil(7.2) + 1
    assert plan.total_duration == 9
