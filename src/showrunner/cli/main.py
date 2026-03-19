"""Showrunner CLI — AI-powered video generation."""

from __future__ import annotations

from pathlib import Path

import click

from showrunner import __version__


@click.group()
@click.version_option(version=__version__)
def cli():
    """Showrunner — AI-powered video generation framework."""
    pass


@cli.command()
@click.argument("topic", required=False)
@click.option("--topic-file", type=click.Path(exists=True), help="Read topic from file")
@click.option("--format", "format_name", default=None, help="Video format")
@click.option("--style", default=None, help="Style preset name")
@click.option("--override", default=None, help="Free-form style overrides")
@click.option("--model", default=None, help="LLM model override")
@click.option(
    "--aspect-ratio",
    default="9:16",
    type=click.Choice(["9:16", "16:9", "1:1", "4:5"]),
)
@click.option("--voice", default="af_heart", help="TTS voice ID")
@click.option("--speed", default=1.0, type=float, help="TTS speed multiplier")
@click.option("--captions", is_flag=True, help="Burn subtitles into video")
@click.option("--watermark", default=None, help="Watermark text overlay")
@click.option("--output", "output_path", type=click.Path(), default=None)
@click.option("--auto-approve", is_flag=True, help="Skip storyboard review")
@click.option("--no-audio", is_flag=True, help="Skip TTS narration")
@click.option("--dry-run", is_flag=True, help="Generate plan only")
@click.option("--preview", is_flag=True, help="Open Remotion Studio")
@click.option("--parallel", is_flag=True, help="Generate scenes concurrently")
@click.option("--storyboard", type=click.Path(exists=True), help="Load existing storyboard JSON")
@click.option("--regen-scene", default=None, help="Regenerate a specific scene")
@click.option("--render-only", is_flag=True, help="Render from existing scenes")
def create(
    topic,
    topic_file,
    format_name,
    style,
    override,
    model,
    aspect_ratio,
    voice,
    speed,
    captions,
    watermark,
    output_path,
    auto_approve,
    no_audio,
    dry_run,
    preview,
    parallel,
    storyboard,
    regen_scene,
    render_only,
):
    """Create a video from a topic."""
    from showrunner.config import load_config
    from showrunner.pipeline import Pipeline
    from showrunner.plan import Plan

    if topic_file:
        topic = Path(topic_file).read_text().strip()
    if not topic and not storyboard:
        raise click.UsageError("Provide a topic or --storyboard")

    config = load_config()

    if model:
        provider_name = config.providers.get("llm", "anthropic")
        if provider_name not in config.provider_config:
            config.provider_config[provider_name] = {}
        config.provider_config[provider_name]["model"] = model

    pipeline = Pipeline(format_name=format_name or config.default_format, config=config)

    if storyboard:
        plan = Plan.from_json(Path(storyboard).read_text())
        click.echo(f"Loaded storyboard: {plan.title} ({len(plan.scenes)} scenes)")
        return

    click.echo(f"Creating video: {topic}")
    click.echo(f"  Style: {style or config.default_style}")
    click.echo(f"  Format: {format_name or config.default_format}")
    click.echo()

    result = pipeline.run(
        topic,
        style=style,
        style_override=override,
        output_path=Path(output_path) if output_path else None,
        aspect_ratio=aspect_ratio,
        voice=voice,
        speed=speed,
        captions=captions,
        watermark=watermark,
        parallel=parallel,
        auto_approve=auto_approve,
        no_audio=no_audio,
        dry_run=dry_run,
        preview=preview,
    )

    if dry_run:
        click.echo(f"\nDry run complete. Plan: {result.title}")
        click.echo(result.to_json())
    elif preview:
        click.echo("\nRemortion Studio opened for preview.")
    else:
        click.echo(f"\nVideo rendered: {result}")


@cli.command()
@click.argument("plan_path", type=click.Path(exists=True))
@click.option("--output", "output_path", type=click.Path(), default=None)
@click.option("--captions", is_flag=True)
@click.option("--watermark", default=None)
def render(plan_path, output_path, captions, watermark):
    """Render a saved plan to video."""
    click.echo(f"Rendering {plan_path}...")


@cli.command()
def formats():
    """List available video formats."""
    from showrunner.formats.registry import get_registry

    registry = get_registry()
    for name in registry.list():
        fmt = registry.get(name)
        click.echo(f"  {name}: {fmt.description}")


@cli.command()
def styles():
    """List available style presets."""
    from showrunner.styles.resolver import list_presets_detailed

    for preset in list_presets_detailed():
        click.echo(f"  {preset['name']}: {preset['description']}")


@cli.command()
def voices():
    """List available TTS voices."""
    from showrunner.providers.tts.kokoro import VOICES

    for v in VOICES:
        click.echo(f"  {v['id']}: {v['name']} — {v['description']}")


@cli.command()
def init():
    """Create a .showrunner.yaml config file."""
    import yaml

    config_path = Path.cwd() / ".showrunner.yaml"
    if config_path.exists():
        click.echo(f"Config already exists: {config_path}")
        return
    default = {
        "default_format": "faceless-explainer",
        "default_style": "3b1b-dark",
        "providers": {"llm": "anthropic", "tts": "kokoro", "render": "remotion"},
        "anthropic": {"model": "claude-sonnet-4-5-20250929"},
        "kokoro": {"voice": "af_heart", "speed": 1.0},
        "output": {"aspect_ratio": "9:16", "captions": False},
    }
    with open(config_path, "w") as f:
        yaml.dump(default, f, default_flow_style=False, sort_keys=False)
    click.echo(f"Created {config_path}")


@cli.command()
def providers():
    """List configured providers."""
    from showrunner.config import load_config

    config = load_config()
    click.echo("Configured providers:")
    for category, name in config.providers.items():
        click.echo(f"  {category}: {name}")
