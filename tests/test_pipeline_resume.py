"""Tests for Pipeline.run(resume_from=...) + per-scene asset resume."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from showrunner import checkpoints
from showrunner.events import WorkDirReady
from showrunner.pipeline import Pipeline, _jsonable
from showrunner.plan import Plan, Scene


def _make_plan() -> Plan:
    return Plan(
        title="Test Video",
        total_duration=15,
        scenes=[
            Scene(id="hook", duration=5, narration="Hello", visual="Title card"),
            Scene(id="main", duration=10, narration="World", visual="Content"),
        ],
    )


def _make_format(plan: Plan) -> MagicMock:
    fmt = MagicMock()
    fmt.name = "faceless-explainer"
    fmt.preferred_render_provider = "remotion"
    fmt.requires_video_provider = False
    fmt.plan.return_value = plan
    fmt.generate_assets.return_value = {
        "durations": {"hook": 5.0, "main": 10.0},
        "has_audio": True, "width": 1080, "height": 1920,
    }
    return fmt


def _make_providers(output_path: Path) -> dict:
    render = MagicMock()
    render.render.return_value = output_path
    return {"llm": MagicMock(), "tts": MagicMock(), "render": render}


def _run(pipeline_kwargs, fmt, providers):
    """Run the pipeline with the registry + provider factory mocked out."""
    mock_reg = MagicMock()
    mock_reg.get.return_value = fmt
    with patch("showrunner.pipeline.get_registry", return_value=mock_reg), \
         patch.object(Pipeline, "_create_providers", return_value=providers), \
         patch.object(Pipeline, "_resolve_music", return_value=None):
        pipeline = Pipeline(format_name="faceless-explainer")
        return pipeline.run(**pipeline_kwargs)


def _write_wav(path: Path, seconds: float = 1.0, rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))


# ── Fresh runs write checkpoints ─────────────────────────────────────────


def test_fresh_run_writes_all_checkpoints(tmp_path):
    plan = _make_plan()
    fmt = _make_format(plan)
    out = tmp_path / "out.mp4"
    events = []

    result = _run(
        {"topic": "cats", "output_path": out, "on_event": events.append},
        fmt, _make_providers(out),
    )
    assert result == out

    work_dir = next(e.work_dir for e in events if isinstance(e, WorkDirReady))
    for stage in checkpoints.STAGES:
        assert checkpoints.is_stage_completed(work_dir, stage), stage

    # showrunner.json carries the stages summary + replay options.
    meta = json.loads((work_dir / "showrunner.json").read_text())
    assert meta["stages"] == {s: "completed" for s in checkpoints.STAGES}
    assert meta["topic"] == "cats"
    assert meta["options"]["voice"] == "af_heart"

    render_cp = checkpoints.read_checkpoint(work_dir, "render")
    assert render_cp.outputs["output_path"] == str(out)


def test_topic_required_without_resume():
    with pytest.raises(ValueError, match="topic is required"):
        Pipeline().run()


def test_run_with_plan_skips_llm_planner(tmp_path):
    """`plan=` (the CLI's --storyboard) must reach assets/compose/render,
    not just print the plan and stop — see cli/main.py's create command."""
    plan = _make_plan()
    fmt = _make_format(plan)
    out = tmp_path / "out.mp4"
    events = []

    result = _run(
        {"plan": plan, "output_path": out, "on_event": events.append},
        fmt, _make_providers(out),
    )
    assert result == out
    fmt.plan.assert_not_called()

    work_dir = next(e.work_dir for e in events if isinstance(e, WorkDirReady))
    for stage in checkpoints.STAGES:
        assert checkpoints.is_stage_completed(work_dir, stage), stage
    assert Plan.from_json((work_dir / "plan.json").read_text()).title == plan.title


# ── Acceptance: failure mid-assets → resume skips the planner ────────────


def test_resume_after_assets_failure_does_not_reinvoke_planner(tmp_path):
    plan = _make_plan()
    out = tmp_path / "out.mp4"

    # First run: assets stage dies mid-way.
    fmt1 = _make_format(plan)
    fmt1.generate_assets.side_effect = RuntimeError("TTS died mid-run")
    events = []
    with pytest.raises(RuntimeError, match="TTS died"):
        _run(
            {"topic": "cats", "output_path": out, "on_event": events.append},
            fmt1, _make_providers(out),
        )
    work_dir = next(e.work_dir for e in events if isinstance(e, WorkDirReady))

    assert checkpoints.stage_status(work_dir, "plan") == "completed"
    assert checkpoints.stage_status(work_dir, "assets") == "failed"
    failed_cp = checkpoints.read_checkpoint(work_dir, "assets")
    assert "TTS died" in failed_cp.error

    # Resume: planner must NOT be called again (mock called 0 times).
    fmt2 = _make_format(plan)
    result = _run({"resume_from": work_dir, "output_path": out}, fmt2, _make_providers(out))

    assert result == out
    fmt2.plan.assert_not_called()
    fmt2.generate_assets.assert_called_once()
    fmt2.compose.assert_called_once()
    for stage in checkpoints.STAGES:
        assert checkpoints.is_stage_completed(work_dir, stage), stage


def test_resume_passes_plan_from_disk_to_assets(tmp_path):
    """The resumed assets stage receives the persisted plan, not a fresh one."""
    plan = _make_plan()
    out = tmp_path / "out.mp4"

    fmt1 = _make_format(plan)
    fmt1.generate_assets.side_effect = RuntimeError("boom")
    events = []
    with pytest.raises(RuntimeError):
        _run({"topic": "cats", "output_path": out, "on_event": events.append},
             fmt1, _make_providers(out))
    work_dir = next(e.work_dir for e in events if isinstance(e, WorkDirReady))

    fmt2 = _make_format(plan)
    _run({"resume_from": work_dir, "output_path": out}, fmt2, _make_providers(out))
    resumed_plan = fmt2.generate_assets.call_args[0][0]
    assert resumed_plan.title == "Test Video"
    assert [s.id for s in resumed_plan.scenes] == ["hook", "main"]
    # Per-scene resume flag is exposed to the format.
    assert fmt2._resume is True


# ── Acceptance: resume after compose → only render runs ──────────────────


def _completed_through_compose(tmp_path: Path, plan: Plan) -> Path:
    """Build a work_dir whose plan/assets/compose stages are completed."""
    work_dir = tmp_path / "workdir"
    work_dir.mkdir()
    (work_dir / "plan.json").write_text(plan.to_json())
    (work_dir / "showrunner.json").write_text(json.dumps({
        "format": "faceless-explainer",
        "aspect_ratio": "9:16",
        "style": None,
        "topic": "cats",
        "options": {"voice": "af_heart"},
    }))
    checkpoints.mark_stage(work_dir, "plan", checkpoints.STATUS_COMPLETED,
                           outputs={"plan_file": "plan.json"})
    checkpoints.mark_stage(
        work_dir, "assets", checkpoints.STATUS_COMPLETED,
        outputs={"assets": {"durations": {}, "has_audio": True, "width": 1080, "height": 1920}},
    )
    checkpoints.mark_stage(work_dir, "compose", checkpoints.STATUS_COMPLETED)
    return work_dir


def test_resume_after_compose_only_renders(tmp_path):
    plan = _make_plan()
    work_dir = _completed_through_compose(tmp_path, plan)
    out = tmp_path / "out.mp4"

    fmt = _make_format(plan)
    providers = _make_providers(out)
    result = _run({"resume_from": work_dir, "output_path": out}, fmt, providers)

    assert result == out
    fmt.plan.assert_not_called()
    fmt.generate_assets.assert_not_called()
    fmt.compose.assert_not_called()
    providers["render"].render.assert_called_once()
    assert checkpoints.is_stage_completed(work_dir, "render")


def test_resume_fully_completed_run_returns_existing_output(tmp_path):
    plan = _make_plan()
    work_dir = _completed_through_compose(tmp_path, plan)
    out = tmp_path / "out.mp4"
    out.write_bytes(b"fake mp4")
    checkpoints.mark_stage(work_dir, "render", checkpoints.STATUS_COMPLETED,
                           outputs={"output_path": str(out)})

    fmt = _make_format(plan)
    providers = _make_providers(out)
    result = _run({"resume_from": work_dir}, fmt, providers)

    assert result == out
    providers["render"].render.assert_not_called()


def test_resume_nonexistent_work_dir_raises(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        Pipeline().run(resume_from=tmp_path / "nope")


# ── Per-scene asset resume ───────────────────────────────────────────────


def test_faceless_narration_resume_skips_existing_wavs(tmp_path):
    from showrunner.formats.faceless_explainer.assets import generate_all_narrations

    plan = _make_plan()
    _write_wav(tmp_path / "hook.wav", seconds=2.0)

    tts = MagicMock()
    tts.synthesize.return_value = MagicMock(duration=3.0)

    durations = generate_all_narrations(
        plan, tts=tts, output_dir=tmp_path, resume=True,
    )
    # Only the missing scene was synthesized.
    tts.synthesize.assert_called_once()
    assert tts.synthesize.call_args.kwargs["output_path"] == tmp_path / "main.wav"
    assert durations["hook"] == pytest.approx(2.0, abs=0.01)
    assert durations["main"] == 3.0


def test_faceless_scene_code_resume_skips_existing(tmp_path):
    from showrunner.formats.faceless_explainer.assets import generate_all_scene_code

    plan = _make_plan()
    llm = MagicMock()
    llm.generate.return_value = (
        "```tsx\n"
        'import React from "react";\n'
        'import { CenterStack } from "../layouts";\n'
        "export default function Main() {\n"
        '  return <CenterStack title="hi" />;\n'
        "}\n"
        "```"
    )
    written = {}

    generate_all_scene_code(
        plan=plan, style_context="", llm=llm,
        write_fn=lambda sid, code: written.setdefault(sid, code),
        validate_fn=lambda sid, code: (True, ""),
        skip_fn=lambda sid: sid == "hook",  # hook's TSX already on disk
    )
    assert "hook" not in written
    assert "main" in written
    assert llm.generate.call_count == 1


def test_ai_video_clips_resume_skips_existing(tmp_path):
    from showrunner.formats.ai_video.assets import generate_all_clips

    plan = _make_plan()
    existing = tmp_path / "hook.mp4"
    existing.write_bytes(b"clip bytes")

    video = MagicMock()
    clips = generate_all_clips(
        plan, video=video, output_dir=tmp_path, resume=True,
    )
    video.generate.assert_called_once()
    assert video.generate.call_args.kwargs["output_path"] == tmp_path / "main.mp4"
    assert clips == {"hook": existing, "main": tmp_path / "main.mp4"}


def test_ai_video_narration_resume_reads_existing_duration(tmp_path):
    from showrunner.formats.ai_video.assets import generate_all_narrations

    plan = _make_plan()
    _write_wav(tmp_path / "main.wav", seconds=1.5)

    tts = MagicMock()
    tts.synthesize.return_value = MagicMock(duration=4.0)
    durations = generate_all_narrations(plan, tts=tts, output_dir=tmp_path, resume=True)
    tts.synthesize.assert_called_once()
    assert durations["hook"] == 4.0
    assert durations["main"] == pytest.approx(1.5, abs=0.01)


def test_wav_duration_of_corrupt_file_is_none(tmp_path):
    from showrunner.formats.audio_util import wav_duration_seconds

    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav at all")
    assert wav_duration_seconds(bad) is None


def test_jsonable_stringifies_paths():
    assert _jsonable({"clips": {"hook": Path("/a/b.mp4")}, "n": 1, "xs": [Path("/c")]}) == {
        "clips": {"hook": "/a/b.mp4"}, "n": 1, "xs": ["/c"],
    }
