"""Abstract TTS provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WordTiming:
    """Word-level timing metadata from a TTS provider (seconds)."""
    word: str
    start: float
    end: float


@dataclass
class AudioFile:
    """Result of TTS synthesis."""
    path: Path
    duration: float  # seconds
    sample_rate: int = 24000
    # Optional word-level timings when the provider exposes them
    # (e.g. Kokoro token timestamps). Used for word-synced captions.
    word_timings: list[WordTiming] | None = None


class TTSProvider(ABC):
    """Synthesize speech from text."""

    @abstractmethod
    def synthesize(self, text: str, *, output_path: Path, voice: str, speed: float = 1.0) -> AudioFile:
        """Synthesize text to audio file."""

    @abstractmethod
    def list_voices(self) -> list[dict[str, str]]:
        """List available voices."""

    # ── Optional cost/usage hooks (see showrunner.costs) ──────────────
    # Non-abstract with null defaults so existing providers keep working.

    def estimate_cost(self, *, characters: int) -> float | None:
        """Optional pricing hook: USD for synthesizing `characters`.

        Default None — the pipeline falls back to its built-in
        pricing table (showrunner.costs.TTS_PRICING_PER_1K_CHARS).
        """
        return None

    def get_usage(self) -> dict:
        """Optional usage-reporting hook: cumulative usage since this
        provider instance was created. Default reports zeros so
        providers that don't track usage keep working."""
        return {"characters": 0, "calls": 0}
