"""`showrunner tts` — synthesize narration for every storyboard scene."""

from __future__ import annotations

import json
from pathlib import Path

import click

from showrunner.plan import Plan


def audio_dir_for_runtime(runtime: str) -> str:
    """Relative audio directory per runtime layout."""
    return "public/audio" if runtime == "remotion" else "assets/audio"


@click.command()
@click.argument("project", type=click.Path(exists=True, file_okay=False))
@click.option("--voice", default=None, help="Override the project's TTS voice")
@click.option("--speed", default=None, type=float, help="Override the project's TTS speed")
def tts(project, voice, speed):
    """Generate narration WAVs + narration.json from storyboard.json.

    Scene durations stretch when the narration runs longer than planned;
    the updated storyboard is written back so later stages stay in sync.
    """
    from showrunner.cli.storyboard_cmds import load_project_storyboard
    from showrunner.config import load_config
    from showrunner.formats.faceless_explainer.assets import generate_all_narrations
    from showrunner.providers import factory

    project_dir = Path(project)
    manifest, data = load_project_storyboard(project_dir)
    plan = Plan.from_dict(data)

    config = load_config()
    provider = factory.create_tts(
        config.providers.get("tts", "kokoro"), config.provider_config
    )

    audio_rel = audio_dir_for_runtime(manifest.runtime)
    durations = generate_all_narrations(
        plan,
        tts=provider,
        output_dir=project_dir / audio_rel,
        voice=voice or manifest.voice,
        speed=speed or manifest.speed,
    )

    narration = {
        scene_id: {"duration": duration, "path": f"{audio_rel}/{scene_id}.wav"}
        for scene_id, duration in durations.items()
    }
    (project_dir / "narration.json").write_text(
        json.dumps(narration, indent=2) + "\n", encoding="utf-8"
    )
    # Persist stretched durations so compose/check see the same timeline.
    (project_dir / "storyboard.json").write_text(plan.to_json() + "\n", encoding="utf-8")

    click.echo(f"narrated {len(narration)}/{len(plan.scenes)} scenes → narration.json")
    skipped = [s.id for s in plan.scenes if s.id not in narration]
    if skipped:
        click.echo(f"skipped (no narration): {', '.join(skipped)}")
