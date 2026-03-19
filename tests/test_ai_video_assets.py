# tests/test_ai_video_assets.py
from unittest.mock import MagicMock
from pathlib import Path

from showrunner.formats.ai_video.assets import generate_all_clips, generate_all_narrations
from showrunner.plan import Plan, Scene


def test_generate_all_clips():
    mock_video = MagicMock()
    mock_video.generate.return_value = Path("/tmp/clip.mp4")

    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="hook", duration=5, narration="N", visual="Aerial ocean shot"),
            Scene(id="main", duration=5, narration="N", visual="Underwater coral"),
        ],
    )
    clips = generate_all_clips(plan, video=mock_video, output_dir=Path("/tmp/clips"), aspect_ratio="16:9")
    assert len(clips) == 2
    assert mock_video.generate.call_count == 2


def test_generate_all_clips_parallel():
    mock_video = MagicMock()
    mock_video.generate.return_value = Path("/tmp/clip.mp4")

    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="hook", duration=5, narration="N", visual="Shot A"),
            Scene(id="main", duration=5, narration="N", visual="Shot B"),
        ],
    )
    clips = generate_all_clips(plan, video=mock_video, output_dir=Path("/tmp/clips"), aspect_ratio="16:9", parallel=True)
    assert len(clips) == 2


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
    durations = generate_all_narrations(plan, tts=mock_tts, output_dir=Path("/tmp/audio"))
    assert len(durations) == 2
