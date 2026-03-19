"""Abstract TTS provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AudioFile:
    """Result of TTS synthesis."""
    path: Path
    duration: float  # seconds
    sample_rate: int = 24000


class TTSProvider(ABC):
    """Synthesize speech from text."""

    @abstractmethod
    def synthesize(self, text: str, *, output_path: Path, voice: str, speed: float = 1.0) -> AudioFile:
        """Synthesize text to audio file."""

    @abstractmethod
    def list_voices(self) -> list[dict[str, str]]:
        """List available voices."""
