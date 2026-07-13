"""Tests for project manifests (showrunner.json) and workflow specs."""

import pytest

from showrunner.project import DIMENSIONS, ProjectManifest
from showrunner.workflows import WorkflowSpec


def test_project_manifest_round_trip(tmp_path):
    manifest = ProjectManifest(
        name="my-video",
        workflow="explainer",
        runtime="remotion",
        style="3b1b-dark",
        aspect_ratio="16:9",
        voice="af_heart",
        speed=1.1,
        created_at="2026-07-13T00:00:00+00:00",
    )
    path = manifest.save(tmp_path)
    assert path.name == "showrunner.json"

    loaded = ProjectManifest.load(tmp_path)
    assert loaded == manifest


def test_project_manifest_dimensions():
    manifest = ProjectManifest(
        name="v", workflow="explainer", runtime="remotion", style="3b1b-dark",
        aspect_ratio="9:16",
    )
    assert (manifest.width, manifest.height) == DIMENSIONS["9:16"]
    assert (manifest.width, manifest.height) == (1080, 1920)


def test_project_manifest_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="showrunner.json"):
        ProjectManifest.load(tmp_path)


def test_workflow_spec_explainer_loads():
    spec = WorkflowSpec.load("explainer")
    assert spec.name == "explainer"
    assert spec.runtime == "remotion"
    stage_names = [s.name for s in spec.stages]
    assert stage_names == ["storyboard", "narration", "scenes", "compose", "render"]
    assert spec.stages[0].produces == "storyboard.json"
    assert spec.stages[0].check == "storyboard"
    assert spec.stages[-1].check is None
    assert spec.constraints["total_duration"] == [20, 120]
    assert spec.constraints["scene_count"] == [4, 10]


def test_workflow_spec_unknown_raises_with_available():
    with pytest.raises(FileNotFoundError, match="explainer"):
        WorkflowSpec.load("no-such-workflow")


def test_workflow_list_all_includes_explainer():
    assert "explainer" in WorkflowSpec.list_all()
