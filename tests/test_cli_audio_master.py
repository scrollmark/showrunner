"""Tests for `showrunner audio master` — loudness normalization via ffmpeg."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from showrunner.cli.main import cli


def _run(tmp_path, infile, *extra):
    src = tmp_path / infile
    src.write_bytes(b"x")
    out = tmp_path / f"out{src.suffix}"
    with patch("showrunner.cli.audio_cmds.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
        result = CliRunner().invoke(
            cli, ["audio", "master", str(src), "-o", str(out), *extra]
        )
    return result, run


def test_master_video_copies_video_stream(tmp_path):
    result, run = _run(tmp_path, "in.mp4")
    assert result.exit_code == 0, result.output
    argv = run.call_args.args[0]
    assert argv[0] == "ffmpeg"
    assert "loudnorm=I=-14.0:TP=-1.5:LRA=11" in argv
    assert "copy" in argv and "-c:v" in argv


def test_master_audio_only_skips_video_copy(tmp_path):
    result, run = _run(tmp_path, "in.wav")
    assert result.exit_code == 0, result.output
    argv = run.call_args.args[0]
    assert "-c:v" not in argv


def test_master_custom_target(tmp_path):
    result, run = _run(tmp_path, "in.mp4", "--lufs", "-16", "--true-peak", "-2")
    assert result.exit_code == 0, result.output
    assert "loudnorm=I=-16.0:TP=-2.0:LRA=11" in run.call_args.args[0]


def test_master_ffmpeg_failure_surfaces_stderr(tmp_path):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    with patch("showrunner.cli.audio_cmds.subprocess.run",
               return_value=MagicMock(returncode=1, stdout="", stderr="bad stream")):
        result = CliRunner().invoke(
            cli, ["audio", "master", str(src), "-o", str(tmp_path / "o.mp4")]
        )
    assert result.exit_code != 0
    assert "bad stream" in result.output


def test_master_missing_ffmpeg_friendly_error(tmp_path):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    with patch("showrunner.cli.audio_cmds.subprocess.run",
               side_effect=FileNotFoundError("ffmpeg")):
        result = CliRunner().invoke(
            cli, ["audio", "master", str(src), "-o", str(tmp_path / "o.mp4")]
        )
    assert result.exit_code != 0
    assert "ffmpeg" in result.output
