"""`showrunner render` / `showrunner preview` — runtime dispatch with the check gate."""

from __future__ import annotations

import json
from pathlib import Path

import click

from showrunner.project import ProjectManifest


def _runtime_provider(manifest: ProjectManifest):
    from showrunner.providers import factory

    if manifest.runtime == "remotion":
        return factory.create_render("remotion")
    raise click.ClickException(
        f"Runtime '{manifest.runtime}' is not available. Available: remotion"
    )


def _require_fresh_check(project_dir: Path) -> None:
    from showrunner.checks import fingerprint

    check_path = project_dir / "check.json"
    if not check_path.exists():
        raise click.ClickException(
            "No check.json — run `showrunner check` first (or pass --force)."
        )
    try:
        report = json.loads(check_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise click.ClickException(
            "check.json is unreadable — rerun `showrunner check`."
        ) from None
    if not report.get("passed"):
        raise click.ClickException(
            "Last check FAILED — fix the findings and rerun `showrunner check`."
        )
    if report.get("fingerprint") != fingerprint(project_dir):
        raise click.ClickException(
            "Project changed since the last passing check — rerun `showrunner check`."
        )


@click.command()
@click.argument("project", type=click.Path(exists=True, file_okay=False))
@click.option("--output", "-o", "output_path", type=click.Path(), required=True,
              help="Where to write the mp4")
@click.option("--force", is_flag=True, help="Render even without a fresh passing check")
def render(project, output_path, force):
    """Render the project to video. Requires a fresh passing `showrunner check`."""
    project_dir = Path(project)
    manifest = ProjectManifest.load(project_dir)
    if not force:
        _require_fresh_check(project_dir)

    provider = _runtime_provider(manifest)
    result = provider.render(work_dir=project_dir, output_path=Path(output_path))
    click.echo(f"rendered: {result}")


@click.command()
@click.argument("project", type=click.Path(exists=True, file_okay=False))
def preview(project):
    """Open the runtime's live preview for this project."""
    project_dir = Path(project)
    manifest = ProjectManifest.load(project_dir)
    provider = _runtime_provider(manifest)
    provider.preview(project_dir)
    click.echo("preview opened")
