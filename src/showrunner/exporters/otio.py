"""OpenTimelineIO exporter.

Maps a showrunner Plan + work_dir into an OTIO Timeline so the cut can be
opened in DaVinci Resolve / Premiere / Final Cut, or round-tripped through
any OTIO adapter (FCPXML, EDL, AAF, ...).

Layout assumptions (matches what Pipeline writes today):
  - ai-video:           clips/{scene_id}.mp4   audio/{scene_id}.wav
  - faceless-explainer: scenes_split/{scene_id}.mp4 (produced on demand by
                        split_final_mp4_by_scenes), public/audio/{scene_id}.wav
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from showrunner.plan import Plan, Scene

if TYPE_CHECKING:
    import opentimelineio as otio  # noqa: F401


_TRANSITION_MAP = {
    "fade": "SMPTE_Dissolve",
    "dissolve": "SMPTE_Dissolve",
    "crossfade": "SMPTE_Dissolve",
}


def plan_to_timeline(
    plan: Plan,
    work_dir: Path,
    *,
    format_name: str,
    fps: int = 30,
    transition_seconds: float = 0.5,
):
    """Build an OTIO Timeline from a Plan and a populated work_dir.

    Raises FileNotFoundError if a per-scene video or audio asset is missing.
    """
    import opentimelineio as otio
    from opentimelineio.opentime import RationalTime, TimeRange
    from opentimelineio.schema import (
        Clip,
        ExternalReference,
        Timeline,
        Track,
        TrackKind,
        Transition,
        TransitionTypes,
    )

    work_dir = Path(work_dir)
    video_dir, audio_dir = _asset_dirs(work_dir, format_name)

    tl = Timeline(name=plan.title)
    tl.metadata["showrunner"] = {
        "format": format_name,
        "fps": fps,
        "plan_total_duration": plan.total_duration,
    }
    video_track = Track(name="V1", kind=TrackKind.Video)
    audio_track = Track(name="A1", kind=TrackKind.Audio)
    tl.tracks.append(video_track)
    tl.tracks.append(audio_track)

    for i, scene in enumerate(plan.scenes):
        video_path = video_dir / f"{scene.id}.mp4"
        audio_path = audio_dir / f"{scene.id}.wav"
        if not video_path.exists():
            raise FileNotFoundError(
                f"Missing per-scene video for '{scene.id}': {video_path}. "
                f"Run the render first (and split_final_mp4_by_scenes for "
                f"faceless-explainer)."
            )
        if not audio_path.exists():
            raise FileNotFoundError(
                f"Missing per-scene audio for '{scene.id}': {audio_path}"
            )

        duration_frames = max(int(round(scene.duration * fps)), 1)
        clip_range = TimeRange(
            start_time=RationalTime(0, fps),
            duration=RationalTime(duration_frames, fps),
        )

        v_clip = Clip(
            name=scene.id,
            media_reference=ExternalReference(
                target_url=video_path.absolute().as_uri(),
                available_range=clip_range,
            ),
            source_range=clip_range,
        )
        v_clip.metadata["showrunner"] = {
            "scene_id": scene.id,
            "narration": scene.narration,
            "visual": scene.visual,
        }

        # Transition before this clip (skip on the first scene).
        if i > 0 and scene.transition and scene.transition.lower() != "cut":
            tt = _TRANSITION_MAP.get(scene.transition.lower())
            if tt:
                offset = RationalTime(
                    max(int(round(transition_seconds * fps / 2)), 1), fps
                )
                video_track.append(
                    Transition(
                        transition_type=getattr(TransitionTypes, "SMPTE_Dissolve", tt),
                        in_offset=offset,
                        out_offset=offset,
                    )
                )

        video_track.append(v_clip)

        a_clip = Clip(
            name=f"{scene.id}_narration",
            media_reference=ExternalReference(
                target_url=audio_path.absolute().as_uri(),
                available_range=clip_range,
            ),
            source_range=clip_range,
        )
        audio_track.append(a_clip)

    return tl


def export(
    work_dir: Path,
    output_path: Path,
    *,
    adapter: str | None = None,
    fps: int = 30,
) -> Path:
    """Export a finished work_dir to OTIO (or any installed adapter).

    Reads work_dir/plan.json and work_dir/showrunner.json (written by
    Pipeline.run). For faceless-explainer, splits the final mp4 into
    per-scene clips on demand.
    """
    import opentimelineio as otio

    work_dir = Path(work_dir)
    plan = Plan.from_json((work_dir / "plan.json").read_text(encoding="utf-8"))
    meta = json.loads((work_dir / "showrunner.json").read_text(encoding="utf-8"))
    format_name = meta["format"]

    if format_name == "faceless-explainer":
        final_mp4 = _find_final_mp4(work_dir, meta)
        split_final_mp4_by_scenes(final_mp4, plan, work_dir / "scenes_split")

    tl = plan_to_timeline(plan, work_dir, format_name=format_name, fps=fps)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if adapter:
        otio.adapters.write_to_file(tl, str(output_path), adapter_name=adapter)
    else:
        otio.adapters.write_to_file(tl, str(output_path))
    return output_path


def split_final_mp4_by_scenes(
    final_mp4: Path,
    plan: Plan,
    out_dir: Path,
) -> dict[str, Path]:
    """Split a single rendered mp4 into per-scene mp4s using ffmpeg stream-copy.

    Returns {scene_id: Path}. Idempotent: skips scenes whose split already exists.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Path] = {}
    cursor = 0.0
    for scene in plan.scenes:
        out = out_dir / f"{scene.id}.mp4"
        if not out.exists():
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{cursor:.3f}",
                "-i", str(final_mp4),
                "-t", f"{scene.duration:.3f}",
                "-c", "copy",
                str(out),
            ]
            subprocess.run(cmd, check=True)
        results[scene.id] = out
        cursor += scene.duration
    return results


def _asset_dirs(work_dir: Path, format_name: str) -> tuple[Path, Path]:
    if format_name == "ai-video":
        return work_dir / "clips", work_dir / "audio"
    if format_name == "faceless-explainer":
        return work_dir / "scenes_split", work_dir / "public" / "audio"
    raise ValueError(f"Unknown format for export: {format_name!r}")


def _find_final_mp4(work_dir: Path, meta: dict) -> Path:
    """Locate the rendered final mp4 for a faceless-explainer work_dir."""
    explicit = meta.get("output_path")
    if explicit and Path(explicit).exists():
        return Path(explicit)
    # Fall back to the conventional cwd/output/<slug>.mp4 — and if not
    # there, scan the work_dir for any mp4 the user may have placed.
    candidates = sorted(work_dir.glob("*.mp4"))
    if candidates:
        return candidates[0]
    raise FileNotFoundError(
        "Could not locate the rendered mp4 for this work_dir. "
        "Pass --final-mp4 explicitly or render first."
    )
