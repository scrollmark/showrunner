"""`showrunner storyboard ...` subcommands."""

from __future__ import annotations

import json
from pathlib import Path

import click

from showrunner.project import ProjectManifest
from showrunner.storyboard import Finding, has_errors, validate_storyboard
from showrunner.workflows import WorkflowSpec


@click.group("storyboard")
def storyboard_cli():
    """Work with a project's storyboard.json."""


def load_project_storyboard(project_dir: Path) -> tuple[ProjectManifest, dict]:
    """Shared loader: manifest + parsed storyboard.json (ClickException on problems)."""
    try:
        manifest = ProjectManifest.load(project_dir)
    except FileNotFoundError as e:
        raise click.ClickException(str(e)) from None
    sb_path = project_dir / "storyboard.json"
    if not sb_path.exists():
        raise click.ClickException(
            f"No storyboard.json in {project_dir}. Author one first (see the workflow skill)."
        )
    try:
        data = json.loads(sb_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise click.ClickException(f"storyboard.json is not valid JSON: {e}") from None
    return manifest, data


def echo_findings(findings: list[Finding], *, as_json: bool, passed_label: str) -> None:
    if as_json:
        click.echo(json.dumps({
            "passed": not has_errors(findings),
            "findings": [f.to_dict() for f in findings],
        }, indent=2))
        return
    if not findings:
        click.echo(passed_label)
        return
    for f in findings:
        where = f" [{f.scene_id}]" if f.scene_id else ""
        click.echo(f"{f.level}[{f.code}]{where}: {f.message}")
    if not has_errors(findings):
        click.echo(passed_label)


@storyboard_cli.command("validate")
@click.argument("project", type=click.Path(exists=True, file_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def validate(project, as_json):
    """Validate storyboard.json against the project's workflow rules."""
    project_dir = Path(project)
    manifest, data = load_project_storyboard(project_dir)
    spec = WorkflowSpec.load(manifest.workflow)
    findings = validate_storyboard(data, spec)
    echo_findings(findings, as_json=as_json, passed_label="storyboard ok")
    if has_errors(findings):
        raise SystemExit(1)
