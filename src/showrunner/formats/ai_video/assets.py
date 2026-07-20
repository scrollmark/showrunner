"""Asset generation for AI video format: video clips + TTS narration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from showrunner.formats.audio_util import wav_duration_seconds
from showrunner.plan import Plan
from showrunner.providers.tts.base import TTSProvider
from showrunner.providers.video.base import VideoProvider


def _clip_exists(clip_path: Path) -> bool:
    """A clip counts as done when it's on disk and non-empty."""
    return clip_path.exists() and clip_path.stat().st_size > 0


def generate_all_clips(
    plan: Plan,
    *,
    video: VideoProvider,
    output_dir: Path,
    aspect_ratio: str = "16:9",
    parallel: bool = False,
    resume: bool = False,
) -> dict[str, Path]:
    """Generate video clips for all scenes. Returns {scene_id: clip_path}.

    With `resume=True`, scenes whose clip already exists (from an
    interrupted run) are skipped — video generation is the most expensive
    stage, so re-doing finished clips wastes real money.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(plan.scenes)

    if parallel:
        return _generate_clips_parallel(
            plan, video=video, output_dir=output_dir,
            aspect_ratio=aspect_ratio, total=total, resume=resume,
        )

    clips = {}
    for i, scene in enumerate(plan.scenes, 1):
        clip_path = output_dir / f"{scene.id}.mp4"
        if resume and _clip_exists(clip_path):
            print(f"  [{i}/{total}] Clip exists: {scene.id} — skipping (resume)")
            clips[scene.id] = clip_path
            continue
        print(f"  [{i}/{total}] Generating clip: {scene.id}...")
        video.generate(scene.visual, duration=scene.duration, aspect_ratio=aspect_ratio, output_path=clip_path)
        clips[scene.id] = clip_path
    return clips


def _generate_clips_parallel(plan, *, video, output_dir, aspect_ratio, total, resume=False):
    clips = {}
    errors = []
    with ThreadPoolExecutor(max_workers=min(3, total)) as pool:
        futures = {}
        for i, scene in enumerate(plan.scenes, 1):
            clip_path = output_dir / f"{scene.id}.mp4"
            if resume and _clip_exists(clip_path):
                print(f"  [{i}/{total}] Clip exists: {scene.id} — skipping (resume)")
                clips[scene.id] = clip_path
                continue
            future = pool.submit(
                video.generate, scene.visual,
                duration=scene.duration, aspect_ratio=aspect_ratio, output_path=clip_path,
            )
            futures[future] = (scene, clip_path, i)

        for future in as_completed(futures):
            scene, clip_path, index = futures[future]
            try:
                future.result()
                clips[scene.id] = clip_path
                print(f"  [{index}/{total}] {scene.id} done")
            except Exception as e:
                errors.append(f"{scene.id}: {e}")

    if errors:
        raise RuntimeError(f"{len(errors)} clip(s) failed:\n" + "\n".join(errors))
    return clips


def generate_all_narrations(
    plan: Plan,
    *,
    tts: TTSProvider,
    output_dir: Path,
    voice: str = "af_heart",
    speed: float = 1.0,
    resume: bool = False,
) -> dict[str, float]:
    """Generate TTS narration for all scenes. Returns {scene_id: duration}.

    With `resume=True`, existing WAVs are kept and their durations are
    read from disk instead of re-synthesizing.
    """
    durations = {}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for scene in plan.scenes:
        output_path = output_dir / f"{scene.id}.wav"
        duration: float | None = None
        if resume and output_path.exists():
            duration = wav_duration_seconds(output_path)
        if duration is None:
            result = tts.synthesize(scene.narration, output_path=output_path, voice=voice, speed=speed)
            duration = result.duration
        durations[scene.id] = duration

    return durations
