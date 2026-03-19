# tests/test_ai_video_planner.py
from unittest.mock import MagicMock
from showrunner.formats.ai_video.planner import generate_plan, STORYBOARD_SYSTEM_PROMPT
from showrunner.plan import Plan
from showrunner.styles.resolver import resolve_style


def test_generate_plan_returns_plan():
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Ocean Wonders",
        "totalDuration": 30,
        "scenes": [
            {"id": "hook", "duration": 5, "narration": "The ocean hides secrets.", "visual": "Cinematic aerial shot of deep blue ocean, golden hour, slow dolly forward", "transition": "fade"},
            {"id": "reveal", "duration": 10, "narration": "Deep below...", "visual": "Underwater shot of coral reef, fish swimming, light rays from surface", "transition": "fade"},
        ],
    }
    style = resolve_style("dramatic-story")
    plan = generate_plan("Ocean mysteries", style=style, llm=mock_llm)
    assert isinstance(plan, Plan)
    assert plan.title == "Ocean Wonders"
    assert len(plan.scenes) == 2


def test_system_prompt_targets_video_generation():
    """Prompt should guide LLM to write video generation prompts, not code descriptions."""
    assert "camera" in STORYBOARD_SYSTEM_PROMPT.lower() or "cinematic" in STORYBOARD_SYSTEM_PROMPT.lower()
    assert "shot" in STORYBOARD_SYSTEM_PROMPT.lower()
    assert "code" not in STORYBOARD_SYSTEM_PROMPT.lower()
