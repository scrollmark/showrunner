"""`showrunner new` — scaffold a persistent project directory."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import click

from showrunner.project import DIMENSIONS, ProjectManifest
from showrunner.workflows import WorkflowSpec


@click.command()
@click.argument("path", type=click.Path())
@click.option("--workflow", default="explainer", help="Workflow (see `showrunner workflows`)")
@click.option("--style", default=None, help="Style preset (defaults to config default_style)")
@click.option("--aspect-ratio", default="9:16", type=click.Choice(sorted(DIMENSIONS)))
@click.option("--voice", default="af_heart", help="TTS voice ID")
@click.option("--speed", default=1.0, type=float, help="TTS speed multiplier")
@click.option("--runtime", default=None, help="Override the workflow's default runtime")
@click.option("--no-install", is_flag=True, help="Skip installing runtime dependencies")
def new(path, workflow, style, aspect_ratio, voice, speed, runtime, no_install):
    """Create a new video project directory.

    Scaffolds the runtime the workflow needs and writes showrunner.json.
    Every other command (`storyboard validate`, `tts`, `compose`, `check`,
    `render`) operates on the directory this creates.
    """
    from showrunner.config import load_config
    from showrunner.styles.resolver import resolve_style

    try:
        spec = WorkflowSpec.load(workflow)
    except FileNotFoundError as e:
        raise click.ClickException(str(e)) from None

    project_dir = Path(path)
    if project_dir.exists() and any(project_dir.iterdir()):
        raise click.ClickException(f"{project_dir} already exists and is not empty.")

    config = load_config()
    style_name = style or config.default_style
    resolved = resolve_style(style_name)  # fail fast on unknown preset

    manifest = ProjectManifest(
        name=project_dir.name,
        workflow=workflow,
        runtime=runtime or spec.runtime,
        style=style_name,
        aspect_ratio=aspect_ratio,
        voice=voice,
        speed=speed,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    project_dir.mkdir(parents=True, exist_ok=True)
    _scaffold_runtime(manifest, project_dir, resolved.preset, install=not no_install)
    manifest.save(project_dir)

    click.echo(f"PROJECT: {project_dir.resolve()}")
    click.echo(f"  workflow: {workflow} · runtime: {manifest.runtime} · style: {style_name}")
    click.echo("Next: write storyboard.json, then `showrunner storyboard validate " f"{project_dir}`.")


def _scaffold_runtime(
    manifest: ProjectManifest, project_dir: Path, preset: dict, *, install: bool
) -> None:
    if manifest.runtime == "remotion":
        from showrunner.providers.render.remotion import RemotionRenderProvider

        provider = RemotionRenderProvider()
        provider.setup(project_dir, install=install)
        provider.write_preset_tokens(project_dir, preset)
    elif manifest.runtime == "hyperframes":
        from showrunner.providers.render.hyperframes import (
            HYPERFRAMES_VERSION,
            HyperframesRenderProvider,
        )

        HyperframesRenderProvider().setup(
            project_dir, width=manifest.width, height=manifest.height, install=install,
        )
        manifest.hyperframes_version = HYPERFRAMES_VERSION
    else:
        raise click.ClickException(
            f"Runtime '{manifest.runtime}' is not available. "
            "Available: remotion, hyperframes"
        )
