from unittest.mock import MagicMock
from showrunner.formats.faceless_explainer import FacelessExplainerFormat
from showrunner.formats.base import Format
from showrunner.feedback import Feedback
from showrunner.plan import Plan, Scene


def test_is_format_subclass():
    assert issubclass(FacelessExplainerFormat, Format)


def test_format_metadata():
    fmt = FacelessExplainerFormat()
    assert fmt.name == "faceless-explainer"
    assert "llm" in fmt.required_providers
    assert "tts" in fmt.required_providers
    assert "render" in fmt.required_providers


def test_plan_delegates_to_planner():
    fmt = FacelessExplainerFormat()
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Test", "totalDuration": 10,
        "scenes": [{"id": "hook", "duration": 10, "narration": "N", "visual": "V"}],
    }
    from showrunner.styles.resolver import resolve_style
    style = resolve_style("3b1b-dark")
    plan = fmt.plan("test topic", style, None, mock_llm)
    assert isinstance(plan, Plan)
    assert plan.title == "Test"


def test_compose_writes_root_tsx(tmp_path):
    fmt = FacelessExplainerFormat()
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    assets = {"width": 1080, "height": 1920, "has_audio": False}
    (tmp_path / "src").mkdir()
    fmt.compose(plan, assets, tmp_path)
    assert (tmp_path / "src" / "Root.tsx").exists()
    content = (tmp_path / "src" / "Root.tsx").read_text()
    assert "Hook" in content


def test_revise_with_text_feedback():
    fmt = FacelessExplainerFormat()
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Revised", "totalDuration": 15,
        "scenes": [{"id": "hook", "duration": 15, "narration": "Better hook", "visual": "V"}],
    }
    feedback = Feedback(level="plan", text="Make it longer")
    revised = fmt.revise(plan, feedback, mock_llm)
    assert revised.title == "Revised"


def test_revise_with_edits():
    fmt = FacelessExplainerFormat()
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    feedback = Feedback(level="plan", edits={"title": "Edited Title"})
    revised = fmt.revise(plan, feedback, MagicMock())
    assert revised.title == "Edited Title"


def test_revise_no_feedback_returns_same():
    fmt = FacelessExplainerFormat()
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    feedback = Feedback(level="plan")
    revised = fmt.revise(plan, feedback, MagicMock())
    assert revised.title == "Test"
