"""Asset generation for AI video format: video clips + TTS narration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from showrunner.plan import Plan
from showrunner.providers.tts.base import TTSProvider
from showrunner.providers.video.base import VideoProvider


def generate_all_clips(
    plan: Plan,
    *,
    video: VideoProvider,
    output_dir: Path,
    aspect_ratio: str = "16:9",
    parallel: bool = False,
) -> dict[str, Path]:
    """Generate video clips for all scenes. Returns {scene_id: clip_path}."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(plan.scenes)

    if parallel:
        return _generate_clips_parallel(plan, video=video, output_dir=output_dir, aspect_ratio=aspect_ratio, total=total)

    clips = {}
    for i, scene in enumerate(plan.scenes, 1):
        print(f"  [{i}/{total}] Generating clip: {scene.id}...")
        clip_path = output_dir / f"{scene.id}.mp4"
        video.generate(scene.visual, duration=scene.duration, aspect_ratio=aspect_ratio, output_path=clip_path)
        clips[scene.id] = clip_path
    return clips


def _generate_clips_parallel(plan, *, video, output_dir, aspect_ratio, total):
    clips = {}
    errors = []
    with ThreadPoolExecutor(max_workers=min(3, total)) as pool:
        futures = {}
        for i, scene in enumerate(plan.scenes, 1):
            clip_path = output_dir / f"{scene.id}.mp4"
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
) -> dict[str, float]:
    """Generate TTS narration for all scenes. Returns {scene_id: duration}."""
    durations = {}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for scene in plan.scenes:
        output_path = output_dir / f"{scene.id}.wav"
        result = tts.synthesize(scene.narration, output_path=output_path, voice=voice, speed=speed)
        durations[scene.id] = result.duration

    return durations
