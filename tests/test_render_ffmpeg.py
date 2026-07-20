# tests/test_render_ffmpeg.py
from unittest.mock import patch, MagicMock
from pathlib import Path

from showrunner.providers.render.ffmpeg import FFmpegRenderProvider
from showrunner.providers.render.base import RenderProvider


def test_ffmpeg_is_render_provider():
    assert issubclass(FFmpegRenderProvider, RenderProvider)


def test_setup_creates_directories(tmp_path):
    provider = FFmpegRenderProvider()
    work_dir = tmp_path / "work"
    provider.setup(work_dir)
    assert (work_dir / "clips").is_dir()
    assert (work_dir / "audio").is_dir()


def test_build_concat_file(tmp_path):
    provider = FFmpegRenderProvider()
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    clips_dir = work_dir / "clips"
    clips_dir.mkdir()

    # Create fake clip files
    (clips_dir / "hook.mp4").write_bytes(b"fake")
    (clips_dir / "main.mp4").write_bytes(b"fake")

    scene_order = ["hook", "main"]
    concat_path = provider._build_concat_file(work_dir, scene_order)
    assert concat_path.exists()
    content = concat_path.read_text()
    assert "hook.mp4" in content
    assert "main.mp4" in content


@patch("showrunner.providers.render.ffmpeg.subprocess")
def test_render_calls_ffmpeg(mock_subprocess, tmp_path):
    mock_subprocess.run.return_value = MagicMock(returncode=0)
    provider = FFmpegRenderProvider()

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "clips").mkdir()
    (work_dir / "audio").mkdir()
    (work_dir / "concat.txt").write_text("file 'clips/hook.mp4'\n")
    (work_dir / "scene_order.txt").write_text("hook\n")

    # Create the intermediate file that ffmpeg would produce (mocked)
    (work_dir / "_concat.mp4").write_bytes(b"fake")

    output = tmp_path / "out.mp4"
    result = provider.render(work_dir=work_dir, output_path=output)
    assert result == output
    assert mock_subprocess.run.called


@patch("showrunner.providers.render.ffmpeg.subprocess")
def test_render_raises_on_failure(mock_subprocess, tmp_path):
    mock_subprocess.run.return_value = MagicMock(returncode=1, stderr="Error")
    provider = FFmpegRenderProvider()

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "concat.txt").write_text("file 'clips/hook.mp4'\n")
    (work_dir / "scene_order.txt").write_text("hook\n")

    import pytest
    with pytest.raises(RuntimeError, match="FFmpeg"):
        provider.render(work_dir=work_dir, output_path=tmp_path / "out.mp4")


@patch("showrunner.providers.render.ffmpeg.subprocess")
def test_render_burns_captions_when_ass_present(mock_subprocess, tmp_path):
    mock_subprocess.run.return_value = MagicMock(returncode=0)
    provider = FFmpegRenderProvider()

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "audio").mkdir()
    (work_dir / "concat.txt").write_text("file 'clips/hook.mp4'\n")
    (work_dir / "scene_order.txt").write_text("hook\n")
    (work_dir / "audio" / "hook.wav").write_bytes(b"fake")
    (work_dir / "captions.ass").write_text("[Script Info]\n")

    provider.render(work_dir=work_dir, output_path=tmp_path / "out.mp4")

    final_cmd = mock_subprocess.run.call_args_list[-1][0][0]
    vf_index = final_cmd.index("-vf")
    assert final_cmd[vf_index + 1].startswith("ass=")
    assert "captions.ass" in final_cmd[vf_index + 1]
    # Burning subtitles requires re-encoding — no stream copy.
    assert "libx264" in final_cmd
    assert ["-c:v", "copy"] != final_cmd[final_cmd.index("-c:v"):final_cmd.index("-c:v") + 2]


@patch("showrunner.providers.render.ffmpeg.subprocess")
def test_render_no_ass_keeps_stream_copy(mock_subprocess, tmp_path):
    mock_subprocess.run.return_value = MagicMock(returncode=0)
    provider = FFmpegRenderProvider()

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "audio").mkdir()
    (work_dir / "concat.txt").write_text("file 'clips/hook.mp4'\n")
    (work_dir / "scene_order.txt").write_text("hook\n")
    (work_dir / "audio" / "hook.wav").write_bytes(b"fake")

    provider.render(work_dir=work_dir, output_path=tmp_path / "out.mp4")

    final_cmd = mock_subprocess.run.call_args_list[-1][0][0]
    assert "-vf" not in final_cmd
    assert "copy" in final_cmd


@patch("showrunner.providers.render.ffmpeg.subprocess")
def test_render_burns_captions_without_audio(mock_subprocess, tmp_path):
    mock_subprocess.run.return_value = MagicMock(returncode=0)
    provider = FFmpegRenderProvider()

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "concat.txt").write_text("file 'clips/hook.mp4'\n")
    (work_dir / "captions.ass").write_text("[Script Info]\n")

    provider.render(work_dir=work_dir, output_path=tmp_path / "out.mp4")

    final_cmd = mock_subprocess.run.call_args_list[-1][0][0]
    assert "-vf" in final_cmd
    assert "libx264" in final_cmd
