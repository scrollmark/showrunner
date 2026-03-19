"""Abstract video generation provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class VideoProvider(ABC):
    """Generate video clips from text prompts."""

    @abstractmethod
    def generate(self, prompt: str, *, duration: int, aspect_ratio: str, output_path: Path) -> Path:
        """Generate a video clip from a text prompt.

        Handles the full lifecycle: submit → poll → download.
        Returns path to the downloaded MP4 file.
        """

    @abstractmethod
    def poll(self, generation_id: str) -> tuple[str, str | None]:
        """Check status of an async generation.

        Returns (status, download_url_or_none).
        Status is one of: "pending", "processing", "completed", "failed".
        """
