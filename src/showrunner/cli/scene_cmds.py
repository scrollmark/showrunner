"""`showrunner scene ...` — per-scene validation (lint + types)."""

from __future__ import annotations

from pathlib import Path

import click

from showrunner.storyboard import Finding, has_errors


def scene_component_name(scene_id: str) -> str:
    return "".join(w.capitalize() for w in scene_id.split("_"))


def validate_remotion_scenes(project_dir: Path, scene_ids: list[str]) -> list[Finding]:
    """Lint + type-check the given scenes. Pure: returns findings."""
    from showrunner.formats.faceless_explainer.lint import lint_scene
    from showrunner.providers.render.remotion import RemotionRenderProvider

    provider = RemotionRenderProvider()
    findings: list[Finding] = []
    for scene_id in scene_ids:
        path = project_dir / "src" / "scenes" / f"{scene_component_name(scene_id)}.tsx"
        if not path.exists():
            findings.append(Finding(
                "error", "missing-scene",
                f"expected {path.relative_to(project_dir)}", scene_id,
            ))
            continue
        code = path.read_text(encoding="utf-8")
        for v in lint_scene(code):
            findings.append(Finding(
                "error", v.rule, f"line {v.line_number}: {v.explanation}", scene_id,
            ))
        ok, tsc_error = provider.validate_scene(project_dir, scene_id)
        if not ok:
            findings.append(Finding("error", "type-error", tsc_error, scene_id))
    return findings


@click.group("scene")
def scene_cli():
    """Validate a project's scene components."""


@scene_cli.command("validate")
@click.argument("project", type=click.Path(exists=True, file_okay=False))
@click.argument("scene_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def validate(project, scene_id, as_json):
    """Lint + type-check scene components (all scenes, or one SCENE_ID)."""
    from showrunner.cli.storyboard_cmds import echo_findings, load_project_storyboard

    project_dir = Path(project)
    manifest, data = load_project_storyboard(project_dir)
    if manifest.runtime != "remotion":
        click.echo(
            f"scene validate is a remotion-runtime gate; for '{manifest.runtime}' "
            "run `showrunner check` instead."
        )
        return

    scene_ids = [s["id"] for s in data.get("scenes", [])]
    if scene_id:
        if scene_id not in scene_ids:
            raise click.ClickException(
                f"scene '{scene_id}' not in storyboard (has: {', '.join(scene_ids)})"
            )
        scene_ids = [scene_id]

    findings = validate_remotion_scenes(project_dir, scene_ids)
    echo_findings(findings, as_json=as_json, passed_label="scenes ok")
    if has_errors(findings):
        raise SystemExit(1)
