"""Pipeline events + cancellation for embedded use.

The CLI doesn't need any of this — it prints to stdout and exits.
Anything embedding `Pipeline` (chatbots, web servers, IDE plugins)
benefits from a structured event stream so the user gets progress
feedback instead of staring at a 5-minute black box.

Design constraints:
- Events are immutable dataclasses (safe to log, queue, serialize).
- Synchronous callback is the primitive; async iteration is built
  on top of it via a queue.
- Cancellation is cooperative: the pipeline checks `cancel_token`
  at scene-boundary checkpoints and raises `PipelineCancelled` to
  unwind cleanly.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from showrunner.plan import Plan


# ── Event types ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PipelineEvent:
    """Base for every pipeline event. Use isinstance() to discriminate."""


@dataclass(frozen=True)
class StageStarted(PipelineEvent):
    """A pipeline stage is about to begin.

    Stages: "plan", "narration", "scene_code", "compose", "render".
    """
    stage: str


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
    """The final video is on disk."""
    output_path: Path


@dataclass(frozen=True)
class PipelineFailed(PipelineEvent):
    """Terminal failure with a reason. Pipeline will not continue."""
    stage: str
    error: str


@dataclass(frozen=True)
class PipelineCancelled(PipelineEvent):
    """User-initiated cancellation took effect at a checkpoint."""


# Type alias for callbacks. Embed apps usually want a single dispatcher.
EventCallback = "Any"  # callable: (PipelineEvent) -> None


# ── Cancellation ─────────────────────────────────────────────────────────


class CancelledError(Exception):
    """Raised internally when a `CancelToken` trips at a checkpoint."""


class CancelToken:
    """Cooperative cancellation for long-running pipelines.

    Caller creates one, optionally calls `.cancel()`. Pipeline checks
    `.raise_if_cancelled()` at scene-boundary checkpoints. Cancellation
    unwinds with a `CancelledError`, surfaced to the caller as a
    `PipelineCancelled` event (sync API) or by terminating the async
    iterator (async API).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False

    def cancel(self) -> None:
        """Mark the token as cancelled. Idempotent, thread-safe."""
        with self._lock:
            self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

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
