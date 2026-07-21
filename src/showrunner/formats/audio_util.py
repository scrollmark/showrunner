"""Small audio helpers shared by format asset generators."""

from __future__ import annotations

import contextlib
import wave
from pathlib import Path


def wav_duration_seconds(path: Path) -> float | None:
    """Duration of a WAV file in seconds, or None if it can't be read.

    Used by per-scene asset resume: an existing narration file's duration
    must be recovered without re-running TTS. Returns None (caller should
    regenerate) for empty/corrupt files.
    """
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate <= 0 or frames <= 0:
                return None
            return frames / float(rate)
    except (OSError, wave.Error, EOFError):
        return None
