"""Feedback data model for plan/asset/composition review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Feedback:
    """User feedback on a pipeline phase."""
    level: str  # "plan" | "asset" | "composition"
    scene_id: str | None = None
    text: str | None = None
    image: Path | None = None  # future: screenshot/reference
    edits: dict | None = None  # structured JSON patch
