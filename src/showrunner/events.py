"""Pipeline events + cancellation for embedded use.

The CLI doesn't need any of this — it prints to stdout and exits.
Anything embedding `Pipeline` (chatbots, web servers, IDE plugins)
benefits from a structured event stream so the user gets progress
feedback instead of staring at a 5-minute black box.

Stability contract (public API — see also docs/embedding.md):
- Event class names and their existing fields are stable. New fields
  are only ever ADDED, with defaults, so `isinstance()` dispatch and
  keyword construction keep working across versions.
- The event sequence for a successful `Pipeline.run()` is:

    StageStarted(stage="plan")
    PlanReady(plan=...)
    StageCompleted(stage="plan")
    WorkDirReady(work_dir=...)
    StageStarted(stage="assets")
      NarrationCompleted(...) per scene        (format-dependent)
      SceneStarted / SceneCompleted per scene  (format-dependent;
        SceneFailed on exhausted retries)
    StageCompleted(stage="assets")
    StageStarted(stage="compose")
    StageCompleted(stage="compose")
    StageStarted(stage="render")
    StageCompleted(stage="render")
    RenderCompleted(output_path=..., usage=..., cost_usd=...)   # "done"

  A failed run ends with PipelineFailed; a cancelled run ends with
  PipelineCancelled (and `run()` raises `PipelineCancelledError`).
- Stage-level events carry a coarse `progress_pct` (0-100) derived
  from `STAGE_PROGRESS`. Scene-level events carry `index`/`total`
  for fine-grained progress within the assets stage.

Design constraints:
- Events are immutable dataclasses (safe to log, queue, serialize).
- Synchronous callback is the primitive; async iteration is built
  on top of it via a queue.
- Cancellation is cooperative: the pipeline checks `cancel_token`
  (or a plain `threading.Event` passed as `cancel_event`) between
  scenes and stages, emits a `PipelineCancelled` event, and raises
  `PipelineCancelledError` to unwind cleanly.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from showrunner.plan import Plan


# ── Event types ──────────────────────────────────────────────────────────

# Coarse progress span (start_pct, end_pct) for each top-level stage of
# a full `Pipeline.run()`. StageStarted carries the span's start,
# StageCompleted its end. Weights reflect typical wall-clock time
# (assets dominate: TTS + per-scene codegen / video generation).
STAGE_PROGRESS: dict[str, tuple[float, float]] = {
    "plan": (0.0, 10.0),
    "assets": (10.0, 70.0),
    "compose": (70.0, 75.0),
    "render": (75.0, 100.0),
}


@dataclass(frozen=True)
class PipelineEvent:
    """Base for every pipeline event. Use isinstance() to discriminate."""


@dataclass(frozen=True)
class StageStarted(PipelineEvent):
    """A pipeline stage is about to begin.

    Stages: "plan", "assets", "compose", "render" (and "refine" /
    "refine_scene_codegen" for `Pipeline.refine`).

    `progress_pct` is a coarse 0-100 figure (see STAGE_PROGRESS);
    None for stages outside the standard run flow.
    """
    stage: str
    progress_pct: float | None = None


@dataclass(frozen=True)
class WorkDirReady(PipelineEvent):
    """The render work directory has been set up. Hosts that want to
    later refine a single scene need this path — without it the work
    dir is created via tempfile.mkdtemp and forgotten."""
    work_dir: Path


@dataclass(frozen=True)
class StageCompleted(PipelineEvent):
    """A pipeline stage just finished cleanly."""
    stage: str
    progress_pct: float | None = None


@dataclass(frozen=True)
class PlanReady(PipelineEvent):
    """The storyboard plan is ready (before any TTS / scene codegen).
    Useful to show the user the scene breakdown immediately while the
    longer asset stages keep running."""
    plan: "Plan"


@dataclass(frozen=True)
class SceneStarted(PipelineEvent):
    """An individual scene's codegen is starting."""
    scene_id: str
    index: int   # 1-based
    total: int


@dataclass(frozen=True)
class SceneCompleted(PipelineEvent):
    """An individual scene's codegen + validation passed."""
    scene_id: str
    index: int
    total: int


@dataclass(frozen=True)
class SceneFailed(PipelineEvent):
    """An individual scene exhausted retries."""
    scene_id: str
    error: str


@dataclass(frozen=True)
class NarrationCompleted(PipelineEvent):
    """A scene's TTS narration finished."""
    scene_id: str
    duration_seconds: float


@dataclass(frozen=True)
class RenderCompleted(PipelineEvent):
    """The final video is on disk — the "done" event.

    `usage` aggregates per-provider actuals (LLM tokens, TTS chars,
    video seconds) as reported by provider `get_usage()` hooks;
    `cost_usd` is the reconciled dollar figure. Both are None when
    no provider reported usage (see showrunner.costs).
    """
    output_path: Path
    usage: dict | None = None
    cost_usd: float | None = None


@dataclass(frozen=True)
class PipelineFailed(PipelineEvent):
    """Terminal failure with a reason. Pipeline will not continue."""
    stage: str
    error: str


@dataclass(frozen=True)
class PipelineCancelled(PipelineEvent):
    """User-initiated cancellation took effect at a checkpoint.

    `work_dir` (when set) points at the partially-built work dir,
    which is left intact — including a `showrunner.json` manifest
    with the plan — so the host can resume or refine later.
    """
    work_dir: Path | None = None


# Type alias for callbacks. Embed apps usually want a single dispatcher.
EventCallback = "Any"  # callable: (PipelineEvent) -> None


# ── Cancellation ─────────────────────────────────────────────────────────


class CancelledError(Exception):
    """Raised internally when a `CancelToken` trips at a checkpoint."""


class PipelineCancelledError(Exception):
    """Raised by `Pipeline.run()` when cooperative cancellation takes
    effect. `work_dir` (when not None) is the partially-built work
    dir, left resumable on disk — it contains a `showrunner.json`
    manifest with the plan and any assets generated so far.
    """

    def __init__(self, work_dir: Path | None = None):
        super().__init__(
            "pipeline cancelled"
            + (f" (resumable work_dir: {work_dir})" if work_dir else "")
        )
        self.work_dir = work_dir


class CancelToken:
    """Cooperative cancellation for long-running pipelines.

    Caller creates one, optionally calls `.cancel()`. Pipeline checks
    `.raise_if_cancelled()` at scene-boundary checkpoints. Cancellation
    unwinds with an internal `CancelledError`, surfaced to the caller
    as a `PipelineCancelled` event plus a `PipelineCancelledError`
    raised from `run()` (sync API) or by terminating the async
    iterator (async API).

    A token can wrap an existing `threading.Event` so hosts that
    already coordinate shutdown with an Event can pass it straight
    through (`Pipeline.run(cancel_event=my_event)` does this for you).
    """

    def __init__(self, event: threading.Event | None = None) -> None:
        self._event = event if event is not None else threading.Event()

    def cancel(self) -> None:
        """Mark the token as cancelled. Idempotent, thread-safe."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """Raise `CancelledError` if cancelled. Call at checkpoints."""
        if self.is_cancelled:
            raise CancelledError()


# ── Helpers ──────────────────────────────────────────────────────────────


def emit(callback, event: PipelineEvent) -> None:
    """Best-effort event emit — never raises out of the pipeline if the
    user's callback throws. Failed callbacks shouldn't break renders."""
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        pass
