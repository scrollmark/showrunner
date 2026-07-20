# tests/test_manim_planner.py
from unittest.mock import MagicMock

from showrunner.formats.manim_explainer.planner import (
    STORYBOARD_SYSTEM_PROMPT,
    generate_plan,
)
from showrunner.plan import Plan
from showrunner.styles.resolver import resolve_style


def _mock_llm():
    llm = MagicMock()
    llm.generate_json.return_value = {
        "title": "Euler's Identity",
        "totalDuration": 45,
        "scenes": [
            {"id": "hook", "duration": 10, "narration": "What if I told you...",
             "visual": "The equation e^{i\\pi} = -1 centered, large", "transition": "fade"},
            {"id": "unit_circle", "duration": 20, "narration": "Picture a circle.",
             "visual": "Unit circle on the left half, rotating arrow", "transition": "fade"},
            {"id": "payoff", "duration": 15, "narration": "And that's why.",
             "visual": "Arrow lands on -1; equation reappears centered", "transition": "fade"},
        ],
    }
    return llm


def test_generate_plan_returns_plan():
    plan = generate_plan("why does e^ipi = -1", style=resolve_style("3b1b-dark"), llm=_mock_llm())
    assert isinstance(plan, Plan)
    assert len(plan.scenes) == 3
    assert plan.scenes[1].id == "unit_circle"


def test_generate_plan_passes_style_context():
    llm = _mock_llm()
    generate_plan("topic", style=resolve_style("3b1b-dark"), llm=llm)
    prompt = llm.generate_json.call_args.kwargs["prompt"]
    assert "3b1b-dark" in prompt
    assert "topic" in prompt


def test_storyboard_prompt_is_spatial_not_code():
    """The planner asks for spatial layout descriptions, never Manim code —
    explicit spatial planning is the documented overlap mitigation."""
    assert "SPATIAL LAYOUT DESCRIPTION" in STORYBOARD_SYSTEM_PROMPT
    assert "Do NOT write Manim code" in STORYBOARD_SYSTEM_PROMPT
    # Spatial vocabulary is demanded
    assert "WHERE" in STORYBOARD_SYSTEM_PROMPT


def test_storyboard_prompt_uses_system_and_user_split():
    llm = _mock_llm()
    generate_plan("topic", style=resolve_style("3b1b-dark"), llm=llm)
    system = llm.generate_json.call_args.kwargs["system"]
    assert system == STORYBOARD_SYSTEM_PROMPT
