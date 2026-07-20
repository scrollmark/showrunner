"""Caption data model — mirrors the `Caption` type from `@remotion/captions`."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Caption:
    """A single timed word (or token) of on-screen caption text.

    Serializes to the camelCase shape `@remotion/captions` expects:
    `{text, startMs, endMs, timestampMs}`.
    """

    text: str
    start_ms: int
    end_ms: int
    timestamp_ms: int | None = None

    def to_dict(self) -> dict:
        ts = self.timestamp_ms
        if ts is None:
            ts = (self.start_ms + self.end_ms) // 2
        return {
            "text": self.text,
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "timestampMs": ts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Caption:
        """Accept both camelCase (the on-disk contract) and snake_case."""

        def pick(camel: str, snake: str, default=None):
            if camel in data:
                return data[camel]
            return data.get(snake, default)

        start = int(pick("startMs", "start_ms", 0))
        end = int(pick("endMs", "end_ms", 0))
        ts = pick("timestampMs", "timestamp_ms")
        return cls(
            text=str(data.get("text", "")),
            start_ms=start,
            end_ms=end,
            timestamp_ms=int(ts) if ts is not None else None,
        )
