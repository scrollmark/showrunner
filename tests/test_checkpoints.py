"""Tests for per-stage checkpoint files (showrunner.checkpoints)."""

from __future__ import annotations

import json

import pytest

from showrunner.checkpoints import (
    STAGES,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    Checkpoint,
    checkpoint_path,
    first_incomplete_stage,
    is_stage_completed,
    mark_stage,
    read_checkpoint,
    stage_status,
    stages_summary,
)


def test_stage_order():
    assert STAGES == ("plan", "assets", "compose", "render")


def test_missing_checkpoint_is_pending(tmp_path):
    assert read_checkpoint(tmp_path, "plan") is None
    assert stage_status(tmp_path, "plan") == STATUS_PENDING
    assert not is_stage_completed(tmp_path, "plan")


def test_mark_in_progress_stamps_started_at(tmp_path):
    cp = mark_stage(tmp_path, "plan", STATUS_IN_PROGRESS)
    assert cp.status == STATUS_IN_PROGRESS
    assert cp.started_at is not None
    assert cp.completed_at is None
    assert checkpoint_path(tmp_path, "plan").exists()


def test_mark_completed_roundtrip(tmp_path):
    mark_stage(tmp_path, "assets", STATUS_IN_PROGRESS)
    mark_stage(tmp_path, "assets", STATUS_COMPLETED, outputs={"assets": {"has_audio": True}})

    cp = read_checkpoint(tmp_path, "assets")
    assert cp is not None
    assert cp.status == STATUS_COMPLETED
    assert cp.started_at is not None
    assert cp.completed_at is not None
    assert cp.error is None
    assert cp.outputs == {"assets": {"has_audio": True}}
    assert is_stage_completed(tmp_path, "assets")

    # File is valid JSON with the documented schema keys.
    raw = json.loads(checkpoint_path(tmp_path, "assets").read_text())
    assert set(raw) == {"stage", "status", "started_at", "completed_at", "error", "outputs"}


def test_mark_failed_records_error(tmp_path):
    mark_stage(tmp_path, "render", STATUS_IN_PROGRESS)
    cp = mark_stage(tmp_path, "render", STATUS_FAILED, error="ffmpeg exploded")
    assert cp.status == STATUS_FAILED
    assert cp.error == "ffmpeg exploded"
    assert cp.completed_at is not None


def test_reinprogress_clears_previous_failure(tmp_path):
    mark_stage(tmp_path, "compose", STATUS_FAILED, error="boom")
    cp = mark_stage(tmp_path, "compose", STATUS_IN_PROGRESS)
    assert cp.error is None
    assert cp.completed_at is None


def test_outputs_merge(tmp_path):
    mark_stage(tmp_path, "render", STATUS_IN_PROGRESS, outputs={"a": 1})
    cp = mark_stage(tmp_path, "render", STATUS_COMPLETED, outputs={"b": 2})
    assert cp.outputs == {"a": 1, "b": 2}


def test_invalid_stage_and_status_raise(tmp_path):
    with pytest.raises(ValueError, match="Unknown stage"):
        mark_stage(tmp_path, "not-a-stage", STATUS_COMPLETED)
    with pytest.raises(ValueError, match="Unknown status"):
        mark_stage(tmp_path, "plan", "definitely-not-a-status")


def test_corrupt_checkpoint_reads_as_none(tmp_path):
    checkpoint_path(tmp_path, "plan").write_text("{not json")
    assert read_checkpoint(tmp_path, "plan") is None
    assert stage_status(tmp_path, "plan") == STATUS_PENDING


def test_stages_summary_and_first_incomplete(tmp_path):
    assert first_incomplete_stage(tmp_path) == "plan"
    mark_stage(tmp_path, "plan", STATUS_COMPLETED)
    mark_stage(tmp_path, "assets", STATUS_COMPLETED)
    assert first_incomplete_stage(tmp_path) == "compose"
    assert stages_summary(tmp_path) == {
        "plan": "completed",
        "assets": "completed",
        "compose": "pending",
        "render": "pending",
    }
    for stage in STAGES:
        mark_stage(tmp_path, stage, STATUS_COMPLETED)
    assert first_incomplete_stage(tmp_path) is None


def test_mark_stage_syncs_showrunner_json(tmp_path):
    """Acceptance: showrunner.json gains a `stages` summary."""
    (tmp_path / "showrunner.json").write_text(json.dumps({"format": "faceless-explainer"}))
    mark_stage(tmp_path, "plan", STATUS_COMPLETED)
    meta = json.loads((tmp_path / "showrunner.json").read_text())
    assert meta["format"] == "faceless-explainer"  # existing keys preserved
    assert meta["stages"]["plan"] == "completed"
    assert meta["stages"]["render"] == "pending"


def test_mark_stage_without_showrunner_json_is_fine(tmp_path):
    # Checkpoints are the source of truth; a missing meta file is tolerated.
    mark_stage(tmp_path, "plan", STATUS_COMPLETED)
    assert not (tmp_path / "showrunner.json").exists()


def test_checkpoint_dataclass_roundtrip():
    cp = Checkpoint(stage="plan", status=STATUS_COMPLETED, outputs={"plan_file": "plan.json"})
    assert Checkpoint.from_dict(cp.to_dict()) == cp
