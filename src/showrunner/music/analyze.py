"""Beat analysis: estimate BPM + a beat grid for a music track.

Uses librosa when installed; otherwise a dependency-light estimator
(onset-flux autocorrelation) over numpy + soundfile. Install either via
`pip install "showrunner[audio]"`.
"""

from __future__ import annotations

from pathlib import Path

# Search band for tempo candidates.
MIN_BPM = 60.0
MAX_BPM = 200.0

_HOP = 512
_WIN = 1024


def analyze_track(path: Path | str) -> dict:
    """Return {"bpm", "beat_interval", "offset", "beats", "duration"}.

    `beats` are absolute times (seconds) on a regular grid aligned to the
    track's onsets — downstream tools snap clip timings to them.
    """
    path = Path(path)
    try:
        return _analyze_librosa(path)
    except ImportError:
        pass
    try:
        return _analyze_numpy(path)
    except ImportError:
        raise RuntimeError(
            "music analyze needs numpy + soundfile (or librosa). "
            'Install with: pip install "showrunner[audio]"'
        ) from None


def _analyze_librosa(path: Path) -> dict:
    import librosa

    y, sr = librosa.load(str(path), sr=None, mono=True)
    duration = len(y) / sr
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(tempo)
    beats = [float(t) for t in librosa.frames_to_time(beat_frames, sr=sr)]
    interval = 60.0 / bpm if bpm else 0.0
    return {
        "bpm": round(bpm, 2),
        "beat_interval": round(interval, 4),
        "offset": round(beats[0], 4) if beats else 0.0,
        "beats": [round(b, 4) for b in beats],
        "duration": round(duration, 3),
    }


def _analyze_numpy(path: Path) -> dict:
    import numpy as np
    import soundfile as sf

    signal, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = signal.mean(axis=1)
    duration = len(mono) / sr

    # Onset envelope: positive flux of per-frame RMS energy.
    n_frames = max((len(mono) - _WIN) // _HOP, 1)
    rms = np.empty(n_frames, dtype=np.float64)
    for i in range(n_frames):
        frame = mono[i * _HOP : i * _HOP + _WIN]
        rms[i] = np.sqrt(np.mean(frame * frame))
    flux = np.maximum(np.diff(rms, prepend=rms[0]), 0.0)
    flux -= flux.mean()

    # Tempo: comb scoring on a fractional beat grid. Integer-lag
    # autocorrelation aliases to harmonics whenever the true beat interval
    # isn't a whole number of frames, so instead we score candidate BPMs
    # directly: how much onset energy does a regular grid at that tempo
    # catch, at its best phase? Sub-tempo harmonics tie with the true
    # tempo (their beats are a subset), so ties break toward the FASTER
    # tempo within the band.
    frames_per_second = sr / _HOP
    if len(flux) < frames_per_second * 2:
        raise ValueError(f"track too short to analyze: {duration:.2f}s")

    def comb_score(interval_frames: float) -> tuple[float, float]:
        n_beats = int((len(flux) - 1) / interval_frames)
        if n_beats < 3:
            return 0.0, 0.0
        beat_idx = np.arange(n_beats) * interval_frames
        best, best_phase = 0.0, 0.0
        for phase in np.arange(0.0, interval_frames, 0.5):
            idx = np.round(phase + beat_idx).astype(int)
            idx = idx[idx < len(flux)]
            # ±1-frame tolerance: fractional intervals round each beat onto
            # a neighboring frame; take the local max so a hair of drift
            # doesn't zero out a genuine hit.
            lo = np.clip(idx - 1, 0, len(flux) - 1)
            hi = np.clip(idx + 1, 0, len(flux) - 1)
            score = float(np.maximum(np.maximum(flux[lo], flux[idx]), flux[hi]).mean())
            if score > best:
                best, best_phase = score, float(phase)
        return best, best_phase

    candidates = np.arange(MIN_BPM, MAX_BPM + 0.25, 0.5)
    scores = np.empty(len(candidates))
    phases = np.empty(len(candidates))
    for i, cand in enumerate(candidates):
        scores[i], phases[i] = comb_score(frames_per_second * 60.0 / cand)
    if scores.max() <= 0:
        raise ValueError("no rhythmic onsets detected")
    pick = int(np.argmax(scores))
    bpm, score, phase = float(candidates[pick]), scores[pick], phases[pick]

    # Octave correction: a sub-harmonic (half the true tempo) can outscore
    # the true tempo by cherry-picking the stronger alternate onsets. If
    # doubling the tempo still catches most of the energy, the double is
    # the real beat; a genuine half-time grid would drop to ~50%.
    while bpm * 2 <= MAX_BPM:
        double_score, double_phase = comb_score(frames_per_second * 60.0 / (bpm * 2))
        if double_score >= 0.6 * score:
            bpm, score, phase = bpm * 2, double_score, double_phase
        else:
            break
    interval = 60.0 / bpm
    offset = phase / frames_per_second

    beats = []
    t = offset
    while t <= duration:
        beats.append(round(t, 4))
        t += interval

    return {
        "bpm": round(bpm, 2),
        "beat_interval": round(interval, 4),
        "offset": round(offset, 4),
        "beats": beats,
        "duration": round(duration, 3),
    }
