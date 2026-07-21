"""Tests for the bounded render→repair loop (issue #25).

On a RenderProvider failure the pipeline truncates the error output,
builds asset-level Feedback, calls `Format.revise()`, regenerates
assets + recomposes, and re-renders — capped by `config.repair_attempts`.
All providers are mocked; no real renders or API calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from showrunner.config import Config
from showrunner.events import PipelineEvent, PipelineFailed, RenderCompleted, RepairAttempt
from showrunner.pipeline import Pipeline, _find_failing_scene, _truncate_error
from showrunner.plan import Plan, Scene


SYNTHETIC_TSX_ERROR = (
    "Remotion render failed:\n"
    'Error: Unexpected token in src/scenes/HookProblem.tsx (12:3)\n'
    "  > 12 |   <AbsoluteFill style={{>\n"
    "SyntaxError: '}' expected."
)


def _plan() -> Plan:
    return Plan(
        title="Repair Run",
        total_duration=12,
        scenes=[
            Scene(id="hook_problem", duration=6, narration="hi", visual="v1"),
            Scene(id="cta", duration=6, narration="bye", visual="v2"),
        ],
    )


def _patch_format(monkeypatch):
    mock_fmt = MagicMock()
    mock_fmt.preferred_render_provider = "remotion"
    mock_fmt.requires_video_provider = False
    mock_fmt.plan.return_value = _plan()
    mock_fmt.revise.side_effect = lambda plan, feedback, llm: plan

    mock_reg = MagicMock()
    mock_reg.get.return_value = mock_fmt
    monkeypatch.setattr("showrunner.pipeline.get_registry", lambda: mock_reg)
    return mock_fmt


def _patch_providers(monkeypatch, tmp_path, render_side_effect):
    providers = {role: MagicMock() for role in ("llm", "tts", "render")}
    providers["render"].render.side_effect = render_side_effect
    monkeypatch.setattr(
        Pipeline, "_create_providers", lambda self, **kwargs: providers
    )
    return providers


def _run(tmp_path, events=None, config=None):
    pipeline = Pipeline(format_name="faceless-explainer", config=config or Config())
    return pipeline.run(
        "a topic", music="none",
        on_event=events.append if events is not None else None,
        output_path=tmp_path / "out.mp4",
    )


# ── Acceptance: fail once → revise() gets the error → second render passes ─


def test_render_fails_once_revise_called_then_second_render_passes(
    monkeypatch, tmp_path
):
    mock_fmt = _patch_format(monkeypatch)
    out = tmp_path / "out.mp4"
    providers = _patch_providers(
        monkeypatch, tmp_path,
        render_side_effect=[RuntimeError(SYNTHETIC_TSX_ERROR), out],
    )

    events: list[PipelineEvent] = []
    result = _run(tmp_path, events)

    assert result == out
    assert providers["render"].render.call_count == 2

    # revise() got asset-level Feedback carrying the render error text,
    # scoped to the scene identified from the traceback.
    mock_fmt.revise.assert_called_once()
    _plan_arg, feedback, llm = mock_fmt.revise.call_args[0]
    assert feedback.level == "asset"
    assert feedback.scene_id == "hook_problem"
    assert "Unexpected token" in feedback.text
    assert llm is providers["llm"]

    # Assets were regenerated and the composition rebuilt before retry.
    assert mock_fmt.generate_assets.call_count == 2
    assert mock_fmt.compose.call_count == 2

    # One RepairAttempt event, then the run still ends with the "done" event.
    repairs = [e for e in events if isinstance(e, RepairAttempt)]
    assert len(repairs) == 1
    assert repairs[0].attempt == 1
    assert repairs[0].max_attempts == 2
    assert repairs[0].scene_id == "hook_problem"
    assert "Unexpected token" in repairs[0].error
    assert isinstance(events[-1], RenderCompleted)


# ── Acceptance: persistent failure exhausts repair_attempts ────────────────


def test_persistent_failure_exhausts_attempts_and_raises_with_count(
    monkeypatch, tmp_path
):
    mock_fmt = _patch_format(monkeypatch)
    providers = _patch_providers(
        monkeypatch, tmp_path,
        render_side_effect=RuntimeError(SYNTHETIC_TSX_ERROR),
    )

    events: list[PipelineEvent] = []
    with pytest.raises(RuntimeError, match=r"Render failed after 3 attempt\(s\)"):
        _run(tmp_path, events)

    # 1 initial + 2 repairs (default repair_attempts=2), each repair revised.
    assert providers["render"].render.call_count == 3
    assert mock_fmt.revise.call_count == 2
    repairs = [e for e in events if isinstance(e, RepairAttempt)]
    assert [r.attempt for r in repairs] == [1, 2]
    assert all(r.max_attempts == 2 for r in repairs)
    # Terminal failure still surfaces as PipelineFailed, never RenderCompleted.
    assert any(isinstance(e, PipelineFailed) for e in events)
    assert not any(isinstance(e, RenderCompleted) for e in events)


def test_error_message_includes_first_and_final_errors(monkeypatch, tmp_path):
    _patch_format(monkeypatch)
    _patch_providers(
        monkeypatch, tmp_path,
        render_side_effect=[
            RuntimeError("first boom"),
            RuntimeError("second boom"),
            RuntimeError("final boom"),
        ],
    )

    with pytest.raises(RuntimeError) as exc_info:
        _run(tmp_path)

    message = str(exc_info.value)
    assert "repair_attempts=2" in message
    assert "first boom" in message
    assert "final boom" in message


def test_repair_attempts_zero_disables_loop(monkeypatch, tmp_path):
    mock_fmt = _patch_format(monkeypatch)
    providers = _patch_providers(
        monkeypatch, tmp_path,
        render_side_effect=RuntimeError("boom"),
    )

    config = Config.from_dict({"repair_attempts": 0})
    with pytest.raises(RuntimeError, match=r"Render failed after 1 attempt\(s\)"):
        _run(tmp_path, config=config)

    assert providers["render"].render.call_count == 1
    mock_fmt.revise.assert_not_called()


def test_repair_attempts_config_knob_respected(monkeypatch, tmp_path):
    mock_fmt = _patch_format(monkeypatch)
    providers = _patch_providers(
        monkeypatch, tmp_path,
        render_side_effect=RuntimeError("boom"),
    )

    config = Config.from_dict({"repair_attempts": 1})
    with pytest.raises(RuntimeError, match=r"Render failed after 2 attempt\(s\)"):
        _run(tmp_path, config=config)

    assert providers["render"].render.call_count == 2
    assert mock_fmt.revise.call_count == 1


def test_no_repair_events_on_clean_render(monkeypatch, tmp_path):
    mock_fmt = _patch_format(monkeypatch)
    _patch_providers(
        monkeypatch, tmp_path, render_side_effect=[tmp_path / "out.mp4"]
    )

    events: list[PipelineEvent] = []
    _run(tmp_path, events)

    assert not any(isinstance(e, RepairAttempt) for e in events)
    mock_fmt.revise.assert_not_called()


# ── Works for both render providers' error shapes ──────────────────────────


def test_repair_loop_handles_ffmpeg_style_error(monkeypatch, tmp_path):
    """FFmpeg raises the same RuntimeError-with-stderr shape as Remotion;
    the loop is provider-agnostic."""
    mock_fmt = _patch_format(monkeypatch)
    mock_fmt.preferred_render_provider = "ffmpeg"
    mock_fmt.requires_video_provider = False
    out = tmp_path / "out.mp4"
    providers = _patch_providers(
        monkeypatch, tmp_path,
        render_side_effect=[
            RuntimeError("FFmpeg concat failed:\nclips/hook_problem.mp4: Invalid data"),
            out,
        ],
    )

    result = _run(tmp_path)

    assert result == out
    assert providers["render"].render.call_count == 2
    feedback = mock_fmt.revise.call_args[0][1]
    assert feedback.level == "asset"
    assert feedback.scene_id == "hook_problem"
    assert "FFmpeg concat failed" in feedback.text


# ── Helpers: truncation + scene identification ─────────────────────────────


def test_truncate_error_keeps_last_lines():
    blob = "\n".join(f"line {i}" for i in range(200))
    truncated = _truncate_error(blob, max_lines=80)
    lines = truncated.splitlines()
    assert len(lines) == 81  # marker + 80 kept lines
    assert "120 earlier line(s) truncated" in lines[0]
    assert lines[-1] == "line 199"


def test_truncate_error_short_blob_untouched():
    assert _truncate_error("one\ntwo") == "one\ntwo"


def test_long_error_is_truncated_before_revise(monkeypatch, tmp_path):
    mock_fmt = _patch_format(monkeypatch)
    long_error = "\n".join(f"trace frame {i}" for i in range(500)) + "\nActual: bad TSX"
    _patch_providers(
        monkeypatch, tmp_path,
        render_side_effect=[RuntimeError(long_error), tmp_path / "out.mp4"],
    )

    _run(tmp_path)

    feedback = mock_fmt.revise.call_args[0][1]
    assert "Actual: bad TSX" in feedback.text          # tail kept
    assert "trace frame 0" not in feedback.text        # head dropped
    assert "truncated" in feedback.text


def test_find_failing_scene_matches_camelcase_component():
    assert _find_failing_scene(_plan(), "error in src/scenes/HookProblem.tsx") == "hook_problem"


def test_find_failing_scene_matches_snake_case_id():
    assert _find_failing_scene(_plan(), "audio/hook_problem.wav missing") == "hook_problem"


def test_find_failing_scene_none_when_unidentifiable():
    assert _find_failing_scene(_plan(), "generic webpack explosion") is None


def test_config_repair_attempts_default_and_merge():
    assert Config().repair_attempts == 2
    assert Config.from_dict({}).repair_attempts == 2
    assert Config.from_dict({"repair_attempts": 5}).repair_attempts == 5
    # merge() round-trips the knob and accepts overrides.
    assert Config.from_dict({"repair_attempts": 5}).merge({}).repair_attempts == 5
    assert Config().merge({"repair_attempts": 3}).repair_attempts == 3
