"""`showrunner music ...` subcommands for managing the user's catalog."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import click

from showrunner.music.catalog import SUGGESTED_MOODS, MusicCatalog, Track


def _slugify(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "track"


def _autodetect_bpm(audio_path: Path) -> float | None:
    """Try to detect BPM via librosa if installed. Returns None if the
    optional dep isn't available — the user can always pass --bpm."""
    try:
        import librosa  # type: ignore
    except ImportError:
        return None
    try:
        y, sr = librosa.load(str(audio_path), sr=None, mono=True, duration=60)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        return float(round(tempo))
    except Exception:
        return None


def _autodetect_duration(audio_path: Path) -> float | None:
    """Best-effort duration extraction: ffprobe first, librosa fallback."""
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    try:
        import librosa  # type: ignore
        return float(librosa.get_duration(path=str(audio_path)))
    except Exception:
        return None


@click.group("music")
def music_cli():
    """Manage the local music catalog used for background beds + stingers."""


@music_cli.command("where")
def music_where():
    """Print the catalog directory path."""
    cat = MusicCatalog.load()
    click.echo(str(cat.directory))
    if cat.catalog_file.exists():
        click.echo(f"catalog: {cat.catalog_file}")
    else:
        click.echo("catalog: (not yet initialized)")


@music_cli.command("list")
@click.option("--mood", "mood_filter", default=None, help="Show only tracks matching this mood")
def music_list(mood_filter):
    """List every track in the catalog."""
    cat = MusicCatalog.load()
    tracks = cat.filter_by_moods([mood_filter]) if mood_filter else cat.tracks
    if not tracks:
        click.echo("(catalog is empty; use `showrunner music add <file>` to populate it)")
        return
    # Compact columnar print without pulling in rich.
    id_w = max(len(t.id) for t in tracks)
    for t in tracks:
        bpm = f"{int(t.bpm)}bpm" if t.bpm else "—"
        moods = ",".join(t.moods) if t.moods else "—"
        click.echo(f"{t.id.ljust(id_w)}  {bpm:>7}  {moods}")


@music_cli.command("inspect")
@click.argument("track_id")
def music_inspect(track_id):
    """Print all metadata for a single track."""
    cat = MusicCatalog.load()
    track = cat.get(track_id)
    if not track:
        raise click.ClickException(f"no track with id '{track_id}' in catalog")
    for k, v in track.to_dict().items():
        click.echo(f"{k}: {v}")
    click.echo(f"resolved_path: {cat.resolve_audio_path(track)}")


@music_cli.command("remove")
@click.argument("track_id")
def music_remove(track_id):
    """Remove a track from the catalog. Does NOT delete the audio file."""
    cat = MusicCatalog.load()
    if not cat.remove(track_id):
        raise click.ClickException(f"no track with id '{track_id}' in catalog")
    cat.save()
    click.echo(f"removed '{track_id}' (audio file on disk is untouched)")


@music_cli.command("add")
@click.argument("audio_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--id", "track_id", default=None, help="Override auto-generated id")
@click.option("--mood", "moods", multiple=True,
              help=f"Mood tag (repeat to add several). Suggested: {', '.join(SUGGESTED_MOODS)}")
@click.option("--bpm", type=float, default=None,
              help="Track BPM. If omitted and librosa is installed, auto-detected.")
@click.option("--key", default=None, help='Musical key, e.g. "Am", "F#"')
@click.option("--license", "license_str", default=None,
              help="License description — your record of how you're allowed to use this track.")
@click.option("--source", default=None, help="Where the track came from (Artlist, original, etc.)")
@click.option("--notes", default=None)
@click.option("--no-copy", is_flag=True,
              help="Reference the audio file in place instead of copying into the catalog directory.")
def music_add(audio_file, track_id, moods, bpm, key, license_str, source, notes, no_copy):
    """Add an audio file to the catalog.

    By default the file is copied into `<catalog-dir>/tracks/` so the
    catalog stays self-contained. Use --no-copy to reference the file
    where it already lives.
    """
    src = Path(audio_file).expanduser().resolve()
    cat = MusicCatalog.load()
    if not track_id:
        track_id = _slugify(src.stem)

    if no_copy:
        rel = str(src)  # absolute path; resolve_audio_path leaves absolute paths alone
    else:
        dest_dir = cat.directory / "tracks"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if dest.exists() and dest.resolve() != src:
            raise click.ClickException(f"{dest} already exists; rename the file or use --no-copy")
        shutil.copy2(src, dest)
        rel = str(dest.relative_to(cat.directory))

    if bpm is None:
        click.echo("  detecting bpm... (install `librosa` for auto-detection)", err=True)
        bpm = _autodetect_bpm(src)
        if bpm:
            click.echo(f"  detected: {bpm:.0f}bpm", err=True)

    duration = _autodetect_duration(src)

    track = Track(
        id=track_id,
        path=rel,
        moods=list(moods),
        bpm=bpm,
        key=key,
        duration_seconds=duration,
        license=license_str,
        source=source,
        notes=notes,
    )
    cat.add(track)
    cat.save()
    click.echo(f"added '{track_id}' → {cat.catalog_file}")
