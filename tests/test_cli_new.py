"""Tests for `showrunner new` project scaffolding."""

import json
from unittest.mock import patch

from click.testing import CliRunner

from showrunner.cli.main import cli


def _invoke_new(tmp_path, *extra, no_install=True):
    runner = CliRunner()
    args = ["new", str(tmp_path / "my-video"), "--workflow", "explainer",
            "--style", "3b1b-dark"]
    if no_install:
        args.append("--no-install")
    args.extend(extra)
    return runner.invoke(cli, args)


def test_new_scaffolds_remotion_project(tmp_path):
    result = _invoke_new(tmp_path)
    assert result.exit_code == 0, result.output

    project = tmp_path / "my-video"
    assert f"PROJECT: {project.resolve()}" in result.output

    manifest = json.loads((project / "showrunner.json").read_text())
    assert manifest["workflow"] == "explainer"
    assert manifest["runtime"] == "remotion"
    assert manifest["style"] == "3b1b-dark"
    assert manifest["aspect_ratio"] == "9:16"
    assert manifest["created_at"]

    # Remotion scaffold: template + generated preset tokens + asset dirs.
    assert (project / "package.json").exists()
    assert (project / "src" / "tokens" / "preset.generated.ts").exists()
    assert (project / "src" / "scenes").is_dir()
    assert (project / "public" / "audio").is_dir()


def test_new_installs_node_deps_by_default(tmp_path):
    with patch("showrunner.providers.render.remotion.subprocess.run") as run:
        run.return_value.returncode = 0
        result = _invoke_new(tmp_path, no_install=False)
    assert result.exit_code == 0, result.output
    npm_calls = [c for c in run.call_args_list if c.args[0][:2] == ["npm", "install"]]
    assert npm_calls, "expected an npm install invocation"


def test_new_refuses_existing_nonempty_dir(tmp_path):
    target = tmp_path / "my-video"
    target.mkdir()
    (target / "something.txt").write_text("hi")
    result = _invoke_new(tmp_path)
    assert result.exit_code != 0
    assert "exists" in result.output


def test_new_unknown_workflow_fails(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["new", str(tmp_path / "v"), "--workflow", "nope", "--no-install"]
    )
    assert result.exit_code != 0
    assert "explainer" in result.output  # lists available workflows
