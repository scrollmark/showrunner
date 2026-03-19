from unittest.mock import MagicMock
from showrunner.formats.faceless_explainer.planner import generate_plan, STORYBOARD_SYSTEM_PROMPT
from showrunner.plan import Plan
from showrunner.styles.resolver import resolve_style


def test_generate_plan_returns_plan():
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Why Cats Purr",
        "totalDuration": 45,
        "scenes": [
            {"id": "hook", "duration": 5, "narration": "Ever wondered why cats purr?", "visual": "Cat with sound waves", "transition": "fade"},
            {"id": "explanation", "duration": 10, "narration": "It turns out...", "visual": "Diagram of larynx", "transition": "slide-left"},
        ],
    }
    style = resolve_style("3b1b-dark")
    plan = generate_plan("Why do cats purr?", style=style, llm=mock_llm)
    assert isinstance(plan, Plan)
    assert plan.title == "Why Cats Purr"
    assert len(plan.scenes) == 2
    mock_llm.generate_json.assert_called_once()


def test_system_prompt_content():
    assert "scene" in STORYBOARD_SYSTEM_PROMPT.lower()
    assert "narration" in STORYBOARD_SYSTEM_PROMPT.lower()
    assert "json" in STORYBOARD_SYSTEM_PROMPT.lower()
    assert "hook" in STORYBOARD_SYSTEM_PROMPT.lower()
