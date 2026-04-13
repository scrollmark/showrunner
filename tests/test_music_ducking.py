"""Tests for the narration-driven music ducking envelope."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from showrunner.music.ducking import (
    DuckingConfig,
    compute_envelope,
    write_envelope_ts,
)


def _write_wav(
    path: Path, *, seconds: float, amplitude: float, sample_rate: int = 16000
) -> None:
    """Write a constant-amplitude square-ish tone WAV so each window has
    a known RMS value regardless of where we sample it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * sample_rate)
    value = int(amplitude * 32767)
    frames = struct.pack("<" + "h" * n, *([value] * n))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(frames)


def test_envelope_length_matches_total_frames(tmp_path):
    audio = tmp_path / "scene.wav"
    _write_wav(audio, seconds=1.0, amplitude=0.5)
    env = compute_envelope(
        narration_specs=[{"path": audio, "start_frame": 0}],
        total_frames=60,
        fps=30,
    )
    assert len(env) == 60


def test_envelope_ducks_during_narration(tmp_path):
    # Narration runs frames 30..60; frames 0..29 have no narration and
    # should sit at base volume; frames 30..60 should be lower.
    audio = tmp_path / "loud.wav"
    _write_wav(audio, seconds=1.0, amplitude=0.9)
    env = compute_envelope(
        narration_specs=[{"path": audio, "start_frame": 30}],
        total_frames=120,
        fps=30,
        config=DuckingConfig(base_volume=0.2, depth=0.6, attack_frames=1, release_frames=1),
    )
    pre = env[5]      # no narration yet
    during = env[45]  # deep in narration
    assert pre > during
    assert math.isclose(pre, 0.2, abs_tol=0.05)
    # Duck depth of 0.6 × base 0.2 → ~0.08 at max narration amplitude.
    assert during < 0.15


def test_envelope_recovers_after_narration_ends(tmp_path):
    audio = tmp_path / "brief.wav"
    _write_wav(audio, seconds=0.5, amplitude=0.9)  # 15 frames at 30fps
    env = compute_envelope(
        narration_specs=[{"path": audio, "start_frame": 0}],
        total_frames=60,
        fps=30,
        config=DuckingConfig(base_volume=0.2, depth=0.6, attack_frames=1, release_frames=1),
    )
    # Past the narration + release window, envelope should be back near base.
    assert env[50] > env[5]
    assert math.isclose(env[50], 0.2, abs_tol=0.02)


def test_envelope_handles_missing_narration_file(tmp_path):
    # Spec references a file that doesn't exist; pipeline should not crash
    # and should just fall back to base volume everywhere.
    env = compute_envelope(
        narration_specs=[{"path": tmp_path / "nope.wav", "start_frame": 0}],
        total_frames=30,
        fps=30,
        config=DuckingConfig(base_volume=0.2),
    )
    assert len(env) == 30
    assert all(math.isclose(v, 0.2, abs_tol=1e-6) for v in env)


def test_write_envelope_ts_roundtrip(tmp_path):
    env = [0.2, 0.18, 0.1, 0.12, 0.2]
    target = tmp_path / "env.generated.ts"
    write_envelope_ts(env, target=target, base_volume=0.2)
    body = target.read_text()
    assert "BASE_VOLUME = 0.2" in body
    assert "export const envelope" in body
    assert "0.1000" in body  # some precision preserved


def test_quieter_narration_ducks_less(tmp_path):
    loud = tmp_path / "loud.wav"
    quiet = tmp_path / "quiet.wav"
    _write_wav(loud, seconds=1.0, amplitude=0.9)
    _write_wav(quiet, seconds=1.0, amplitude=0.1)

    env_loud = compute_envelope(
        narration_specs=[{"path": loud, "start_frame": 0}],
        total_frames=40, fps=30,
        config=DuckingConfig(base_volume=0.2, depth=0.6, attack_frames=1, release_frames=1),
    )
    env_quiet = compute_envelope(
        narration_specs=[{"path": quiet, "start_frame": 0}],
        total_frames=40, fps=30,
        config=DuckingConfig(base_volume=0.2, depth=0.6, attack_frames=1, release_frames=1),
    )
    # With normalization, both envelopes dip to similar floors on their own.
    # But if we mix them in a single timeline, the quiet file shouldn't
    # push a second music layer as low as the loud one would.
    combined = compute_envelope(
        narration_specs=[
            {"path": loud, "start_frame": 0},
            {"path": quiet, "start_frame": 40},
        ],
        total_frames=80, fps=30,
        config=DuckingConfig(base_volume=0.2, depth=0.6, attack_frames=1, release_frames=1),
    )
    # Peak is now set by the loud file, so quiet narration ducks far less.
    loud_dip = min(combined[:40])
    quiet_dip = min(combined[40:])
    assert quiet_dip > loud_dip
