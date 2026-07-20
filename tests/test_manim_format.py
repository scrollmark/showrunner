# tests/test_manim_format.py
from pathlib import Path
from unittest.mock import MagicMock, patch

from showrunner.feedback import Feedback
from showrunner.formats.base import Format
from showrunner.formats.manim_explainer import ManimExplainerFormat
from showrunner.plan import Plan, Scene
from showrunner.styles.resolver import resolve_style


def test_is_format_subclass():
    assert issubclass(ManimExplainerFormat, Format)


def test_format_metadata():
    fmt = ManimExplainerFormat()
    assert fmt.name == "manim-explainer"
    assert "llm" in fmt.required_providers
    assert "tts" in fmt.required_providers
    assert "render" in fmt.required_providers
    assert "video" not in fmt.required_providers


def test_render_pipeline_wiring():
    fmt = ManimExplainerFormat()
    assert fmt.preferred_render_provider == "ffmpeg"
    assert fmt.requires_video_provider is False


def test_entry_point_declared_in_pyproject():
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    text = pyproject.read_text()
    assert 'manim-explainer = "showrunner.formats.manim_explainer:ManimExplainerFormat"' in text
    # Optional dependency group for the manim toolchain.
    assert 'manim = ["manim>=0.20' in text


def test_plan_delegates_to_planner():
    fmt = ManimExplainerFormat()
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Euler", "totalDuration": 30,
        "scenes": [{"id": "hook", "duration": 10, "narration": "N",
                    "visual": "Equation centered, then a unit circle on the left"}],
    }
    style = resolve_style("3b1b-dark")
    plan = fmt.plan("why does e^ipi = -1", style, None, mock_llm)
    assert isinstance(plan, Plan)
    assert plan.title == "Euler"


def test_compose_writes_concat_and_scene_order(tmp_path):
    fmt = ManimExplainerFormat()
    plan = Plan(
        title="Test", total_duration=20,
        scenes=[
            Scene(id="hook", duration=10, narration="N", visual="V"),
            Scene(id="payoff", duration=10, narration="N", visual="V"),
        ],
    )
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    (clips_dir / "hook.mp4").write_bytes(b"fake")
    (clips_dir / "payoff.mp4").write_bytes(b"fake")

    assets = {"clips": {"hook": clips_dir / "hook.mp4", "payoff": clips_dir / "payoff.mp4"},
              "has_audio": True}
    fmt.compose(plan, assets, tmp_path)

    concat = (tmp_path / "concat.txt").read_text()
    assert "hook.mp4" in concat
    assert "payoff.mp4" in concat
    order = (tmp_path / "scene_order.txt").read_text().splitlines()
    assert order == ["hook", "payoff"]


def test_generate_assets_narrates_then_renders_each_scene(tmp_path):
    fmt = ManimExplainerFormat()
    fmt._style = resolve_style("3b1b-dark")
    plan = Plan(
        title="Test", total_duration=10,
        scenes=[Scene(id="hook", duration=5, narration="Hello", visual="Equation centered")],
    )

    mock_llm = MagicMock()
    mock_llm.generate.return_value = (
        "```python\nfrom manim import *\n\nclass Hook(Scene):\n"
        "    def construct(self):\n        self.wait(5)\n```"
    )
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = MagicMock(duration=4.0)

    with patch("showrunner.formats.manim_explainer.render_scene") as mock_render:
        mock_render.return_value = (True, "")
        assets = fmt.generate_assets(plan, {"llm": mock_llm, "tts": mock_tts}, tmp_path)

    assert assets["has_audio"] is True
    assert "hook" in assets["clips"]
    assert assets["durations"]["hook"] == 4.0
    # Scene source written to disk for the manim CLI
    assert (tmp_path / "scenes" / "hook.py").exists()
    # render_scene invoked with the scene file + class name
    args, kwargs = mock_render.call_args
    assert args[1] == "Hook"
    mock_tts.synthesize.assert_called_once()


def test_generate_assets_extends_scene_duration_to_narration(tmp_path):
    fmt = ManimExplainerFormat()
    fmt._style = resolve_style("3b1b-dark")
    plan = Plan(
        title="Test", total_duration=5,
        scenes=[Scene(id="hook", duration=5, narration="Long narration", visual="V")],
    )

    mock_llm = MagicMock()
    mock_llm.generate.return_value = (
        "```python\nfrom manim import *\n\nclass Hook(Scene):\n"
        "    def construct(self):\n        self.wait(10)\n```"
    )
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = MagicMock(duration=8.5)

    with patch("showrunner.formats.manim_explainer.render_scene") as mock_render:
        mock_render.return_value = (True, "")
        fmt.generate_assets(plan, {"llm": mock_llm, "tts": mock_tts}, tmp_path)

    # 8.5s narration → scene padded to ceil(8.5) + 1 = 10s
    assert plan.scenes[0].duration == 10
    assert plan.total_duration == 10


def test_revise_with_edits():
    fmt = ManimExplainerFormat()
    plan = Plan(title="Old", total_duration=10,
                scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    feedback = Feedback(level="plan", edits={"title": "New"})
    revised = fmt.revise(plan, feedback, MagicMock())
    assert revised.title == "New"


def test_revise_with_text():
    fmt = ManimExplainerFormat()
    plan = Plan(title="Test", total_duration=10,
                scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Revised", "totalDuration": 12,
        "scenes": [{"id": "hook", "duration": 12, "narration": "Better", "visual": "Clearer layout"}],
    }
    feedback = Feedback(level="plan", text="Slow down the equation reveal")
    revised = fmt.revise(plan, feedback, mock_llm)
    assert revised.title == "Revised"
    # The revise prompt keeps the visual field a layout description, not code.
    system = mock_llm.generate_json.call_args.kwargs["system"]
    assert "spatial layout description" in system


def test_revise_no_feedback_returns_plan():
    fmt = ManimExplainerFormat()
    plan = Plan(title="Test", total_duration=10, scenes=[])
    feedback = Feedback(level="plan")
    assert fmt.revise(plan, feedback, MagicMock()) is plan
