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
