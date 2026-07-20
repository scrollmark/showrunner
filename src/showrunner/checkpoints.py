"""Per-stage pipeline checkpoints — the resumability contract for a work_dir.

Every pipeline stage (`plan`, `assets`, `compose`, `render`) writes a
`checkpoint_<stage>.json` file into the work_dir recording its status,
timestamps, and outputs (or pointers to them inside the work_dir). A
mirror `stages` summary is kept in `showrunner.json` so a single read
tells an external host where a run stands.

This is a public contract: `showrunner resume <work_dir>`, the OTIO
exporter, and the hosted platform worker all depend on the work_dir
layout documented in docs/workdir-layout.md.

Statuses:
- ``pending``        — stage has not started (also implied by a missing file)
- ``in_progress``    — stage started but has not finished (a crash mid-stage
                       leaves this behind; resume re-runs the stage)
- ``awaiting_human`` — reserved for approval gates (not yet emitted)
- ``completed``      — stage finished; its outputs are on disk
- ``failed``         — stage raised; ``error`` holds the message
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Pipeline stages, in execution order.
STAGES: tuple[str, ...] = ("plan", "assets", "compose", "render")

STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_AWAITING_HUMAN = "awaiting_human"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

VALID_STATUSES = frozenset(
    {STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_AWAITING_HUMAN, STATUS_COMPLETED, STATUS_FAILED}
)


@dataclass
class Checkpoint:
    """One stage's persisted state inside a work_dir."""

    stage: str
    status: str = STATUS_PENDING
    started_at: str | None = None    # ISO-8601 UTC
    completed_at: str | None = None  # ISO-8601 UTC (set on completed/failed)
    error: str | None = None
    outputs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "outputs": self.outputs,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Checkpoint:
        return cls(
            stage=d["stage"],
            status=d.get("status", STATUS_PENDING),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
            error=d.get("error"),
            outputs=d.get("outputs") or {},
        )


def checkpoint_path(work_dir: Path, stage: str) -> Path:
    return Path(work_dir) / f"checkpoint_{stage}.json"


def read_checkpoint(work_dir: Path, stage: str) -> Checkpoint | None:
    """Read one stage's checkpoint. Returns None when the file is missing
    or unreadable (both mean: the stage never ran)."""
    path = checkpoint_path(work_dir, stage)
    if not path.exists():
        return None
    try:
        return Checkpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def stage_status(work_dir: Path, stage: str) -> str:
    """A stage's status; ``pending`` when no checkpoint exists."""
    cp = read_checkpoint(work_dir, stage)
    return cp.status if cp is not None else STATUS_PENDING


def is_stage_completed(work_dir: Path, stage: str) -> bool:
    return stage_status(work_dir, stage) == STATUS_COMPLETED


def read_all_checkpoints(work_dir: Path) -> dict[str, Checkpoint | None]:
    """All stage checkpoints keyed by stage name, in execution order."""
    return {stage: read_checkpoint(work_dir, stage) for stage in STAGES}


def stages_summary(work_dir: Path) -> dict[str, str]:
    """``{stage: status}`` for all stages — the shape mirrored into
    ``showrunner.json``'s ``stages`` key."""
    return {stage: stage_status(work_dir, stage) for stage in STAGES}


def mark_stage(
    work_dir: Path,
    stage: str,
    status: str,
    *,
    outputs: dict | None = None,
    error: str | None = None,
) -> Checkpoint:
    """Transition a stage to ``status``, persist its checkpoint file, and
    mirror the summary into ``showrunner.json``.

    Timestamps are managed here: ``started_at`` is stamped on the first
    transition to ``in_progress``; ``completed_at`` on ``completed`` /
    ``failed``. Existing outputs are merged (new keys win).
    """
    if stage not in STAGES:
        raise ValueError(f"Unknown stage '{stage}'. Valid stages: {STAGES}")
    if status not in VALID_STATUSES:
        raise ValueError(f"Unknown status '{status}'. Valid: {sorted(VALID_STATUSES)}")

    work_dir = Path(work_dir)
    cp = read_checkpoint(work_dir, stage) or Checkpoint(stage=stage)
    now = datetime.now(timezone.utc).isoformat()

    cp.status = status
    if status == STATUS_IN_PROGRESS:
        cp.started_at = cp.started_at or now
        cp.completed_at = None
        cp.error = None
    elif status in (STATUS_COMPLETED, STATUS_FAILED):
        cp.started_at = cp.started_at or now
        cp.completed_at = now
    cp.error = error if error is not None else (cp.error if status == STATUS_FAILED else None)
    if outputs:
        cp.outputs = {**cp.outputs, **outputs}

    path = checkpoint_path(work_dir, stage)
    path.write_text(json.dumps(cp.to_dict(), indent=2), encoding="utf-8")
    _sync_showrunner_stages(work_dir)
    return cp


def _sync_showrunner_stages(work_dir: Path) -> None:
    """Mirror the per-stage statuses into ``showrunner.json``'s ``stages``
    key. Best-effort: a missing or corrupt ``showrunner.json`` is left
    alone (the checkpoint files remain the source of truth)."""
    meta_path = Path(work_dir) / "showrunner.json"
    if not meta_path.exists():
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    meta["stages"] = stages_summary(work_dir)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def first_incomplete_stage(work_dir: Path) -> str | None:
    """The first stage (in execution order) that is not ``completed``,
    or None when every stage is done."""
    for stage in STAGES:
        if not is_stage_completed(work_dir, stage):
            return stage
    return None
