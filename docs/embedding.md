# Embedding Showrunner

How to drive `Pipeline` from a host application (a web server, worker,
chatbot, IDE plugin) instead of the CLI: progress events, cooperative
cancellation, and cost estimation/reconciliation.

```python
from showrunner import Pipeline

pipeline = Pipeline(format_name="faceless-explainer")
```

## 1. Progress events (stability contract)

`Pipeline.run(on_event=...)` calls your callback with typed, frozen
dataclass events (`showrunner.events`). This surface is a **stability
contract**:

- Event **class names and existing fields never change**. New fields
  are only ever added, with defaults — dispatch on `isinstance()` and
  construct with keywords and your code survives upgrades.
- Exceptions thrown by your callback are swallowed; a buggy event
  handler can't break a render.

### Event types

| Event | Fields | Meaning |
|---|---|---|
| `StageStarted` | `stage`, `progress_pct` | A top-level stage began (`plan`, `assets`, `compose`, `render`; `refine`/`refine_scene_codegen` for `Pipeline.refine`) |
| `PlanReady` | `plan` | Storyboard is ready — show the scene breakdown while assets generate |
| `StageCompleted` | `stage`, `progress_pct` | Stage finished cleanly |
| `WorkDirReady` | `work_dir` | Work dir created; keep this path to refine/resume later |
| `NarrationCompleted` | `scene_id`, `duration_seconds` | One scene's TTS finished |
| `SceneStarted` | `scene_id`, `index`, `total` | One scene's codegen started (1-based `index`) |
| `SceneCompleted` | `scene_id`, `index`, `total` | Scene codegen + validation passed |
| `SceneFailed` | `scene_id`, `error` | Scene exhausted retries |
| `RepairAttempt` | `attempt`, `max_attempts`, `error`, `scene_id` | A render failed; the (truncated) error is being fed back through `Format.revise()` and the render retried. 1-based `attempt`, capped by the `repair_attempts` config knob (default 2, 0 disables). `scene_id` set when the failing scene is identifiable |
| `RenderCompleted` | `output_path`, `usage`, `cost_usd` | **Done.** Final video on disk, with actual usage + cost (None when unreported) |
| `PipelineFailed` | `stage`, `error` | Terminal failure |
| `PipelineCancelled` | `work_dir` | Cancellation took effect; `work_dir` (if any) is resumable |

### Event sequence

A successful `run()` emits, in order:

```
StageStarted(plan)  →  PlanReady  →  StageCompleted(plan)
WorkDirReady
StageStarted(assets)
    per scene: NarrationCompleted / SceneStarted / SceneCompleted   (format-dependent)
StageCompleted(assets)
StageStarted(compose)  →  StageCompleted(compose)
StageStarted(render)
    per failed render: RepairAttempt   (bounded by `repair_attempts`, default 2)
StageCompleted(render)
RenderCompleted        ← the "done" event
```

A failed run ends with `PipelineFailed` (and `run()` re-raises); a
cancelled run ends with `PipelineCancelled` (and `run()` raises
`PipelineCancelledError`).

### Progress

- **Coarse:** `StageStarted`/`StageCompleted` carry `progress_pct`
  (0–100), derived from `showrunner.events.STAGE_PROGRESS` (plan 0–10,
  assets 10–70, compose 70–75, render 75–100 — weighted by typical
  wall-clock time).
- **Fine:** scene-level events carry `index`/`total`, so within the
  assets stage you can interpolate:
  `pct = 10 + 60 * (index / total)`.

For async hosts, `Pipeline.arun()` wraps the same callback into an
async iterator; the final yielded event is `RenderCompleted`,
`PipelineFailed`, or `PipelineCancelled`.

## 2. Cooperative cancellation

Pass either a `showrunner.CancelToken` (`cancel_token=`) or a plain
`threading.Event` (`cancel_event=`) — if you pass both, either one
trips cancellation. The pipeline checks between stages and between
scenes; in-flight provider calls finish first (no mid-API-call abort).

```python
import threading
from showrunner import Pipeline, PipelineCancelledError

stop = threading.Event()
try:
    pipeline.run("topic", cancel_event=stop)   # another thread: stop.set()
except PipelineCancelledError as e:
    resume_dir = e.work_dir   # None if cancelled before the work dir existed
```

On cancellation the pipeline:

1. stops at the next checkpoint,
2. leaves the **work_dir intact and resumable** — including the
   `showrunner.json` manifest (see below) with the full plan and any
   already-generated assets (TTS audio, scene TSX, clips),
3. emits `PipelineCancelled(work_dir=...)`,
4. raises `PipelineCancelledError` (with `.work_dir`).

## 3. Cost estimation and reconciliation

Follows an **estimate → reserve → reconcile** lifecycle (OpenMontage's
CostTracker model).

### Estimate (before running)

```python
estimate = pipeline.estimate("topic", num_scenes=6, avg_scene_seconds=6)
estimate.total_usd          # figure to reserve against
for stage in estimate.stages:
    print(stage.stage, stage.unit, stage.quantity, stage.usd)
```

`estimate()` makes **no API calls and instantiates no providers**. It
prices per-stage heuristics — LLM tokens (plan + per-scene codegen),
TTS characters, video-generation seconds (the dominant cost for
`ai-video`), local render compute — against static tables in
`showrunner.costs`. Treat it as a conservative budget figure.

### Provider hooks (optional, null defaults)

Every provider ABC exposes optional hooks; existing/third-party
providers that don't implement them keep working:

- `estimate_cost(...) -> float | None` — return a USD figure to
  override the static pricing table (default `None`).
- `get_usage() -> dict` — cumulative actuals since the instance was
  created (default zeros). Keys per role: LLM
  `input_tokens`/`output_tokens`/`calls`, TTS `characters`/`calls`,
  video `video_seconds`/`clips`, render `render_seconds`.

The built-in Anthropic/OpenAI (token counts from API responses),
ElevenLabs (characters), and Gemini/Minimax (generated seconds)
providers report real usage.

### Reconcile (after running)

Actual usage is aggregated per role and surfaced twice:

- on the `RenderCompleted` event: `usage` (dict) and `cost_usd`,
- in the work dir's **`showrunner.json` manifest**.

### The `showrunner.json` manifest

Written into every work_dir (`showrunner.pipeline.MANIFEST_NAME`) and
updated as the run progresses:

```json
{
  "status": "in_progress | completed | cancelled | failed",
  "topic": "...",
  "format": "faceless-explainer",
  "style": "3b1b-dark",
  "title": "...",
  "plan": { "title": "...", "totalDuration": 42, "scenes": [ ... ] },
  "output_path": "/abs/path/out.mp4",
  "usage": { "llm": { "input_tokens": 41200, "output_tokens": 16800, "calls": 9 },
             "tts": { "characters": 1180, "calls": 7 } },
  "cost_usd": 0.38
}
```

`plan` + `status` make a cancelled work_dir resumable; `usage` +
`cost_usd` let the host reconcile actual spend against its
reservation.
