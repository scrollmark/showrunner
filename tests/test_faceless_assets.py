from unittest.mock import MagicMock
from pathlib import Path

from showrunner.formats.faceless_explainer.assets import (
    generate_scene_code,
    generate_all_scene_code,
    generate_all_narrations,
    CODEGEN_SYSTEM_PROMPT,
    CODEGEN_USER_TEMPLATE,
    REMOTION_LLM_RULES,
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


# ---------------------------------------------------------------------------
# Remotion official LLM codegen rules (issue #24) — prompt-content regression.
# These assert the built system prompt carries the key rules from
# remotion.dev/docs/ai/system-prompt so a prompt refactor can't silently
# drop them.
# ---------------------------------------------------------------------------

def _built_system_prompt(component_name="Hook"):
    return CODEGEN_SYSTEM_PROMPT.format(
        width=1080, height=1920, fps=30, duration_frames=150, duration=5,
        style_context="test", component_name=component_name,
    )


def test_codegen_prompt_embeds_vendored_remotion_rules():
    prompt = _built_system_prompt()
    assert REMOTION_LLM_RULES in prompt
    assert "__REMOTION_RULES__" not in prompt


def test_codegen_prompt_determinism_rules():
    prompt = _built_system_prompt()
    # Math.random is explicitly forbidden; seeded remotion random() required.
    assert "Math.random()" in prompt
    assert "random('seed')" in prompt
    assert "Date.now()" in prompt
    # `random` is offered as an allowed remotion import.
    assert "random," in prompt or " random" in prompt


def test_codegen_prompt_interpolate_clamp_rule():
    prompt = _built_system_prompt()
    assert "extrapolateLeft" in prompt
    assert "extrapolateRight" in prompt
    assert "clamp" in prompt


def test_codegen_prompt_self_contained_rule():
    prompt = _built_system_prompt()
    assert "self-contained" in prompt.lower()
    # Network / external data is banned.
    assert "fetch" in prompt.lower()
    assert "no external data" in prompt.lower()


def test_codegen_prompt_export_contract():
    prompt = _built_system_prompt(component_name="KeyInsight")
    # Predictable component name + mandatory default export (composer contract).
    assert "exact name `KeyInsight`" in prompt
    assert "export default KeyInsight" in prompt
    assert "export { KeyInsight };" in prompt


def test_codegen_prompt_forbids_markdown_fences():
    prompt = _built_system_prompt()
    assert "markdown fences" in prompt.lower()
    # The old instruction asked FOR a fence — make sure it stays gone.
    assert "inside a single ```tsx fence" not in prompt
    # The user-facing template repeats the belt-and-braces rule.
    assert "no markdown fences" in CODEGEN_USER_TEMPLATE.lower()


def test_codegen_prompt_layout_and_dimension_rules():
    prompt = _built_system_prompt()
    assert "useVideoConfig()" in prompt
    assert "AbsoluteFill" in prompt
    # Prefer transform-based animation in style props.
    assert "scale()/translate()/rotate()" in prompt


def test_codegen_retry_prompt_repeats_key_rules():
    """On validation failure the retry prompt reminds the model of the rules."""
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = ['```tsx\nbad code\n```', _CLEAN_LLM_OUTPUT]
    calls = [0]

    def validate_fn(scene_id, code):
        calls[0] += 1
        return (False, "Type error") if calls[0] == 1 else (True, "")

    scene = Scene(id="hook", duration=5, narration="Hello", visual="Title card")
    generate_scene_code(
        scene=scene, style_context="dark", llm=mock_llm,
        validate_fn=validate_fn, width=1080, height=1920, quiet=True,
    )
    retry_prompt = mock_llm.generate.call_args_list[1].kwargs["prompt"]
    assert "random('seed')" in retry_prompt
    assert "clamp" in retry_prompt
    assert "no markdown fences" in retry_prompt.lower()


def test_generate_all_narrations_writes_caption_json(tmp_path):
    import json
    from showrunner.providers.tts.base import AudioFile, WordTiming

    def fake_synthesize(text, *, output_path, voice, speed):
        return AudioFile(
            path=Path(output_path), duration=1.0,
            word_timings=[WordTiming(word=w, start=i * 0.5, end=i * 0.5 + 0.4)
                          for i, w in enumerate(text.split())],
        )

    mock_tts = MagicMock()
    mock_tts.synthesize.side_effect = fake_synthesize

    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="hook", duration=5, narration="Hello world", visual="V"),
            Scene(id="main", duration=5, narration="Second scene", visual="V"),
        ],
    )
    captions_dir = tmp_path / "captions"
    generate_all_narrations(
        plan, tts=mock_tts, output_dir=tmp_path / "audio", captions_dir=captions_dir,
    )
    for scene_id in ("hook", "main"):
        data = json.loads((captions_dir / f"{scene_id}.json").read_text())
        assert len(data) == 2
        assert set(data[0]) == {"text", "startMs", "endMs", "timestampMs"}
    hook = json.loads((captions_dir / "hook.json").read_text())
    assert hook[0]["text"] == "Hello"
    assert hook[1]["startMs"] == 500


def test_generate_all_narrations_no_captions_dir_writes_nothing(tmp_path):
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = MagicMock(duration=1.0, path=tmp_path / "x.wav")
    plan = Plan(title="Test", total_duration=5,
                scenes=[Scene(id="hook", duration=5, narration="Hi", visual="V")])
    generate_all_narrations(plan, tts=mock_tts, output_dir=tmp_path / "audio")
    assert not (tmp_path / "captions").exists()
