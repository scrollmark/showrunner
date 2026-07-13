"""Tests for storyboard validation (rules from the workflow spec)."""

import json

from click.testing import CliRunner

from showrunner.cli.main import cli
from showrunner.project import ProjectManifest
from showrunner.storyboard import validate_storyboard
from showrunner.workflows import WorkflowSpec


def _spec():
    return WorkflowSpec.load("explainer")


def _storyboard(scenes=None, title="How Rainbows Form"):
    if scenes is None:
        scenes = [
            {"id": f"scene_{i}", "duration": 8, "narration": f"Line {i}.",
             "visual": f"Visual {i}", "transition": "fade"}
            for i in range(5)
        ]
        scenes[0]["id"] = "hook_question"
        scenes[0]["duration"] = 4
    return {"title": title, "totalDuration": sum(s["duration"] for s in scenes),
            "scenes": scenes}


def _errors(findings):
    return [f for f in findings if f.level == "error"]


def test_valid_storyboard_passes():
    findings = validate_storyboard(_storyboard(), _spec())
    assert _errors(findings) == []


def test_missing_title_errors():
    sb = _storyboard()
    del sb["title"]
    codes = [f.code for f in _errors(validate_storyboard(sb, _spec()))]
    assert "missing-title" in codes


def test_bad_scene_id_errors():
    sb = _storyboard()
    sb["scenes"][1]["id"] = "Scene-Two"
    codes = [f.code for f in _errors(validate_storyboard(sb, _spec()))]
    assert "bad-scene-id" in codes


def test_duplicate_scene_id_errors():
    sb = _storyboard()
    sb["scenes"][2]["id"] = sb["scenes"][1]["id"]
    codes = [f.code for f in _errors(validate_storyboard(sb, _spec()))]
    assert "duplicate-scene-id" in codes


def test_scene_duration_out_of_bounds_errors():
    sb = _storyboard()
    sb["scenes"][1]["duration"] = 45  # explainer max is 20
    findings = _errors(validate_storyboard(sb, _spec()))
    assert any(f.code == "scene-duration" and f.scene_id == "scene_1" for f in findings)


def test_scene_count_too_few_errors():
    sb = _storyboard()
    sb["scenes"] = sb["scenes"][:2]  # explainer min is 4
    sb["totalDuration"] = sum(s["duration"] for s in sb["scenes"])
    codes = [f.code for f in _errors(validate_storyboard(sb, _spec()))]
    assert "scene-count" in codes


def test_total_duration_out_of_bounds_errors():
    scenes = [
        {"id": f"s_{i}", "duration": 3, "narration": "x", "visual": "y"}
        for i in range(4)
    ]  # 12s total, explainer min is 20
    codes = [f.code for f in _errors(validate_storyboard(_storyboard(scenes), _spec()))]
    assert "total-duration" in codes


def test_unknown_transition_errors():
    sb = _storyboard()
    sb["scenes"][1]["transition"] = "explode"
    codes = [f.code for f in _errors(validate_storyboard(sb, _spec()))]
    assert "bad-transition" in codes


def test_empty_narration_warns_not_errors():
    sb = _storyboard()
    sb["scenes"][1]["narration"] = ""
    findings = validate_storyboard(sb, _spec())
    assert not any(f.code == "empty-narration" for f in _errors(findings))
    assert any(f.code == "empty-narration" and f.level == "warning" for f in findings)


def test_long_first_scene_warns():
    sb = _storyboard()
    sb["scenes"][0]["duration"] = 10
    findings = validate_storyboard(sb, _spec())
    assert any(f.code == "slow-hook" and f.level == "warning" for f in findings)


def _project(tmp_path, storyboard=None):
    project = tmp_path / "proj"
    project.mkdir()
    ProjectManifest(
        name="proj", workflow="explainer", runtime="remotion", style="3b1b-dark"
    ).save(project)
    if storyboard is not None:
        (project / "storyboard.json").write_text(json.dumps(storyboard))
    return project


def test_cli_validate_ok(tmp_path):
    project = _project(tmp_path, _storyboard())
    result = CliRunner().invoke(cli, ["storyboard", "validate", str(project)])
    assert result.exit_code == 0, result.output
    assert "ok" in result.output.lower()


def test_cli_validate_fails_with_findings(tmp_path):
    sb = _storyboard()
    sb["scenes"][1]["visual"] = ""
    project = _project(tmp_path, sb)
    result = CliRunner().invoke(cli, ["storyboard", "validate", str(project), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert any(f["code"] == "empty-visual" for f in payload["findings"])


def test_cli_validate_missing_storyboard(tmp_path):
    project = _project(tmp_path)
    result = CliRunner().invoke(cli, ["storyboard", "validate", str(project)])
    assert result.exit_code != 0
    assert "storyboard.json" in result.output
