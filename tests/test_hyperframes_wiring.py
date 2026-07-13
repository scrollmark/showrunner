"""Wiring tests: hyperframes runtime reachable from new/render/check."""

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from showrunner.checks import CHECKS, CheckContext
from showrunner.cli.main import cli
from showrunner.project import ProjectManifest
from showrunner.providers.render.hyperframes import HYPERFRAMES_VERSION
from showrunner.workflows import WorkflowSpec


def test_new_scaffolds_hyperframes_runtime(tmp_path):
    result = CliRunner().invoke(cli, [
        "new", str(tmp_path / "v"), "--workflow", "explainer",
        "--style", "3b1b-dark", "--runtime", "hyperframes", "--no-install",
    ])
    assert result.exit_code == 0, result.output
    project = tmp_path / "v"
    assert (project / "index.html").exists()
    assert (project / "assets" / "audio").is_dir()
    manifest = json.loads((project / "showrunner.json").read_text())
    assert manifest["runtime"] == "hyperframes"
    assert manifest["hyperframes_version"] == HYPERFRAMES_VERSION


def test_render_dispatches_to_hyperframes(tmp_path):
    project = tmp_path / "v"
    project.mkdir()
    (project / "index.html").write_text("<html></html>")
    ProjectManifest(
        name="v", workflow="explainer", runtime="hyperframes", style="3b1b-dark",
        hyperframes_version=HYPERFRAMES_VERSION,
    ).save(project)
    with patch(
        "showrunner.providers.render.hyperframes.HyperframesRenderProvider.render",
        return_value=Path("o.mp4"),
    ) as render:
        result = CliRunner().invoke(
            cli, ["render", str(project), "-o", str(tmp_path / "o.mp4"), "--force"]
        )
    assert result.exit_code == 0, result.output
    render.assert_called_once()


def _hf_ctx(tmp_path, with_index=True):
    project = tmp_path / "v"
    project.mkdir()
    manifest = ProjectManifest(
        name="v", workflow="explainer", runtime="hyperframes", style="3b1b-dark",
    )
    manifest.save(project)
    if with_index:
        (project / "index.html").write_text("<html></html>")
    return CheckContext(
        project_dir=project, manifest=manifest,
        spec=WorkflowSpec.load("explainer"), storyboard={"scenes": []},
    )


def test_hyperframes_check_passes_through_runtime_gate(tmp_path):
    ctx = _hf_ctx(tmp_path)
    with patch(
        "showrunner.providers.render.hyperframes.HyperframesRenderProvider.check",
        return_value=(True, []),
    ):
        findings = CHECKS["hyperframes"](ctx)
    assert findings == []


def test_hyperframes_check_maps_runtime_findings(tmp_path):
    ctx = _hf_ctx(tmp_path)
    with patch(
        "showrunner.providers.render.hyperframes.HyperframesRenderProvider.check",
        return_value=(False, ["console error on load"]),
    ):
        findings = CHECKS["hyperframes"](ctx)
    assert any("console error" in f.message for f in findings)
    assert all(f.level == "error" for f in findings)


def test_hyperframes_check_requires_index_html(tmp_path):
    ctx = _hf_ctx(tmp_path, with_index=False)
    findings = CHECKS["hyperframes"](ctx)
    assert any(f.code == "missing-composition" for f in findings)
