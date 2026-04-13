"""Abstract Format interface — defines a video production pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from showrunner.feedback import Feedback
from showrunner.plan import Plan


class Format(ABC):
    """A video format plugin."""
    name: str
    description: str
    required_providers: list[str]

    # Render pipeline wiring — overrideable on subclasses.
    preferred_render_provider: str = "remotion"
    requires_video_provider: bool = False

    @abstractmethod
    def plan(self, topic: str, style: Any, config: Any, llm: Any) -> Plan:
        """Generate a storyboard/plan from a topic."""

    @abstractmethod
    def generate_assets(self, plan: Plan, providers: dict, work_dir: Path) -> dict:
        """Generate all assets. Returns asset metadata dict."""

    @abstractmethod
    def compose(self, plan: Plan, assets: dict, work_dir: Path, **kwargs) -> None:
        """Compose the final timeline/composition."""

    @abstractmethod
    def revise(self, plan: Plan, feedback: Feedback, llm: Any) -> Plan:
        """Revise a plan based on user feedback."""
