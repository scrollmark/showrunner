from unittest.mock import MagicMock
from pathlib import Path

from showrunner.formats.faceless_explainer.assets import (
    generate_scene_code,
    generate_all_scene_code,
    generate_all_narrations,
    CODEGEN_SYSTEM_PROMPT,
    _extract_code,
)
from showrunner.plan import Plan, Scene


def test_extract_code_from_fence():
    text = '```tsx\nconst x = 1;\n```'
    assert _extract_code(text) == "const x = 1;"


def test_extract_code_no_fence():
    text = "const x = 1;"
    assert _extract_code(text) == "const x = 1;"


def test_codegen_prompt_has_key_rules():
    # Format it first to check content
    prompt = CODEGEN_SYSTEM_PROMPT.format(
        width=1080, height=1920, fps=30, duration_frames=150, duration=5,
        style_context="test", component_name="Hook",
    )
    assert "interpolate" in prompt.lower()
    assert "remotion" in prompt.lower()
    assert "easing" in prompt.lower()
    assert "export default Hook" in prompt


_CLEAN_LLM_OUTPUT = (
    '```tsx\n'
    'import { CenterStack } from "../layouts";\n'
    'export default function Hook() { return <CenterStack title="hi" />; }\n'
    '```'
)


def test_generate_scene_code():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = _CLEAN_LLM_OUTPUT
    # validate_fn now takes (scene_id, code) so tsc-aware validators can
    # write the file to disk before type-checking.
    mock_validate = MagicMock(return_value=(True, ""))

    scene = Scene(id="hook", duration=5, narration="Hello", visual="Title card")
    code = generate_scene_code(
        scene=scene, style_context="dark", llm=mock_llm,
        validate_fn=mock_validate, width=1080, height=1920,
    )
    assert "CenterStack" in code
    mock_llm.generate.assert_called_once()
    mock_validate.assert_called_with("hook", code)


def test_generate_scene_code_retries_on_failure():
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        '```tsx\nbad code\n```',
        _CLEAN_LLM_OUTPUT,
    ]
    call_count = [0]
    def validate_fn(scene_id, code):
        call_count[0] += 1
        if call_count[0] == 1:
            return False, "Type error"
        return True, ""

    scene = Scene(id="hook", duration=5, narration="Hello", visual="Title card")
    code = generate_scene_code(
        scene=scene, style_context="dark", llm=mock_llm,
        validate_fn=validate_fn, width=1080, height=1920,
    )
    assert "CenterStack" in code
    assert mock_llm.generate.call_count == 2


def test_generate_all_narrations():
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = MagicMock(duration=3.5, path=Path("/tmp/test.wav"))

    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="hook", duration=5, narration="Hello", visual="V"),
            Scene(id="main", duration=5, narration="World", visual="V"),
        ],
    )
    durations = generate_all_narrations(plan, tts=mock_tts, output_dir=Path("/tmp"))
    assert len(durations) == 2
    assert mock_tts.synthesize.call_count == 2


def test_generate_all_narrations_extends_duration():
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = MagicMock(duration=8.5, path=Path("/tmp/test.wav"))

    plan = Plan(
        title="Test", total_duration=5,
        scenes=[Scene(id="hook", duration=5, narration="Long narration", visual="V")],
    )
    generate_all_narrations(plan, tts=mock_tts, output_dir=Path("/tmp"))
    assert plan.scenes[0].duration == 10  # ceil(8.5) + 1
    assert plan.total_duration == 10
