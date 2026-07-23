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
    captions_dir: Path | None = None,
) -> dict[str, float]:
    """Generate TTS narration for all scenes. Returns {scene_id: duration}.

    Each scene's own `voice` (if set) overrides the run's default —
    e.g. alternating two voices for a two-character dialogue scene.

    With `resume=True`, existing WAVs are kept and their durations are
    read from disk instead of re-synthesizing.

    When `captions_dir` is set, also writes word-level caption JSON
    (`{scene_id}.json`, Caption[] shape) for each scene. On resume,
    surviving caption files are kept; missing ones are regenerated from
    the on-disk WAV (whisper/estimation — TTS word timings are gone).
    """
    durations = {}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for scene in plan.scenes:
        output_path = output_dir / f"{scene.id}.wav"
        result = None
        duration: float | None = None
        if resume and output_path.exists():
            duration = wav_duration_seconds(output_path)
        if duration is None:
            result = tts.synthesize(
                scene.narration, output_path=output_path, voice=scene.voice or voice, speed=speed
            )
            duration = result.duration
        durations[scene.id] = duration
        if captions_dir is not None:
            from showrunner.captions import generate_scene_captions, write_scene_captions
            from showrunner.providers.tts.base import AudioFile

            caption_file = Path(captions_dir) / f"{scene.id}.json"
            if result is None and caption_file.exists():
                continue  # resumed scene with surviving captions
            audio = result or AudioFile(path=output_path, duration=duration)
            captions = generate_scene_captions(narration=scene.narration, audio=audio)
            write_scene_captions(captions_dir, scene.id, captions)

    return durations


# --- clip normalization ------------------------------------------------------

#: Output dimensions per aspect ratio (shared with caption sizing).
DIMENSIONS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


def normalize_clips(
    plan: Plan,
    clips: dict[str, Path],
    *,
    work_dir: Path,
    aspect_ratio: str = "16:9",
    fps: int = 30,
    keep_audio: bool = False,
) -> dict[str, Path]:
    """Conform raw provider clips to the storyboard: trim + crop + fps.

    Video APIs quantize clip length (e.g. Hailuo generates 6s/10s) and some
    only output landscape — without conforming, concatenated video drifts
    ahead of the narration track and vertical runs come out sideways. Each
    clip is re-encoded once into ``clips_norm/``:

    - trimmed to the scene's storyboard duration,
    - cover-cropped (scale up, center crop) to the target aspect's canvas,
    - constant ``fps``, yuv420p, and audio stripped (narration is the audio
      track) unless ``keep_audio`` — the native-audio path (e.g. Veo ASMR).

    Idempotent: a normalized clip newer than its source is reused.
    Returns {scene_id: normalized_path} for the scenes that have clips.
    """
    import subprocess

    width, height = DIMENSIONS.get(aspect_ratio, DIMENSIONS["16:9"])
    norm_dir = Path(work_dir) / "clips_norm"
    norm_dir.mkdir(parents=True, exist_ok=True)

    normalized: dict[str, Path] = {}
    for scene in plan.scenes:
        raw = clips.get(scene.id)
        if not raw or not Path(raw).exists():
            continue
        raw = Path(raw)
        target = norm_dir / f"{scene.id}.mp4"
        if target.exists() and target.stat().st_mtime >= raw.stat().st_mtime:
            normalized[scene.id] = target
            continue
        cmd = [
            "ffmpeg", "-y",
            "-i", str(raw),
            "-t", str(scene.duration),
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps}",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            *([] if keep_audio else ["-an"]),
            str(target),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg normalize failed for {scene.id}:\n{result.stderr}")
        normalized[scene.id] = target
    return normalized
