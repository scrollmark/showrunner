"""Benchmark harness — same brief, matrixed agent conditions, judged output.

A *condition* is one way of producing a video: which agent CLI runs, and
whether the workspace it runs in has the showrunner toolchain staged. Every
condition gets the identical brief; only the toolchain preamble differs, so
quality differences are attributable to the toolchain, not the prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

TOOLCHAIN_PREAMBLES = {
    "showrunner": (
        "You are producing a video in this workspace. The `showrunner` CLI is "
        "on your PATH — read AGENTS.md in this directory first and follow its "
        "workflow, including its validation gates.\n\n"
    ),
    "bare": (
        "You are producing a video in this workspace. Use whatever "
        "general-purpose tools are available on this system.\n\n"
    ),
}

DELIVERABLE_CONTRACT = (
    "\n\nDeliverable: write the finished video to out/final.mp4 inside this "
    "workspace (1080x1920 vertical mp4 with audio). Work autonomously — do "
    "not ask questions. When the file is written and verified playable, stop."
)


@dataclass
class BenchCondition:
    id: str
    agent: str
    command: list[str] = field(default_factory=list)
    toolchain: str = "bare"
    # Off by default: an inherited ANTHROPIC_API_KEY overrides the machine's
    # subscription login and bills runs at per-token API prices.
    use_api_key: bool = False


def load_conditions(path: Path) -> list[BenchCondition]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    conditions = []
    for entry in data.get("conditions", []):
        toolchain = entry.get("toolchain", "bare")
        if toolchain not in TOOLCHAIN_PREAMBLES:
            raise ValueError(
                f"condition '{entry.get('id')}' has unknown toolchain '{toolchain}' "
                f"(known: {sorted(TOOLCHAIN_PREAMBLES)})"
            )
        conditions.append(BenchCondition(
            id=entry["id"],
            agent=entry.get("agent", "unknown"),
            command=list(entry["command"]),
            toolchain=toolchain,
            use_api_key=bool(entry.get("use_api_key", False)),
        ))
    return conditions


def build_prompt(brief: str, *, toolchain: str) -> str:
    return TOOLCHAIN_PREAMBLES[toolchain] + brief.strip() + DELIVERABLE_CONTRACT
