# tests/test_composite_format.py
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from showrunner.feedback import Feedback
from showrunner.formats.base import Format
from showrunner.formats.composite import CompositeFormat
from showrunner.plan import Plan, Scene


def test_is_format_subclass():
    assert issubclass(CompositeFormat, Format)


def test_format_metadata():
    fmt = CompositeFormat()
    assert fmt.name == "composite"
    assert fmt.preferred_render_provider == "ffmpeg"
    assert fmt.requires_video_provider is True
    assert "video" in fmt.required_providers
    assert "tts" in fmt.required_providers


def test_plan_raises_not_implemented_with_actionable_message():
    fmt = CompositeFormat()
    with pytest.raises(NotImplementedError, match="--storyboard"):
        fmt.plan("anything", None, None, MagicMock())


# --- generate_assets: overlay mode --------------------------------------------


def _overlay_plan():
    return Plan(
        title="Reaction", total_duration=5,
        scenes=[
            Scene(
                id="react", duration=5, narration="Wow", visual="unused",
                layers=[
                    {"id": "base", "role": "base", "source": "a news article rendered as a static frame"},
                    {"id": "speaker", "role": "chromakey", "source": "a person reacting on green screen", "rect": [0.5, 0.5, 0.5, 0.5]},
                ],
            ),
        ],
    )


def test_generate_assets_overlay_mode_generates_each_layer(tmp_path, monkeypatch):
    composite_calls = []
    monkeypatch.setattr(
        "showrunner.formats.composite.composite_scene",
        lambda paths, specs, **kw: composite_calls.append((paths, specs, kw)) or kw["output_path"],
    )
    fmt = CompositeFormat()
    fmt._aspect_ratio = "16:9"

    mock_video = MagicMock()

    def fake_generate(prompt, *, duration, aspect_ratio, output_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake")
        return output_path

    mock_video.generate.side_effect = fake_generate
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = MagicMock(duration=2.0, path=Path("/tmp/a.wav"))

    assets = fmt.generate_assets(_overlay_plan(), {"video": mock_video, "tts": mock_tts}, tmp_path)

    assert mock_video.generate.call_count == 2
    prompts = [call.args[0] for call in mock_video.generate.call_args_list]
    assert "news article" in prompts[0]
    assert "green screen" in prompts[1]

    (paths, specs, kw) = composite_calls[0]
    assert len(paths) == 2
    assert specs[0]["role"] == "base"
    assert specs[1]["role"] == "chromakey"
    assert kw["width"] == 1920 and kw["height"] == 1080
    assert kw["duration"] == 5

    assert assets["has_audio"] is True
    assert "react" in assets["clips"]
    mock_tts.synthesize.assert_called_once()


def test_generate_assets_ingests_local_asset_layer(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "showrunner.formats.composite.composite_scene",
        lambda paths, specs, **kw: kw["output_path"],
    )
    source = tmp_path / "gameplay.mp4"
    source.write_bytes(b"real gameplay footage")

    plan = Plan(
        title="Reddit", total_duration=8,
        scenes=[
            Scene(
                id="thread", duration=8, narration="Read this", visual="unused",
                layers=[
                    {"id": "base", "role": "base", "source": f"file://{source}"},
                    {"id": "card", "role": "image", "source": "a static reddit thread card"},
                ],
            ),
        ],
    )
    fmt = CompositeFormat()
    fmt._aspect_ratio = "9:16"
    mock_video = MagicMock()

    def fake_generate(prompt, *, duration, aspect_ratio, output_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"card image")
        return output_path

    mock_video.generate.side_effect = fake_generate
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = MagicMock(duration=2.0, path=Path("/tmp/a.wav"))

    fmt.generate_assets(plan, {"video": mock_video, "tts": mock_tts}, tmp_path)

    # Only the "card" layer (a prompt) calls the video provider — the base
    # (file:// asset) is ingested directly, not generated.
    mock_video.generate.assert_called_once()
    assert "reddit thread" in mock_video.generate.call_args.args[0]

    base_layer_path = tmp_path / "layers" / "thread-base.mp4"
    assert base_layer_path.read_bytes() == b"real gameplay footage"


def test_generate_assets_stack_mode(tmp_path, monkeypatch):
    composite_calls = []
    monkeypatch.setattr(
        "showrunner.formats.composite.composite_scene",
        lambda paths, specs, **kw: composite_calls.append(specs) or kw["output_path"],
    )
    plan = Plan(
        title="Duet", total_duration=6,
        scenes=[
            Scene(
                id="duet", duration=6, narration="", visual="unused",
                layers=[
                    {"id": "left", "role": "hstack", "source": "a dancer", "label": "@og"},
                    {"id": "right", "role": "hstack", "source": "a reactor", "label": "@duet"},
                ],
            ),
        ],
    )
    fmt = CompositeFormat()
    fmt._aspect_ratio = "9:16"
    fmt._no_audio = True
    mock_video = MagicMock()

    def fake_generate(prompt, *, duration, aspect_ratio, output_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake")
        return output_path

    mock_video.generate.side_effect = fake_generate

    assets = fmt.generate_assets(plan, {"video": mock_video, "tts": MagicMock()}, tmp_path)

    assert composite_calls[0][0]["role"] == "hstack"
    assert composite_calls[0][1]["role"] == "hstack"
    assert assets["has_audio"] is False
    assert assets["durations"] == {}


def test_generate_assets_requires_layers_on_every_scene(tmp_path):
    plan = Plan(
        title="Bad", total_duration=5,
        scenes=[Scene(id="oops", duration=5, narration="N", visual="V")],  # no layers
    )
    fmt = CompositeFormat()
    with pytest.raises(ValueError, match="no `layers`"):
        fmt.generate_assets(plan, {"video": MagicMock(), "tts": MagicMock()}, tmp_path)


# --- compose: delegates to ai-video --------------------------------------------


def test_compose_delegates_to_ai_video(tmp_path, monkeypatch):
    fmt = CompositeFormat()
    fmt._aspect_ratio = "9:16"
    plan = Plan(
        title="Test", total_duration=5,
        scenes=[Scene(id="hook", duration=5, narration="N", visual="V", layers=[{"id": "base", "role": "base", "source": "x"}])],
    )
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    (clips_dir / "hook.mp4").write_bytes(b"fake")

    monkeypatch.setattr(
        "showrunner.formats.ai_video.assets.normalize_clips",
        lambda plan, clips, **kw: clips,
    )
    assets = {"clips": {"hook": clips_dir / "hook.mp4"}, "has_audio": True}
    fmt.compose(plan, assets, tmp_path)

    assert (tmp_path / "concat.txt").exists()
    assert (tmp_path / "scene_order.txt").exists()
    assert "hook.mp4" in (tmp_path / "concat.txt").read_text()


# --- revise --------------------------------------------------------------------


def test_revise_with_edits_dict():
    fmt = CompositeFormat()
    plan = Plan(title="Test", total_duration=5, scenes=[
        Scene(id="hook", duration=5, narration="N", visual="V", layers=[{"id": "base", "role": "base", "source": "x"}]),
    ])
    feedback = Feedback(level="plan", edits={"title": "New Title"})
    revised = fmt.revise(plan, feedback, MagicMock())
    assert revised.title == "New Title"


def test_revise_with_text_calls_llm():
    fmt = CompositeFormat()
    plan = Plan(title="Test", total_duration=5, scenes=[
        Scene(id="hook", duration=5, narration="N", visual="V", layers=[{"id": "base", "role": "base", "source": "x"}]),
    ])
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Revised", "totalDuration": 5,
        "scenes": [{"id": "hook", "duration": 5, "narration": "N2", "visual": "V", "layers": [{"id": "base", "role": "base", "source": "x2"}]}],
    }
    feedback = Feedback(level="plan", text="Make it punchier")
    revised = fmt.revise(plan, feedback, mock_llm)
    assert revised.title == "Revised"
    assert revised.scenes[0].layers[0]["source"] == "x2"
    # System prompt should actually describe the layers schema, not a generic one.
    assert "layers" in mock_llm.generate_json.call_args.kwargs["system"]


def test_revise_without_feedback_returns_plan_unchanged():
    fmt = CompositeFormat()
    plan = Plan(title="Test", total_duration=5, scenes=[])
    feedback = Feedback(level="plan")
    assert fmt.revise(plan, feedback, MagicMock()) is plan
