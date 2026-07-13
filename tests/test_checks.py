"""Tests for `showrunner check` — the manifest-driven quality gate."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from showrunner.checks import fingerprint, run_checks
from showrunner.cli.main import cli
from showrunner.project import ProjectManifest

CLEAN_SCENE = '''import React from "react";
import {{ CenterStack }} from "../layouts";

export default function {name}() {{
  return <CenterStack title="Hi" body="There" />;
}}
'''

ROOT_TSX = '''import React from "react";
import Hook from "./scenes/Hook";
import FinalCta from "./scenes/FinalCta";
export const RemotionRoot: React.FC = () => null;
'''


def _green_project(tmp_path):
    project = tmp_path / "proj"
    (project / "src" / "scenes").mkdir(parents=True)
    (project / "public" / "audio").mkdir(parents=True)
    ProjectManifest(
        name="proj", workflow="explainer", runtime="remotion", style="3b1b-dark"
    ).save(project)
    scenes = [
        {"id": "hook", "duration": 4, "narration": "a", "visual": "v"},
        {"id": "final_cta", "duration": 8, "narration": "b", "visual": "v"},
        {"id": "s3", "duration": 8, "narration": "c", "visual": "v"},
        {"id": "s4", "duration": 8, "narration": "d", "visual": "v"},
    ]
    (project / "storyboard.json").write_text(json.dumps({
        "title": "T", "totalDuration": 28, "scenes": scenes,
    }))
    narration = {}
    for s in scenes:
        (project / "public" / "audio" / f"{s['id']}.wav").write_bytes(b"RIFF")
        narration[s["id"]] = {"duration": 3.0, "path": f"public/audio/{s['id']}.wav"}
    (project / "narration.json").write_text(json.dumps(narration))
    for s in scenes:
        name = "".join(w.capitalize() for w in s["id"].split("_"))
        (project / "src" / "scenes" / f"{name}.tsx").write_text(
            CLEAN_SCENE.format(name=name)
        )
    root = ROOT_TSX
    for s in scenes[2:]:
        name = "".join(w.capitalize() for w in s["id"].split("_"))
        root += f'\nimport {name} from "./scenes/{name}";'
    (project / "src" / "Root.tsx").write_text(root)
    return project


def _tsc_ok():
    return patch("showrunner.checks.subprocess.run",
                 return_value=MagicMock(returncode=0, stdout="", stderr=""))


def test_check_green_project_passes(tmp_path):
    project = _green_project(tmp_path)
    with _tsc_ok():
        report = run_checks(project)
    assert report["passed"] is True, report
    saved = json.loads((project / "check.json").read_text())
    assert saved["passed"] is True
    assert saved["fingerprint"]
    assert {c["name"] for c in saved["checks"]} == {
        "storyboard", "narration", "scenes", "compose",
    }


def test_check_fails_on_invalid_storyboard(tmp_path):
    project = _green_project(tmp_path)
    sb = json.loads((project / "storyboard.json").read_text())
    sb["scenes"][0]["visual"] = ""
    (project / "storyboard.json").write_text(json.dumps(sb))
    with _tsc_ok():
        report = run_checks(project)
    assert report["passed"] is False
    failed = {c["name"] for c in report["checks"] if not c["passed"]}
    assert "storyboard" in failed


def test_check_fails_on_missing_wav(tmp_path):
    project = _green_project(tmp_path)
    (project / "public" / "audio" / "hook.wav").unlink()
    with _tsc_ok():
        report = run_checks(project)
    failed = {c["name"] for c in report["checks"] if not c["passed"]}
    assert "narration" in failed


def test_check_fails_on_missing_scene_file(tmp_path):
    project = _green_project(tmp_path)
    (project / "src" / "scenes" / "Hook.tsx").unlink()
    with _tsc_ok():
        report = run_checks(project)
    failed = {c["name"] for c in report["checks"] if not c["passed"]}
    assert "scenes" in failed


def test_check_fails_on_type_errors(tmp_path):
    project = _green_project(tmp_path)
    with patch("showrunner.checks.subprocess.run",
               return_value=MagicMock(returncode=1,
                                      stdout="src/scenes/Hook.tsx(2,1): error TS2304",
                                      stderr="")):
        report = run_checks(project)
    failed = {c["name"] for c in report["checks"] if not c["passed"]}
    assert "scenes" in failed


def test_check_fails_when_root_misses_scene_import(tmp_path):
    project = _green_project(tmp_path)
    root = (project / "src" / "Root.tsx").read_text()
    (project / "src" / "Root.tsx").write_text(
        root.replace('import FinalCta from "./scenes/FinalCta";', "")
    )
    with _tsc_ok():
        report = run_checks(project)
    failed = {c["name"] for c in report["checks"] if not c["passed"]}
    assert "compose" in failed


def test_fingerprint_changes_when_scene_changes(tmp_path):
    project = _green_project(tmp_path)
    before = fingerprint(project)
    path = project / "src" / "scenes" / "Hook.tsx"
    path.write_text(path.read_text().replace("Hi", "Hello"))
    assert fingerprint(project) != before


def test_cli_check_json(tmp_path):
    project = _green_project(tmp_path)
    with _tsc_ok():
        result = CliRunner().invoke(cli, ["check", str(project), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True


def test_cli_check_exit_code_on_failure(tmp_path):
    project = _green_project(tmp_path)
    (project / "narration.json").unlink()
    with _tsc_ok():
        result = CliRunner().invoke(cli, ["check", str(project)])
    assert result.exit_code == 1
