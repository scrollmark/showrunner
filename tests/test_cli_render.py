"""Tests for `showrunner render` — gated by a fresh passing check."""

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from showrunner.checks import run_checks
from showrunner.cli.main import cli

from tests.test_checks import _green_project, _tsc_ok


def _checked_project(tmp_path):
    project = _green_project(tmp_path)
    with _tsc_ok():
        report = run_checks(project)
    assert report["passed"]
    return project


def _render_patch():
    return patch(
        "showrunner.providers.render.remotion.RemotionRenderProvider.render",
        return_value=Path("out.mp4"),
    )


def test_render_refuses_without_check(tmp_path):
    project = _green_project(tmp_path)
    result = CliRunner().invoke(cli, ["render", str(project), "-o", str(tmp_path / "o.mp4")])
    assert result.exit_code != 0
    assert "showrunner check" in result.output


def test_render_refuses_failed_check(tmp_path):
    project = _checked_project(tmp_path)
    report = json.loads((project / "check.json").read_text())
    report["passed"] = False
    (project / "check.json").write_text(json.dumps(report))
    result = CliRunner().invoke(cli, ["render", str(project), "-o", str(tmp_path / "o.mp4")])
    assert result.exit_code != 0


def test_render_refuses_stale_fingerprint(tmp_path):
    project = _checked_project(tmp_path)
    scene = project / "src" / "scenes" / "Hook.tsx"
    scene.write_text(scene.read_text().replace("Hi", "Changed"))
    result = CliRunner().invoke(cli, ["render", str(project), "-o", str(tmp_path / "o.mp4")])
    assert result.exit_code != 0
    assert "changed" in result.output.lower()


def test_render_force_bypasses_gate(tmp_path):
    project = _green_project(tmp_path)
    with _render_patch() as render:
        result = CliRunner().invoke(
            cli, ["render", str(project), "-o", str(tmp_path / "o.mp4"), "--force"]
        )
    assert result.exit_code == 0, result.output
    render.assert_called_once()


def test_render_runs_after_fresh_check(tmp_path):
    project = _checked_project(tmp_path)
    out = tmp_path / "final.mp4"
    with _render_patch() as render:
        result = CliRunner().invoke(cli, ["render", str(project), "-o", str(out)])
    assert result.exit_code == 0, result.output
    kwargs = render.call_args.kwargs
    assert kwargs["work_dir"] == project
    assert kwargs["output_path"] == out


def test_preview_dispatches_to_runtime(tmp_path):
    project = _green_project(tmp_path)
    with patch(
        "showrunner.providers.render.remotion.RemotionRenderProvider.preview"
    ) as preview:
        result = CliRunner().invoke(cli, ["preview", str(project)])
    assert result.exit_code == 0, result.output
    preview.assert_called_once_with(project)
