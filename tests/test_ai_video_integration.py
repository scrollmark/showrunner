# tests/test_ai_video_integration.py
"""Integration test for AI video format with mocked providers."""

from unittest.mock import MagicMock, patch
from pathlib import Path

from showrunner.formats.ai_video import AIVideoFormat
from showrunner.plan import Plan, Scene
from showrunner.styles.resolver import resolve_style


def test_ai_video_full_flow(tmp_path):
    """Test complete format flow: plan → assets → compose."""
    fmt = AIVideoFormat()
    fmt._style = resolve_style("dramatic-story")
    fmt._aspect_ratio = "16:9"
    fmt._voice = "af_heart"
    fmt._speed = 1.0
    fmt._parallel = False

    # Mock providers
    mock_llm = MagicMock()
    mock_video = MagicMock()
    mock_tts = MagicMock()

    # Plan
    mock_llm.generate_json.return_value = {
        "title": "Ocean Wonders",
        "totalDuration": 15,
        "scenes": [
            {"id": "hook", "duration": 5, "narration": "The ocean hides secrets.", "visual": "Aerial shot of ocean waves, golden hour"},
            {"id": "deep", "duration": 5, "narration": "Miles below the surface...", "visual": "Underwater shot, bioluminescent creatures"},
            {"id": "cta", "duration": 5, "narration": "Follow for more.", "visual": "Sunset over calm ocean, drone shot pulling back"},
        ],
    }
    plan = fmt.plan("Ocean mysteries", fmt._style, None, mock_llm)
    assert len(plan.scenes) == 3

    # Assets — mock video.generate to create the fake clip file at output_path
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()

    def fake_generate(prompt, *, duration, aspect_ratio, output_path):
        Path(output_path).write_bytes(b"fake_video")
        return output_path

    mock_video.generate.side_effect = fake_generate
    mock_tts.synthesize.return_value = MagicMock(duration=4.0, path=Path("/tmp/audio.wav"))

    providers = {"llm": mock_llm, "video": mock_video, "tts": mock_tts}
    assets = fmt.generate_assets(plan, providers, tmp_path)
    assert "clips" in assets
    assert mock_video.generate.call_count == 3
    assert mock_tts.synthesize.call_count == 3

    # Compose
    fmt.compose(plan, assets, tmp_path)
    assert (tmp_path / "concat.txt").exists()
    assert (tmp_path / "scene_order.txt").exists()

    concat_content = (tmp_path / "concat.txt").read_text()
    assert "hook.mp4" in concat_content
    assert "deep.mp4" in concat_content
    assert "cta.mp4" in concat_content

    scene_order = (tmp_path / "scene_order.txt").read_text().strip().split("\n")
    assert scene_order == ["hook", "deep", "cta"]
