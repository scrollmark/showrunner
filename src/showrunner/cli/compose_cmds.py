"""`showrunner compose` — build the timeline (Root.tsx) from project state."""

from __future__ import annotations

from pathlib import Path

import click


@click.command()
@click.argument("project", type=click.Path(exists=True, file_okay=False))
@click.option("--captions", is_flag=True, help="Include the caption overlay")
@click.option("--watermark", default=None, help="Watermark text overlay")
@click.option("--music", default="auto",
              help="Background music: 'auto' (mood-pick from preset), 'none', or a track id.")
@click.option("--music-volume", type=float, default=None, help="Override music volume (0.0-1.0)")
@click.option("--music-seed", default=None,
              help="Seed for deterministic music picking (defaults to the storyboard title)")
def compose(project, captions, watermark, music, music_volume, music_seed):
    """Generate src/Root.tsx: transitions, narration offsets, music bed.

    Root.tsx is GENERATED — never edit it by hand; rerun compose instead.
    """
    from showrunner.cli.storyboard_cmds import load_project_storyboard
    from showrunner.formats.faceless_explainer.composer import generate_root_tsx
    from showrunner.formats.faceless_explainer.music_staging import stage_music
    from showrunner.music.selection import resolve_music_selection
    from showrunner.plan import Plan
    from showrunner.styles.resolver import resolve_style

    project_dir = Path(project)
    manifest, data = load_project_storyboard(project_dir)
    if manifest.runtime != "remotion":
        raise click.ClickException(
            f"compose targets the remotion runtime; '{manifest.runtime}' projects "
            "author their composition directly (see the workflow skill)."
        )
    if not (project_dir / "narration.json").exists():
        raise click.ClickException(
            "No narration.json — run `showrunner tts` first so the timeline "
            "uses measured narration durations."
        )

    plan = Plan.from_dict(data)
    preset = resolve_style(manifest.style).preset

    try:
        selection = resolve_music_selection(
            music=music, seed=music_seed or plan.title, volume=music_volume, preset=preset,
        )
    except ValueError as e:
        raise click.ClickException(str(e)) from None
    music_ref = stage_music(project_dir, plan, selection, preset)

    tsx = generate_root_tsx(
        plan,
        width=manifest.width,
        height=manifest.height,
        fps=30,
        has_audio=True,
        captions=captions,
        watermark=watermark,
        preset=preset,
        music=music_ref,
    )
    (project_dir / "src" / "Root.tsx").write_text(tsx, encoding="utf-8")

    bits = [f"{len(plan.scenes)} scenes"]
    bits.append(f"music: {music_ref['track_id']}" if music_ref else "music: none")
    click.echo(f"composed src/Root.tsx ({', '.join(bits)})")
