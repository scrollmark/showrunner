"""Abstract render provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class RenderProvider(ABC):
    """Render a video composition to file."""

    @abstractmethod
    def setup(self, work_dir: Path) -> None:
        """Initialize render environment."""

    @abstractmethod
    def render(self, *, work_dir: Path, output_path: Path) -> Path:
        """Render composition to output file."""

    @abstractmethod
    def preview(self, work_dir: Path) -> None:
        """Open interactive preview."""
