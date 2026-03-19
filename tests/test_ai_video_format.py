# tests/test_ai_video_format.py
from unittest.mock import MagicMock
from pathlib import Path

from showrunner.formats.ai_video import AIVideoFormat
from showrunner.formats.base import Format
from showrunner.feedback import Feedback
from showrunner.plan import Plan, Scene
from showrunner.styles.resolver import resolve_style


def test_is_format_subclass():
    assert issubclass(AIVideoFormat, Format)


def test_format_metadata():
    fmt = AIVideoFormat()
    assert fmt.name == "ai-video"
    assert "video" in fmt.required_providers
    assert "llm" in fmt.required_providers
    assert "tts" in fmt.required_providers
    assert "render" in fmt.required_providers


def test_plan_delegates_to_planner():
    fmt = AIVideoFormat()
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Test", "totalDuration": 10,
        "scenes": [{"id": "hook", "duration": 5, "narration": "N", "visual": "Aerial shot"}],
    }
    style = resolve_style("dramatic-story")
    plan = fmt.plan("test", style, None, mock_llm)
    assert isinstance(plan, Plan)


def test_compose_writes_concat_and_scene_order(tmp_path):
    fmt = AIVideoFormat()
    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="hook", duration=5, narration="N", visual="V"),
            Scene(id="main", duration=5, narration="N", visual="V"),
        ],
    )
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    (clips_dir / "hook.mp4").write_bytes(b"fake")
    (clips_dir / "main.mp4").write_bytes(b"fake")

    assets = {"clips": {"hook": clips_dir / "hook.mp4", "main": clips_dir / "main.mp4"}, "has_audio": True}
    fmt.compose(plan, assets, tmp_path)

    assert (tmp_path / "concat.txt").exists()
    assert (tmp_path / "scene_order.txt").exists()
    content = (tmp_path / "concat.txt").read_text()
    assert "hook.mp4" in content
    assert "main.mp4" in content


def test_revise_with_text():
    fmt = AIVideoFormat()
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=5, narration="N", visual="V")])
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Revised", "totalDuration": 15,
        "scenes": [{"id": "hook", "duration": 5, "narration": "Better", "visual": "Better shot"}],
    }
    feedback = Feedback(level="plan", text="Make visuals more dramatic")
    revised = fmt.revise(plan, feedback, mock_llm)
    assert revised.title == "Revised"
