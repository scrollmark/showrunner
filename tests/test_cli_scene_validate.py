"""Tests for `showrunner scene validate` — lint + type gate per scene."""

import json
from unittest.mock import patch

from click.testing import CliRunner

from showrunner.cli.main import cli
from showrunner.project import ProjectManifest

CLEAN_SCENE = '''import React from "react";
import { CenterStack } from "../layouts";

export default function Hook() {
  return <CenterStack title="Hi" body="There" />;
}
'''

HEX_SCENE = '''import React from "react";
import { CenterStack } from "../layouts";

export default function Body() {
  return <CenterStack title="Hi" accent={<div style={{ color: "#ff0000" }} />} />;
}
'''


def _project(tmp_path, scene_files=None):
    project = tmp_path / "proj"
    (project / "src" / "scenes").mkdir(parents=True)
    ProjectManifest(
        name="proj", workflow="explainer", runtime="remotion", style="3b1b-dark"
    ).save(project)
    scenes = [
        {"id": "hook", "duration": 4, "narration": "a", "visual": "v"},
        {"id": "body", "duration": 8, "narration": "b", "visual": "v"},
    ]
    (project / "storyboard.json").write_text(json.dumps({
        "title": "T", "totalDuration": 12, "scenes": scenes,
    }))
    for name, code in (scene_files or {}).items():
        (project / "src" / "scenes" / f"{name}.tsx").write_text(code)
    return project


def test_scene_validate_reports_missing_tsx(tmp_path):
    project = _project(tmp_path, scene_files={"Hook": CLEAN_SCENE})  # body missing
    with patch(
        "showrunner.providers.render.remotion.RemotionRenderProvider.validate_scene",
        return_value=(True, ""),
    ):
        result = CliRunner().invoke(cli, ["scene", "validate", str(project), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert any(f["code"] == "missing-scene" and f["scene_id"] == "body"
               for f in payload["findings"])


def test_scene_validate_lint_violation_fails(tmp_path):
    project = _project(tmp_path, scene_files={"Hook": CLEAN_SCENE, "Body": HEX_SCENE})
    with patch(
        "showrunner.providers.render.remotion.RemotionRenderProvider.validate_scene",
        return_value=(True, ""),
    ):
        result = CliRunner().invoke(cli, ["scene", "validate", str(project), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert any(f["code"] == "no-hardcoded-color" and f["scene_id"] == "body"
               for f in payload["findings"])


def test_scene_validate_clean_passes(tmp_path):
    project = _project(
        tmp_path,
        scene_files={"Hook": CLEAN_SCENE, "Body": CLEAN_SCENE.replace("Hook", "Body")},
    )
    with patch(
        "showrunner.providers.render.remotion.RemotionRenderProvider.validate_scene",
        return_value=(True, ""),
    ):
        result = CliRunner().invoke(cli, ["scene", "validate", str(project)])
    assert result.exit_code == 0, result.output


def test_scene_validate_type_errors_surface(tmp_path):
    project = _project(
        tmp_path,
        scene_files={"Hook": CLEAN_SCENE, "Body": CLEAN_SCENE.replace("Hook", "Body")},
    )
    with patch(
        "showrunner.providers.render.remotion.RemotionRenderProvider.validate_scene",
        return_value=(False, "src/scenes/Hook.tsx(3,1): error TS2304"),
    ):
        result = CliRunner().invoke(cli, ["scene", "validate", str(project), "hook", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert any(f["code"] == "type-error" and f["scene_id"] == "hook"
               for f in payload["findings"])
    # single-scene invocation must not report the sibling
    assert not any(f.get("scene_id") == "body" for f in payload["findings"])
