"""CLI tests for `showrunner music`. Uses click's CliRunner against an
isolated catalog directory via the SHOWRUNNER_MUSIC_DIR env var."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from showrunner.cli.main import cli


def _silent_wav(path: Path, seconds: float = 1.0, sample_rate: int = 8000) -> None:
    """Write a minimal valid WAV file. Used as a stand-in for real audio so
    `music add` has something to point at without depending on test fixtures."""
    import struct
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    _ = struct  # keep import for lint hygiene


def test_music_where_prints_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWRUNNER_MUSIC_DIR", str(tmp_path))
    result = CliRunner().invoke(cli, ["music", "where"])
    assert result.exit_code == 0
    assert str(tmp_path) in result.output


def test_music_list_empty_catalog(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWRUNNER_MUSIC_DIR", str(tmp_path))
    result = CliRunner().invoke(cli, ["music", "list"])
    assert result.exit_code == 0
    assert "empty" in result.output


def test_music_add_then_list(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWRUNNER_MUSIC_DIR", str(tmp_path))
    audio = tmp_path / "warm-editorial.wav"
    _silent_wav(audio, seconds=0.2)

    result = CliRunner().invoke(cli, [
        "music", "add", str(audio),
        "--mood", "editorial", "--mood", "contemplative",
        "--bpm", "92", "--license", "self-recorded",
    ])
    assert result.exit_code == 0, result.output

    listed = CliRunner().invoke(cli, ["music", "list"])
    assert listed.exit_code == 0
    assert "warm-editorial" in listed.output
    assert "92bpm" in listed.output


def test_music_add_copies_file_into_catalog_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWRUNNER_MUSIC_DIR", str(tmp_path))
    audio = tmp_path / "source" / "elsewhere.wav"
    audio.parent.mkdir()
    _silent_wav(audio)

    result = CliRunner().invoke(cli, ["music", "add", str(audio), "--bpm", "100"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "tracks" / "elsewhere.wav").exists()


def test_music_add_no_copy_leaves_file_in_place(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWRUNNER_MUSIC_DIR", str(tmp_path))
    audio = tmp_path / "source" / "somewhere-else.wav"
    audio.parent.mkdir()
    _silent_wav(audio)

    result = CliRunner().invoke(cli, ["music", "add", str(audio), "--no-copy", "--bpm", "100"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "tracks" / "somewhere-else.wav").exists()
    assert audio.exists()


def test_music_inspect_and_remove(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWRUNNER_MUSIC_DIR", str(tmp_path))
    audio = tmp_path / "track.wav"
    _silent_wav(audio)

    CliRunner().invoke(cli, ["music", "add", str(audio), "--bpm", "120", "--mood", "uplifting"])

    inspected = CliRunner().invoke(cli, ["music", "inspect", "track"])
    assert inspected.exit_code == 0
    assert "uplifting" in inspected.output
    assert "120" in inspected.output

    removed = CliRunner().invoke(cli, ["music", "remove", "track"])
    assert removed.exit_code == 0
    assert "removed" in removed.output

    # Catalog should now list empty again.
    listed = CliRunner().invoke(cli, ["music", "list"])
    assert "empty" in listed.output


def test_music_inspect_missing_id(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWRUNNER_MUSIC_DIR", str(tmp_path))
    result = CliRunner().invoke(cli, ["music", "inspect", "nope"])
    assert result.exit_code != 0
    assert "no track" in result.output
