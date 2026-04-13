"""Narration-driven music ducking.

Produces a per-frame gain envelope for the music bed so it sits low under
speech and swells back up during silence. We do the DSP in Python once at
compose time rather than in Remotion at render time; a simple array
lookup in the `<Audio>` component's `volume` callback is much cheaper
than running an RMS analyzer on every frame.

The algorithm:

1. Walk every narration WAV, computing root-mean-square (RMS) energy in
   one-frame-wide windows.
2. Normalize RMS to [0, 1] across the loudest moment of ALL narrations
   (not per-file), so consistently-quiet TTS doesn't get spuriously
   boosted.
3. Convert RMS → duck gain with a configurable depth: silence maps to
   full music volume, peak narration maps to `(1 - depth) × base`.
4. Smooth the resulting envelope with a short attack/release so the music
   doesn't pump on every phoneme.

The output is a float array, one value per video frame, that the
Remotion composition imports and samples in its `<Audio volume>` prop.
"""

from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DuckingConfig:
    """Tuning knobs exposed to the pipeline. Defaults are musical —
    narration pushes the bed down ~65%, with a ~6-frame attack and
    ~15-frame release for a natural ride."""
    base_volume: float = 0.2        # volume with no narration active
    depth: float = 0.65              # fraction to duck under loudest narration
    attack_frames: int = 6           # how fast the bed dips
    release_frames: int = 15         # how fast the bed recovers
    analysis_window_seconds: float = 0.033  # ~1 frame at 30fps


def compute_envelope(
    *,
    narration_specs: list[dict],
    total_frames: int,
    fps: int,
    config: DuckingConfig | None = None,
) -> list[float]:
    """Return a `total_frames`-long list of per-frame music volumes.

    `narration_specs` is `[{path: Path, start_frame: int}, ...]`, one
    entry per scene's narration WAV. Entries may extend past the scene's
    own duration — the envelope simply extends through the audio's
    actual length.
    """
    cfg = config or DuckingConfig()
    window_secs = cfg.analysis_window_seconds

    # Step 1 + 2: collect per-frame RMS for each narration, then find the
    # global peak so normalization is stable across quiet & loud files.
    per_narration: list[tuple[int, list[float]]] = []
    global_peak = 1e-9
    for spec in narration_specs:
        rms = _rms_per_frame(Path(spec["path"]), fps=fps, window_secs=window_secs)
        if rms:
            global_peak = max(global_peak, max(rms))
        per_narration.append((int(spec["start_frame"]), rms))

    # Step 3: compose into a single raw duck envelope over the full timeline.
    raw = [cfg.base_volume] * total_frames
    for start_frame, rms in per_narration:
        for i, energy in enumerate(rms):
            f = start_frame + i
            if f < 0 or f >= total_frames:
                continue
            normalized = min(energy / global_peak, 1.0)
            # Loud narration → low music: base × (1 − depth × normalized)
            target = cfg.base_volume * (1.0 - cfg.depth * normalized)
            # Take the MIN across overlapping narrations so the louder
            # source wins (correct behavior if narrations ever overlap).
            if target < raw[f]:
                raw[f] = target

    # Step 4: asymmetric smoothing — attack faster than release.
    return _asymmetric_smooth(raw, cfg.base_volume, cfg.attack_frames, cfg.release_frames)


def write_envelope_ts(envelope: list[float], target: Path, base_volume: float) -> Path:
    """Serialize the envelope as `envelope.generated.ts` for Remotion to
    import. Writes a `Float32Array` to keep file size and parse cost
    modest for long compositions."""
    target.parent.mkdir(parents=True, exist_ok=True)
    body_parts = [
        "// GENERATED at compose time. Do not edit.",
        "// Per-frame music volume envelope, length == composition durationInFrames.",
        f"export const BASE_VOLUME = {base_volume};",
        f"export const envelope: readonly number[] = [",
    ]
    # Chunk 16 values per line for readability without ballooning file size.
    chunk = 16
    for i in range(0, len(envelope), chunk):
        row = ", ".join(f"{v:.4f}" for v in envelope[i:i + chunk])
        body_parts.append(f"  {row},")
    body_parts.append("];")
    target.write_text("\n".join(body_parts) + "\n", encoding="utf-8")
    return target


def _rms_per_frame(audio_path: Path, *, fps: int, window_secs: float) -> list[float]:
    """One RMS value per video frame over the audio's full duration.

    Uses the stdlib `wave` module — all TTS providers we support emit
    WAV, and avoiding numpy/librosa here keeps the dependency story
    clean for a feature most users run once per render."""
    if not audio_path.exists():
        return []
    try:
        with wave.open(str(audio_path), "rb") as w:
            nchannels = w.getnchannels()
            sampwidth = w.getsampwidth()
            framerate = w.getframerate()
            nframes = w.getnframes()
            raw = w.readframes(nframes)
    except wave.Error:
        return []

    samples = _decode_pcm(raw, sampwidth=sampwidth, channels=nchannels)
    if not samples:
        return []

    samples_per_frame = int(framerate / fps)
    if samples_per_frame <= 0:
        return []

    out: list[float] = []
    for start in range(0, len(samples), samples_per_frame):
        window = samples[start:start + samples_per_frame]
        if not window:
            break
        mean_sq = sum(s * s for s in window) / len(window)
        out.append(math.sqrt(mean_sq))
    return out


def _decode_pcm(raw: bytes, *, sampwidth: int, channels: int) -> list[float]:
    """Decode 16-bit or 8-bit PCM bytes to a mono float list in [-1, 1].
    Stereo tracks are averaged to mono."""
    if sampwidth == 2:
        max_amp = 32768.0
        # struct.iter_unpack avoids building a huge intermediate tuple
        import struct
        mono: list[float] = []
        if channels == 1:
            for (sample,) in struct.iter_unpack("<h", raw):
                mono.append(sample / max_amp)
        else:
            # Average across channels.
            fmt = "<" + "h" * channels
            for values in struct.iter_unpack(fmt, raw):
                mono.append(sum(values) / (channels * max_amp))
        return mono
    if sampwidth == 1:
        # 8-bit PCM is unsigned; centered around 128.
        if channels == 1:
            return [(b - 128) / 128.0 for b in raw]
        out: list[float] = []
        for i in range(0, len(raw), channels):
            group = raw[i:i + channels]
            if len(group) < channels:
                break
            out.append(sum(b - 128 for b in group) / (channels * 128.0))
        return out
    # Unsupported bit depth — silent fallback; the envelope will just be flat.
    return []


def _asymmetric_smooth(
    values: list[float], base: float, attack: int, release: int,
) -> list[float]:
    """One-pole filter with different time constants for dipping (attack)
    vs. recovering (release). Keeps the bed from thrashing."""
    smoothed = list(values)
    if attack <= 0 and release <= 0:
        return smoothed
    alpha_attack = 1.0 / max(attack, 1)
    alpha_release = 1.0 / max(release, 1)
    current = base
    for i, target in enumerate(smoothed):
        if target < current:  # duck: use faster attack
            current += (target - current) * alpha_attack
        else:  # recover: slower release
            current += (target - current) * alpha_release
        smoothed[i] = current
    return smoothed
