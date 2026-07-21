"""`--json` agent mode — NDJSON serialization of pipeline events.

Coding agents (Claude Code, Cursor, ...) drive the CLI programmatically
and shouldn't scrape human prose. Under the global `--json` flag:

- stdout carries ONLY newline-delimited JSON (NDJSON) events, one
  object per line, each with an `"event"` discriminator field;
- human logging moves to stderr;
- failures end with an `{"event": "error", ...}` line and a non-zero
  exit code;
- listing commands (`formats`, `styles`, `voices`, `providers`) emit a
  single JSON document instead of a stream.

The event schema is a stability contract (documented in README.md):
changes are ADDITIVE-ONLY — existing event names and fields never
change meaning or disappear; new events and new fields may appear, so
consumers must ignore unknown events/fields.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from showrunner.events import (
    NarrationCompleted,
    PipelineCancelled,
    PipelineEvent,
    PipelineFailed,
    PlanReady,
    RenderCompleted,
    SceneCompleted,
    SceneFailed,
    SceneStarted,
    StageCompleted,
    StageStarted,
    WorkDirReady,
)


def write_json_line(doc: dict) -> None:
    """Write one NDJSON line to stdout and flush (agents read pipes)."""
    sys.stdout.write(json.dumps(doc, default=str) + "\n")
    sys.stdout.flush()


class JsonEventStream:
    """Maps typed `PipelineEvent`s to the documented NDJSON schema.

    Pass an instance as `on_event=` to `Pipeline.run()` / `.refine()`.
    Tracks the work_dir (from `WorkDirReady`) so the terminal `done`
    event can carry both `output_path` and `work_dir`, and whether a
    terminal `error` event has been written so the CLI can emit one
    itself for failures that happen outside the pipeline.
    """

    def __init__(self, asset_kind: str = "code", work_dir: Path | None = None):
        #: What the per-scene asset is: "code" (faceless-explainer TSX),
        #: "clip" (ai-video generated clips). TTS events carry "tts".
        self.asset_kind = asset_kind
        self.work_dir: Path | None = work_dir
        self.error_emitted = False

    # ── callback protocol ────────────────────────────────────────────

    def __call__(self, ev: PipelineEvent) -> None:
        doc = self._to_doc(ev)
        if doc is not None:
            write_json_line(doc)

    # ── manual emission (CLI-side failures, dry-run terminal) ────────

    def emit_error(self, *, stage: str, message: str) -> None:
        self.error_emitted = True
        write_json_line({"event": "error", "stage": stage, "message": message})

    def emit_done(self, *, output_path=None, extra: dict | None = None) -> None:
        doc = {
            "event": "done",
            "output_path": str(output_path) if output_path is not None else None,
            "work_dir": str(self.work_dir) if self.work_dir is not None else None,
        }
        if extra:
            doc.update(extra)
        write_json_line(doc)

    # ── event mapping ────────────────────────────────────────────────

    def _to_doc(self, ev: PipelineEvent) -> dict | None:
        if isinstance(ev, PlanReady):
            return {
                "event": "plan_ready",
                "title": ev.plan.title,
                "scenes": len(ev.plan.scenes),
                "total_duration": ev.plan.total_duration,
                "plan": ev.plan.to_dict(),
            }
        if isinstance(ev, WorkDirReady):
            self.work_dir = ev.work_dir
            return {"event": "work_dir_ready", "work_dir": str(ev.work_dir)}
        if isinstance(ev, StageStarted):
            return {
                "event": "stage_started",
                "stage": ev.stage,
                "progress_pct": ev.progress_pct,
            }
        if isinstance(ev, StageCompleted):
            return {
                "event": "stage_completed",
                "stage": ev.stage,
                "progress_pct": ev.progress_pct,
            }
        if isinstance(ev, SceneStarted):
            return {
                "event": "asset_progress",
                "scene_id": ev.scene_id,
                "kind": self.asset_kind,
                "status": "started",
                "index": ev.index,
                "total": ev.total,
            }
        if isinstance(ev, SceneCompleted):
            return {
                "event": "asset_progress",
                "scene_id": ev.scene_id,
                "kind": self.asset_kind,
                "status": "completed",
                "index": ev.index,
                "total": ev.total,
            }
        if isinstance(ev, NarrationCompleted):
            return {
                "event": "asset_progress",
                "scene_id": ev.scene_id,
                "kind": "tts",
                "status": "completed",
                "duration_seconds": ev.duration_seconds,
            }
        if isinstance(ev, SceneFailed):
            return {
                "event": "scene_failed",
                "scene_id": ev.scene_id,
                "error": ev.error,
            }
        if isinstance(ev, RenderCompleted):
            doc = {
                "event": "done",
                "output_path": str(ev.output_path),
                "work_dir": str(self.work_dir) if self.work_dir is not None else None,
            }
            if ev.usage is not None:
                doc["usage"] = ev.usage
            if ev.cost_usd is not None:
                doc["cost_usd"] = ev.cost_usd
            return doc
        if isinstance(ev, PipelineFailed):
            self.error_emitted = True
            return {"event": "error", "stage": ev.stage, "message": ev.error}
        if isinstance(ev, PipelineCancelled):
            return {
                "event": "cancelled",
                "work_dir": str(ev.work_dir) if ev.work_dir is not None else None,
            }
        # Unknown / future event types: skip rather than guess a schema.
        return None
