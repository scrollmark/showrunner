"""Tests for the embeddable Pipeline API: events, callbacks, cancellation."""

from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import MagicMock

import pytest

from showrunner.events import (
    CancelToken,
    PipelineCancelled,
    PipelineCancelledError,
    PipelineEvent,
    PlanReady,
    RenderCompleted,
    StageCompleted,
    StageStarted,
    WorkDirReady,
    emit,
)
from showrunner.config import Config
from showrunner.pipeline import Pipeline
from showrunner.plan import Plan, Scene


def _patch_format(monkeypatch):
    """Helper that patches the format registry to return a mock format
    so dry-run pipelines don't need real LLM/TTS providers."""
    mock_fmt = MagicMock()
    mock_fmt.preferred_render_provider = "remotion"
    mock_fmt.requires_video_provider = False
    mock_fmt.plan.return_value = Plan(title="Test", total_duration=10, scenes=[])

    mock_reg = MagicMock()
    mock_reg.get.return_value = mock_fmt
    monkeypatch.setattr("showrunner.pipeline.get_registry", lambda: mock_reg)
    return mock_fmt


def _patch_providers(monkeypatch, tmp_path, usage: dict | None = None):
    """Patch Pipeline._create_providers with mocks whose render returns
    a real path. `usage` maps role -> get_usage() return dict."""
    usage = usage or {}
    providers: dict = {}
    for role in ("llm", "tts", "render"):
        provider = MagicMock()
        if role in usage:
            provider.get_usage = MagicMock(return_value=usage[role])
        providers[role] = provider
    out = tmp_path / "out.mp4"
    providers["render"].render.return_value = out
    monkeypatch.setattr(
        Pipeline, "_create_providers", lambda self, **kwargs: providers
    )
    return providers


def _full_run_plan() -> Plan:
    return Plan(
        title="Full Run",
        total_duration=12,
        scenes=[
            Scene(id="hook", duration=6, narration="hi", visual="v1"),
            Scene(id="cta", duration=6, narration="bye", visual="v2"),
        ],
    )


def test_emit_swallows_callback_exceptions():
    """User callbacks must never crash the pipeline."""

    def bad_cb(_ev: PipelineEvent) -> None:
        raise RuntimeError("user bug")

    # Should not raise.
    emit(bad_cb, StageStarted(stage="plan"))


def test_emit_no_op_for_none():
    emit(None, StageStarted(stage="plan"))


def test_dry_run_emits_plan_ready(monkeypatch):
    _patch_format(monkeypatch)
    events: list[PipelineEvent] = []
    pipeline = Pipeline(format_name="faceless-explainer", config=Config())

    pipeline.run("a topic", dry_run=True, on_event=events.append)

    types = [type(e).__name__ for e in events]
    assert "StageStarted" in types
    assert "PlanReady" in types
    assert "StageCompleted" in types
    plan_ready = next(e for e in events if isinstance(e, PlanReady))
    assert plan_ready.plan.title == "Test"


def test_cancel_token_pre_run(monkeypatch):
    """A token that's already cancelled bails out with a
    PipelineCancelled event + PipelineCancelledError before
    instantiating any providers."""
    _patch_format(monkeypatch)

    token = CancelToken()
    token.cancel()
    events: list[PipelineEvent] = []
    pipeline = Pipeline(format_name="faceless-explainer", config=Config())

    with pytest.raises(PipelineCancelledError) as exc_info:
        pipeline.run(
            "a topic", dry_run=True, on_event=events.append, cancel_token=token,
        )
    assert any(isinstance(e, PipelineCancelled) for e in events)
    # Cancelled before any work_dir existed — nothing to resume.
    assert exc_info.value.work_dir is None


def test_cancel_token_threadsafe():
    """`CancelToken.cancel()` should be safe across threads."""
    import threading

    token = CancelToken()
    threads = [threading.Thread(target=token.cancel) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert token.is_cancelled is True


def test_arun_yields_events(monkeypatch):
    """Async wrapper yields the same events as the sync callback."""
    _patch_format(monkeypatch)
    pipeline = Pipeline(format_name="faceless-explainer", config=Config())

    async def collect():
        events = []
        async for ev in pipeline.arun("a topic", dry_run=True):
            events.append(ev)
        return events

    events = asyncio.run(collect())
    types = [type(e).__name__ for e in events]
    assert "StageStarted" in types
    assert "PlanReady" in types


def test_event_dataclasses_are_frozen():
    """Events must be immutable so logging/queueing is safe."""
    ev = StageStarted(stage="plan")
    with pytest.raises(Exception):  # FrozenInstanceError or similar
        ev.stage = "render"  # type: ignore[misc]


# ── Event sequence contract (acceptance: mocked full run) ────────────────


def test_full_mocked_run_event_sequence(monkeypatch, tmp_path):
    """The documented event sequence holds for a full mocked run."""
    mock_fmt = _patch_format(monkeypatch)
    mock_fmt.plan.return_value = _full_run_plan()
    _patch_providers(monkeypatch, tmp_path)

    events: list[PipelineEvent] = []
    pipeline = Pipeline(format_name="faceless-explainer", config=Config())
    result = pipeline.run(
        "a topic", music="none", on_event=events.append,
        output_path=tmp_path / "out.mp4",
    )

    assert result == tmp_path / "out.mp4"
    signature = [
        (type(e).__name__, getattr(e, "stage", None)) for e in events
    ]
    assert signature == [
        ("StageStarted", "plan"),
        ("PlanReady", None),
        ("StageCompleted", "plan"),
        ("WorkDirReady", None),
        ("StageStarted", "assets"),
        ("StageCompleted", "assets"),
        ("StageStarted", "compose"),
        ("StageCompleted", "compose"),
        ("StageStarted", "render"),
        ("StageCompleted", "render"),
        ("RenderCompleted", None),
    ]


def test_stage_events_carry_progress_pct(monkeypatch, tmp_path):
    """Stage events expose coarse 0-100 progress, monotonically increasing."""
    mock_fmt = _patch_format(monkeypatch)
    mock_fmt.plan.return_value = _full_run_plan()
    _patch_providers(monkeypatch, tmp_path)

    events: list[PipelineEvent] = []
    Pipeline(format_name="faceless-explainer", config=Config()).run(
        "a topic", music="none", on_event=events.append,
        output_path=tmp_path / "out.mp4",
    )

    pcts = [
        e.progress_pct for e in events
        if isinstance(e, (StageStarted, StageCompleted))
    ]
    assert all(p is not None for p in pcts)
    assert pcts == sorted(pcts)
    assert pcts[0] == 0.0
    assert pcts[-1] == 100.0


# ── Cancellation (acceptance: cancel during assets → resumable dir) ──────


def test_cancel_during_assets_raises_and_leaves_resumable_work_dir(
    monkeypatch, tmp_path
):
    """Cancelling mid-assets raises PipelineCancelledError and leaves a
    work_dir with a showrunner.json manifest holding the plan."""
    mock_fmt = _patch_format(monkeypatch)
    mock_fmt.plan.return_value = _full_run_plan()
    _patch_providers(monkeypatch, tmp_path)

    cancel_event = threading.Event()
    mock_fmt.generate_assets.side_effect = (
        lambda *a, **k: cancel_event.set()  # cancel arrives while assets run
    )

    events: list[PipelineEvent] = []
    pipeline = Pipeline(format_name="faceless-explainer", config=Config())
    with pytest.raises(PipelineCancelledError) as exc_info:
        pipeline.run(
            "a topic", music="none", on_event=events.append,
            cancel_event=cancel_event, output_path=tmp_path / "out.mp4",
        )

    cancelled = [e for e in events if isinstance(e, PipelineCancelled)]
    assert len(cancelled) == 1
    work_dir = exc_info.value.work_dir
    assert work_dir is not None
    assert cancelled[0].work_dir == work_dir
    # Resumable: the manifest survived with the plan + cancelled status.
    manifest = json.loads((work_dir / "showrunner.json").read_text())
    assert manifest["status"] == "cancelled"
    assert manifest["plan"]["title"] == "Full Run"
    assert [s["id"] for s in manifest["plan"]["scenes"]] == ["hook", "cta"]
    # No render happened after cancellation.
    assert not any(isinstance(e, RenderCompleted) for e in events)


def test_cancel_event_and_token_both_honored(monkeypatch, tmp_path):
    """Passing both cancel_token and cancel_event: either one trips."""
    mock_fmt = _patch_format(monkeypatch)
    mock_fmt.plan.return_value = _full_run_plan()
    _patch_providers(monkeypatch, tmp_path)

    token = CancelToken()
    mock_fmt.generate_assets.side_effect = lambda *a, **k: token.cancel()

    with pytest.raises(PipelineCancelledError):
        Pipeline(format_name="faceless-explainer", config=Config()).run(
            "a topic", music="none",
            cancel_token=token, cancel_event=threading.Event(),
            output_path=tmp_path / "out.mp4",
        )


def test_cancel_token_wraps_threading_event():
    ev = threading.Event()
    token = CancelToken(event=ev)
    assert token.is_cancelled is False
    ev.set()
    assert token.is_cancelled is True


def test_arun_cancellation_ends_with_pipeline_cancelled(monkeypatch, tmp_path):
    """The async iterator terminates cleanly on cancellation, with
    PipelineCancelled as the final event (no PipelineFailed)."""
    mock_fmt = _patch_format(monkeypatch)
    mock_fmt.plan.return_value = _full_run_plan()
    _patch_providers(monkeypatch, tmp_path)

    token = CancelToken()
    mock_fmt.generate_assets.side_effect = lambda *a, **k: token.cancel()
    pipeline = Pipeline(format_name="faceless-explainer", config=Config())

    async def collect():
        events = []
        async for ev in pipeline.arun(
            "a topic", music="none", cancel_token=token,
            output_path=tmp_path / "out.mp4",
        ):
            events.append(ev)
        return events

    events = asyncio.run(collect())
    assert isinstance(events[-1], PipelineCancelled)
    assert not any(type(e).__name__ == "PipelineFailed" for e in events)


# ── Usage reporting (acceptance: actuals in showrunner.json) ─────────────


def test_mocked_run_writes_usage_to_manifest_and_done_event(monkeypatch, tmp_path):
    """Provider get_usage() actuals aggregate into showrunner.json and
    onto the RenderCompleted ("done") event with a cost figure."""
    mock_fmt = _patch_format(monkeypatch)
    mock_fmt.plan.return_value = _full_run_plan()
    _patch_providers(
        monkeypatch, tmp_path,
        usage={
            "llm": {"input_tokens": 40_000, "output_tokens": 16_000, "calls": 9},
            "tts": {"characters": 1_200, "calls": 2},
        },
    )

    events: list[PipelineEvent] = []
    pipeline = Pipeline(format_name="faceless-explainer", config=Config())
    pipeline.run(
        "a topic", music="none", on_event=events.append,
        output_path=tmp_path / "out.mp4",
    )

    done = next(e for e in events if isinstance(e, RenderCompleted))
    assert done.usage["llm"]["input_tokens"] == 40_000
    assert done.usage["tts"]["characters"] == 1_200
    # anthropic table: 40k in * $3/M + 16k out * $15/M = 0.12 + 0.24
    assert done.cost_usd == pytest.approx(0.36, abs=1e-6)

    work_dir = next(e for e in events if isinstance(e, WorkDirReady)).work_dir
    manifest = json.loads((work_dir / "showrunner.json").read_text())
    assert manifest["status"] == "completed"
    assert manifest["usage"]["llm"]["output_tokens"] == 16_000
    assert manifest["cost_usd"] == pytest.approx(0.36, abs=1e-6)
    assert manifest["output_path"] == str(tmp_path / "out.mp4")
