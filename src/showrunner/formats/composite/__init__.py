"""Composite format — layered/compositing scenes (E4).

A scene's `layers` (see `showrunner.plan.Scene.layers`) describe either a
base clip with PiP/chromakey/static-image overlays on top, or two+ clips
split side-by-side (hstack) / top-bottom (vstack). This format's own work
is entirely in `generate_assets()` — resolving each layer's source (a
generation prompt or a `file://` asset, reusing ai-video's ingestion) and
compositing them into one flat clip per scene via
`providers.render.ffmpeg_compose`. Everything downstream (TTS narration,
captions, concat, render) reuses ai-video's pipeline unchanged, since by
the time `compose()` runs, a composite scene looks exactly like an
ai-video scene: one clip per scene id.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from showrunner.feedback import Feedback
from showrunner.formats.ai_video import AIVideoFormat
from showrunner.formats.ai_video.assets import (
    generate_all_narrations,
    ingest_local_asset,
    is_local_asset,
)
from showrunner.formats.base import Format
from showrunner.plan import Plan
from showrunner.providers.render.ffmpeg_compose import composite_scene
from showrunner.providers.video.base import VideoProvider

#: Mirrors `formats.ai_video.assets.DIMENSIONS` — kept separate rather than
#: imported since it's a small, stable constant and this format has no
#: other dependency on ai-video's internals.
DIMENSIONS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


class CompositeFormat(Format):
    """Layered scenes: base + overlay clips (PiP/chromakey/image), or
    side-by-side split-screen (hstack/vstack)."""

    name = "composite"
    description = "Layered/compositing scenes: picture-in-picture, chromakey, split-screen"
    required_providers = ["llm", "tts", "video", "render"]
    preferred_render_provider = "ffmpeg"
    requires_video_provider = True

    def plan(self, topic: str, style: Any, config: Any, llm: Any) -> Plan:
        raise NotImplementedError(
            "composite has no LLM planner yet — a scene's `layers` structure "
            "(base/pip/chromakey/hstack/vstack roles, rects, sources) needs "
            "hand-authoring. Use `showrunner create --storyboard <plan.json>`."
        )

    def generate_assets(self, plan: Plan, providers: dict, work_dir: Path) -> dict:
        video: VideoProvider = providers["video"]
        aspect_ratio = getattr(self, "_aspect_ratio", "16:9")
        width, height = DIMENSIONS.get(aspect_ratio, DIMENSIONS["16:9"])

        clips_dir = work_dir / "clips"
        layers_dir = work_dir / "layers"
        clips_dir.mkdir(parents=True, exist_ok=True)
        layers_dir.mkdir(parents=True, exist_ok=True)

        clips: dict[str, Path] = {}
        for scene in plan.scenes:
            layer_specs = scene.layers
            if not layer_specs:
                raise ValueError(
                    f"composite scene {scene.id!r} has no `layers` — every scene "
                    "in a composite storyboard must declare layers (see Scene.layers)."
                )
            layer_paths = [
                self._resolve_layer(layer, scene, video=video, aspect_ratio=aspect_ratio, layers_dir=layers_dir)
                for layer in layer_specs
            ]
            clip_path = clips_dir / f"{scene.id}.mp4"
            composite_scene(
                layer_paths, layer_specs,
                output_path=clip_path, width=width, height=height, duration=scene.duration,
            )
            clips[scene.id] = clip_path

        # --no-audio (E5-style): no TTS narration for this run.
        if getattr(self, "_no_audio", False):
            return {"clips": clips, "durations": {}, "has_audio": False}

        tts = providers["tts"]
        voice = getattr(self, "_voice", "af_heart")
        speed = getattr(self, "_speed", 1.0)
        resume = getattr(self, "_resume", False)
        audio_dir = work_dir / "audio"
        captions_dir = (work_dir / "captions") if getattr(self, "_captions", False) else None
        durations = generate_all_narrations(
            plan, tts=tts, output_dir=audio_dir, voice=voice, speed=speed,
            resume=resume, captions_dir=captions_dir,
        )
        return {"clips": clips, "durations": durations, "has_audio": True}

    @staticmethod
    def _resolve_layer(
        layer: dict, scene, *, video: VideoProvider, aspect_ratio: str, layers_dir: Path
    ) -> Path:
        """Resolve one layer's `source` (a generation prompt or a
        `file://` asset) into a file on disk, named so re-running the
        same scene/layer id overwrites rather than accumulates."""
        source = layer["source"]
        if is_local_asset(source):
            suffix = Path(source[len("file://"):]).suffix or ".mp4"
            layer_path = layers_dir / f"{scene.id}-{layer['id']}{suffix}"
            ingest_local_asset(source, layer_path)
        else:
            layer_path = layers_dir / f"{scene.id}-{layer['id']}.mp4"
            video.generate(source, duration=scene.duration, aspect_ratio=aspect_ratio, output_path=layer_path)
        return layer_path

    def compose(self, plan: Plan, assets: dict, work_dir: Path, **kwargs) -> None:
        """Delegate to ai-video's concat/normalize/scene-order logic — by
        this point every scene already has one flat, composited clip, the
        same shape ai-video's own compose() expects."""
        proxy = AIVideoFormat()
        proxy._aspect_ratio = getattr(self, "_aspect_ratio", "16:9")
        proxy._no_audio = getattr(self, "_no_audio", False)
        proxy.compose(plan, assets, work_dir, **kwargs)

    def revise(self, plan: Plan, feedback: Feedback, llm: Any) -> Plan:
        if feedback.edits:
            return Plan.from_dict({**plan.to_dict(), **feedback.edits})
        if feedback.text:
            revised = llm.generate_json(
                system=(
                    "You are a video storyboard editor for a compositing format. "
                    "Each scene has a `layers` list: either one role='base' layer "
                    "followed by 'pip'/'chromakey'/'image' overlays (positioned by "
                    "`rect`, fractions of the canvas 0.0-1.0), or two-plus "
                    "'hstack'/'vstack' layers with no base. Preserve this structure "
                    "when revising. Return valid JSON."
                ),
                prompt=f"Current storyboard:\n{plan.to_json()}\n\nFeedback: {feedback.text}\n\nReturn revised JSON.",
            )
            return Plan.from_dict(revised)
        return plan
