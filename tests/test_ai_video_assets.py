# tests/test_ai_video_assets.py
from unittest.mock import MagicMock
from pathlib import Path

import pytest

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


# --- E3: local-asset ingestion (`file://` scenes) ----------------------------


def test_generate_all_clips_ingests_local_asset_instead_of_generating(tmp_path):
    source = tmp_path / "supplied.mp4"
    source.write_bytes(b"fake mp4 bytes")
    mock_video = MagicMock()

    plan = Plan(
        title="Test", total_duration=5,
        scenes=[Scene(id="intro", duration=5, narration="N", visual=f"file://{source}")],
    )
    clips = generate_all_clips(plan, video=mock_video, output_dir=tmp_path / "clips", aspect_ratio="16:9")

    assert clips["intro"] == tmp_path / "clips" / "intro.mp4"
    assert clips["intro"].read_bytes() == b"fake mp4 bytes"
    mock_video.generate.assert_not_called()


def test_generate_all_clips_mixes_generated_and_local_scenes(tmp_path):
    source = tmp_path / "supplied.mp4"
    source.write_bytes(b"fake mp4 bytes")
    mock_video = MagicMock()
    mock_video.generate.return_value = Path("/tmp/clip.mp4")

    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="supplied", duration=5, narration="N", visual=f"file://{source}"),
            Scene(id="generated", duration=5, narration="N", visual="Aerial ocean shot"),
        ],
    )
    clips = generate_all_clips(plan, video=mock_video, output_dir=tmp_path / "clips", aspect_ratio="16:9")

    assert clips["supplied"].read_bytes() == b"fake mp4 bytes"
    mock_video.generate.assert_called_once()
    assert mock_video.generate.call_args.args[0] == "Aerial ocean shot"


def test_generate_all_clips_local_asset_relative_path_resolves_against_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake mp4 bytes")
    mock_video = MagicMock()

    plan = Plan(
        title="Test", total_duration=5,
        scenes=[Scene(id="intro", duration=5, narration="N", visual="file://clip.mp4")],
    )
    clips = generate_all_clips(plan, video=mock_video, output_dir=tmp_path / "clips", aspect_ratio="16:9")
    assert clips["intro"].read_bytes() == b"fake mp4 bytes"


def test_generate_all_clips_missing_local_asset_raises_clear_error(tmp_path):
    mock_video = MagicMock()
    plan = Plan(
        title="Test", total_duration=5,
        scenes=[Scene(id="intro", duration=5, narration="N", visual="file:///no/such/file.mp4")],
    )
    with pytest.raises(FileNotFoundError, match="no/such/file.mp4"):
        generate_all_clips(plan, video=mock_video, output_dir=tmp_path / "clips", aspect_ratio="16:9")


def test_generate_all_clips_parallel_ingests_local_asset(tmp_path):
    source = tmp_path / "supplied.mp4"
    source.write_bytes(b"fake mp4 bytes")
    mock_video = MagicMock()

    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="supplied", duration=5, narration="N", visual=f"file://{source}"),
            Scene(id="generated", duration=5, narration="N", visual="Shot B"),
        ],
    )
    clips = generate_all_clips(
        plan, video=mock_video, output_dir=tmp_path / "clips", aspect_ratio="16:9", parallel=True,
    )
    assert clips["supplied"].read_bytes() == b"fake mp4 bytes"
    mock_video.generate.assert_called_once()


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


def test_generate_all_narrations_uses_per_scene_voice_override():
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = MagicMock(duration=3.5, path=Path("/tmp/test.wav"))

    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="a", duration=5, narration="Hi", visual="V", voice="am_adam"),
            Scene(id="b", duration=5, narration="Hey", visual="V"),
        ],
    )
    generate_all_narrations(plan, tts=mock_tts, output_dir=Path("/tmp/audio"), voice="af_heart")

    voices_used = [call.kwargs["voice"] for call in mock_tts.synthesize.call_args_list]
    assert voices_used == ["am_adam", "af_heart"]


# --- normalize_clips ---------------------------------------------------------


def _norm_plan():
    from showrunner.plan import Plan, Scene

    return Plan(
        title="t",
        total_duration=10,
        scenes=[
            Scene(id="a", duration=5, narration="n", visual="v"),
            Scene(id="b", duration=5, narration="n", visual="v"),
        ],
    )


def test_normalize_clips_trims_crops_and_strips_audio(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from showrunner.formats.ai_video import assets as mod

    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    raw_a = clips_dir / "a.mp4"
    raw_a.write_bytes(b"raw")

    calls = []

    def fake_run(cmd, capture_output, text):
        calls.append(cmd)
        # ffmpeg would write the output file; emulate that.
        Path(cmd[-1]).write_bytes(b"norm")
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = mod.normalize_clips(
        _norm_plan(), {"a": raw_a}, work_dir=tmp_path, aspect_ratio="9:16"
    )

    assert set(result) == {"a"}  # scene b has no clip — skipped, not an error
    assert result["a"] == tmp_path / "clips_norm" / "a.mp4"
    (cmd,) = calls
    # Trimmed to the storyboard duration (Hailuo clips come back 6s).
    assert cmd[cmd.index("-t") + 1] == "5"
    # Cover-cropped to the 9:16 canvas at constant fps.
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in vf
    assert "crop=1080:1920" in vf
    assert "fps=30" in vf
    # Narration is the audio track — clip audio is stripped by default.
    assert "-an" in cmd


def test_normalize_clips_is_idempotent_and_keep_audio(tmp_path, monkeypatch):
    import time
    from unittest.mock import MagicMock

    from showrunner.formats.ai_video import assets as mod

    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    raw_a = clips_dir / "a.mp4"
    raw_a.write_bytes(b"raw")

    norm_dir = tmp_path / "clips_norm"
    norm_dir.mkdir()
    done = norm_dir / "a.mp4"
    done.write_bytes(b"norm")
    # Ensure the normalized copy is NEWER than the source.
    later = time.time() + 60
    import os

    os.utime(done, (later, later))

    calls = []
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **kw: calls.append(a) or MagicMock(returncode=0, stderr="")
    )

    result = mod.normalize_clips(_norm_plan(), {"a": raw_a}, work_dir=tmp_path)
    assert result["a"] == done
    assert calls == []  # newer normalized clip reused, no re-encode

    # keep_audio=True omits -an (native-audio path, e.g. Veo ASMR).
    raw_b = clips_dir / "b.mp4"
    raw_b.write_bytes(b"raw")
    cmds = []

    def fake_run(cmd, capture_output, text):
        cmds.append(cmd)
        Path(cmd[-1]).write_bytes(b"norm")
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    mod.normalize_clips(_norm_plan(), {"b": raw_b}, work_dir=tmp_path, keep_audio=True)
    (cmd,) = cmds
    assert "-an" not in cmd
