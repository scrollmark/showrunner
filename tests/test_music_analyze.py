"""Tests for `showrunner music analyze` — BPM + beat-grid estimation."""

import json

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

from click.testing import CliRunner  # noqa: E402

from showrunner.cli.main import cli  # noqa: E402
from showrunner.music.analyze import analyze_track  # noqa: E402


def _click_track(path, bpm=120.0, seconds=10.0, sr=22050):
    """Synthesize a click every beat: 15ms 1kHz bursts on silence."""
    n = int(seconds * sr)
    signal = np.zeros(n, dtype=np.float32)
    interval = 60.0 / bpm
    t_click = np.arange(int(0.015 * sr)) / sr
    burst = (np.sin(2 * np.pi * 1000 * t_click) * np.hanning(len(t_click))).astype(np.float32)
    pos = 0.0
    while pos < seconds:
        start = int(pos * sr)
        end = min(start + len(burst), n)
        signal[start:end] += burst[: end - start]
        pos += interval
    sf.write(str(path), signal, sr)
    return path


def test_analyze_click_track_bpm(tmp_path):
    wav = _click_track(tmp_path / "click.wav", bpm=120.0)
    result = analyze_track(wav)
    assert abs(result["bpm"] - 120.0) <= 3.0
    assert abs(result["beat_interval"] - 0.5) <= 0.02
    assert result["beats"], "expected a non-empty beat grid"
    assert result["beats"][0] < 0.5  # first beat lands near the start
    assert 9.0 <= result["duration"] <= 11.0


def test_analyze_slow_click_track(tmp_path):
    wav = _click_track(tmp_path / "slow.wav", bpm=90.0)
    result = analyze_track(wav)
    assert abs(result["bpm"] - 90.0) <= 3.0


def test_analyze_missing_deps_message(tmp_path, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("numpy", "soundfile", "librosa"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match=r"showrunner\[audio\]"):
        analyze_track(tmp_path / "x.wav")


def test_cli_music_analyze_json(tmp_path):
    wav = _click_track(tmp_path / "click.wav", bpm=120.0)
    result = CliRunner().invoke(cli, ["music", "analyze", str(wav), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert abs(payload["bpm"] - 120.0) <= 3.0
