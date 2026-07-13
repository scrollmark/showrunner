"""`showrunner audio ...` — audio finishing tools."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv"}


@click.group("audio")
def audio_cli():
    """Audio finishing (loudness normalization)."""


@audio_cli.command("master")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", "output_path", type=click.Path(), required=True)
@click.option("--lufs", default=-14.0, type=float,
              help="Integrated loudness target (short-form platforms sit at -14)")
@click.option("--true-peak", default=-1.5, type=float, help="True-peak ceiling (dBTP)")
def master(input_path, output_path, lufs, true_peak):
    """Normalize loudness to a platform target (default -14 LUFS).

    Works on rendered videos (video stream copied untouched) or bare audio
    files. Run this on the final render before publishing.
    """
    src = Path(input_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    argv = ["ffmpeg", "-y", "-i", str(src),
            "-af", f"loudnorm=I={lufs:.1f}:TP={true_peak:.1f}:LRA=11"]
    if src.suffix.lower() in VIDEO_SUFFIXES:
        argv += ["-c:v", "copy"]
    argv.append(str(out))

    try:
        result = subprocess.run(argv, capture_output=True, text=True)
    except FileNotFoundError:
        raise click.ClickException(
            "ffmpeg not found — audio master needs ffmpeg on PATH."
        ) from None
    if result.returncode != 0:
        raise click.ClickException(f"ffmpeg failed:\n{result.stderr or result.stdout}")
    click.echo(f"mastered → {out} (target {lufs:.1f} LUFS)")
