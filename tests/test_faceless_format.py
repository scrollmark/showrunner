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


def test_compose_with_captions_writes_generated_bundle(tmp_path):
    import json

    fmt = FacelessExplainerFormat()
    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="hook", duration=5, narration="Hello world", visual="V"),
            Scene(id="main", duration=5, narration="More words here", visual="V"),
        ],
    )
    # Pre-seed the work_dir contract files (normally written during assets).
    captions_dir = tmp_path / "captions"
    captions_dir.mkdir()
    (captions_dir / "hook.json").write_text(json.dumps([
        {"text": "Hello", "startMs": 0, "endMs": 300, "timestampMs": 150},
        {"text": "world", "startMs": 300, "endMs": 700, "timestampMs": 500},
    ]))
    (captions_dir / "main.json").write_text(json.dumps([
        {"text": "More", "startMs": 0, "endMs": 250, "timestampMs": 125},
    ]))

    (tmp_path / "src").mkdir()
    assets = {"width": 1080, "height": 1920, "has_audio": True}
    fmt.compose(plan, assets, tmp_path, captions=True)

    generated = tmp_path / "src" / "captions" / "captions.generated.ts"
    assert generated.exists()
    content = generated.read_text()
    assert "export const captionPages" in content
    assert '"Hello"' in content
    # Scene 2 words are offset onto the composition timeline (scene 2
    # starts at 5s minus the transition overlap — i.e. after scene 1's 0ms).
    assert '"More"' in content
    data = json.loads(content.split("captionPages: CaptionPage[] = ")[1].rstrip().rstrip(";"))
    more_page = [p for p in data if p["tokens"][0]["text"] == "More"][0]
    assert more_page["startMs"] > 3000

    root = (tmp_path / "src" / "Root.tsx").read_text()
    assert "CaptionOverlay" in root
    assert 'from "./captions/captions.generated"' in root


def test_compose_with_captions_but_no_json_writes_empty_bundle(tmp_path):
    fmt = FacelessExplainerFormat()
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    (tmp_path / "src").mkdir()
    fmt.compose(plan, {"has_audio": False}, tmp_path, captions=True)
    generated = tmp_path / "src" / "captions" / "captions.generated.ts"
    assert generated.exists()
    assert "captionPages: CaptionPage[] = []" in generated.read_text()
