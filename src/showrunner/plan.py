"""Plan and Scene data models for video storyboards."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Scene:
    """A single scene in a video plan."""
    id: str
    duration: int  # seconds
    narration: str
    visual: str
    transition: str = "fade"
    # Optional per-scene TTS voice override (e.g. two-character dialogue).
    # None means "use the run's default voice".
    voice: str | None = None


@dataclass
class Plan:
    """A complete video storyboard — the output of Format.plan()."""
    title: str
    total_duration: int  # seconds
    scenes: list[Scene] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dict with camelCase keys (Remotion-compatible)."""
        return {
            "title": self.title,
            "totalDuration": self.total_duration,
            "scenes": [
                {
                    "id": s.id,
                    "duration": s.duration,
                    "narration": s.narration,
                    "visual": s.visual,
                    "transition": s.transition,
                    # Omitted when unset so existing plan JSON stays byte-stable.
                    **({"voice": s.voice} if s.voice else {}),
                }
                for s in self.scenes
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Plan:
        """Deserialize from dict. Accepts both camelCase and snake_case keys."""
        total_duration = d.get("total_duration") or d.get("totalDuration", 0)
        scenes = [
            Scene(
                id=s["id"],
                duration=s["duration"],
                narration=s["narration"],
                visual=s["visual"],
                transition=s.get("transition", "fade"),
                voice=s.get("voice"),
            )
            for s in d.get("scenes", [])
        ]
        return cls(title=d["title"], total_duration=total_duration, scenes=scenes)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> Plan:
        return cls.from_dict(json.loads(json_str))
