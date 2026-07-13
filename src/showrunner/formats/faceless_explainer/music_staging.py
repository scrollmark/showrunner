"""Stage a picked music track into a work dir with a ducking envelope."""

from __future__ import annotations

import shutil
from pathlib import Path

from showrunner.music.ducking import DuckingConfig, compute_envelope, write_envelope_ts
from showrunner.plan import Plan


def stage_music(
    work_dir: Path,
    plan: Plan,
    selection: dict | None,
    preset: dict | None,
    fps: int = 30,
) -> dict | None:
    """Copy the picked track into `public/music/` and compute a
    narration-driven ducking envelope written to
    `src/music/envelope.generated.ts`. The composer wires both into
    a single `<Audio volume={(f) => envelope[f] ?? BASE_VOLUME}>`.
    Returns None if no track was picked."""
    if not selection:
        return None
    audio_path = Path(selection["audio_path"])
    if not audio_path.exists():
        return None

    # Stage audio.
    dest_dir = work_dir / "public" / "music"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / audio_path.name
    if dest.resolve() != audio_path.resolve():
        shutil.copy2(audio_path, dest)

    base_volume = float(selection["volume"])

    # Build narration specs (path + start-frame) on the transition-
    # compressed visual timeline — that way the envelope matches the
    # audio Sequence offsets the composer will emit, and the fade
    # lands on the real end of the last visible scene rather than
    # after a gap of empty-background frames.
    preset = preset or {}
    rhythm = preset.get("rhythm") or {}
    music_cfg = preset.get("music") or {}
    bpm = float(rhythm.get("bpm", 120))
    trans_beats = float(rhythm.get("transitionBeats", 1.0))
    transition_frames = max(
        int(round((60.0 / bpm) * trans_beats * fps)), 1
    )

    narration_dir = work_dir / "public" / "audio"
    narration_specs: list[dict] = []
    compressed = 0
    last_idx = len(plan.scenes) - 1
    for i, scene in enumerate(plan.scenes):
        wav = narration_dir / f"{scene.id}.wav"
        if wav.exists():
            narration_specs.append({"path": wav, "start_frame": compressed})
        compressed += scene.duration * fps - (
            transition_frames if i < last_idx else 0
        )
    narration_frames = compressed

    # Outro tail: keep the music playing for a short beat after
    # narration ends, fading out so the video lands on a resolve
    # instead of hard-cutting. Tail length is derived from the
    # preset's BPM so it aligns to the musical grid.
    outro_beats = float(music_cfg.get("outroBeats", 2.0))
    outro_frames = max(int(round((60.0 / bpm) * outro_beats * fps)), 15)
    total_frames = narration_frames + outro_frames

    envelope = compute_envelope(
        narration_specs=narration_specs,
        total_frames=total_frames,
        fps=fps,
        config=DuckingConfig(base_volume=base_volume),
    )
    # Apply a linear fade over the outro tail so the bed resolves
    # instead of ending mid-phrase.
    fade_start = narration_frames
    fade_len = max(total_frames - fade_start, 1)
    for i in range(fade_start, total_frames):
        t = (i - fade_start) / fade_len
        envelope[i] = envelope[i] * max(0.0, 1.0 - t)
    write_envelope_ts(
        envelope,
        target=work_dir / "src" / "music" / "envelope.generated.ts",
        base_volume=base_volume,
    )

    return {
        "filename": audio_path.name,
        "volume": base_volume,
        "track_id": selection["track"].id,
        "has_envelope": True,
        "extra_frames": outro_frames,
    }
