"""Manim explainer format — 3Blue1Brown-style math animations via Manim CE.

Pipeline shape: LLM plans a spatially-explicit storyboard, the LLM writes
one Manim `Scene` subclass per storyboard scene (render->traceback->revise
repair loop), each scene is rendered to a clip with the `manim` CLI, and
the clips are concatenated + mixed with narration by the FFmpeg render
provider (same composer path as the ai-video format).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from showrunner.feedback import Feedback
from showrunner.formats.base import Format
from showrunner.formats.manim_explainer.assets import (
    generate_all_narrations,
    generate_scene_code,
    scene_class_name,
)
from showrunner.formats.manim_explainer.planner import generate_plan
from showrunner.formats.manim_explainer.renderer import render_scene
from showrunner.plan import Plan

DIMENSIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


class ManimExplainerFormat(Format):
    """Narrated math-animation explainers rendered with Manim CE."""

    name = "manim-explainer"
    description = "Math-animation explainers (Manim CE) with AI narration"
    required_providers = ["llm", "tts", "render"]
    preferred_render_provider = "ffmpeg"
    requires_video_provider = False

    def plan(self, topic: str, style: Any, config: Any, llm: Any) -> Plan:
        return generate_plan(topic, style=style, llm=llm, config=config)

    def generate_assets(self, plan: Plan, providers: dict, work_dir: Path) -> dict:
        llm = providers["llm"]
        tts = providers["tts"]

        aspect_ratio = getattr(self, "_aspect_ratio", "9:16")
        width, height = DIMENSIONS.get(aspect_ratio, (1080, 1920))
        voice = getattr(self, "_voice", "af_heart")
        speed = getattr(self, "_speed", 1.0)

        style = getattr(self, "_style", None)
        style_context = style.to_prompt_context() if style else ""
        background_color = (style.colors.get("background", "#000000") if style else "#000000")

        # Narrations FIRST — scene durations are extended to cover the
        # audio, and the codegen prompt targets the extended duration
        # (padding with self.wait), keeping clips and narration in sync.
        audio_dir = work_dir / "audio"
        durations = generate_all_narrations(
            plan, tts=tts, output_dir=audio_dir, voice=voice, speed=speed,
        )

        scenes_dir = work_dir / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)
        clips_dir = work_dir / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        media_dir = work_dir / "media"

        clips: dict[str, Path] = {}
        total = len(plan.scenes)
        for i, scene in enumerate(plan.scenes, 1):
            print(f"  [{i}/{total}] Animating {scene.id}...")
            scene_path = scenes_dir / f"{scene.id}.py"
            clip_path = clips_dir / f"{scene.id}.mp4"
            class_name = scene_class_name(scene.id)

            def validate_fn(
                sid: str,
                code: str,
                _scene_path: Path = scene_path,
                _clip_path: Path = clip_path,
                _class_name: str = class_name,
            ) -> tuple[bool, str]:
                # The render IS the validation: write the candidate, run
                # manim, and hand any traceback back to the repair loop.
                _scene_path.write_text(code, encoding="utf-8")
                return render_scene(
                    _scene_path, _class_name, _clip_path,
                    media_dir=media_dir, resolution=(width, height),
                )

            generate_scene_code(
                scene=scene,
                style_context=style_context,
                llm=llm,
                validate_fn=validate_fn,
                width=width,
                height=height,
                background_color=background_color,
            )
            clips[scene.id] = clip_path

        return {"clips": clips, "durations": durations, "has_audio": True}

    def compose(self, plan: Plan, assets: dict, work_dir: Path, **kwargs) -> None:
        """Write the FFmpeg concat manifest + scene order (ai-video path)."""
        clips = assets.get("clips", {})
        scene_order = [scene.id for scene in plan.scenes]

        lines = []
        for scene_id in scene_order:
            clip_path = clips.get(scene_id)
            if clip_path and Path(clip_path).exists():
                lines.append(f"file '{clip_path}'")
        concat_path = work_dir / "concat.txt"
        concat_path.write_text("\n".join(lines) + "\n")

        scene_order_path = work_dir / "scene_order.txt"
        scene_order_path.write_text("\n".join(scene_order) + "\n")

    def revise(self, plan: Plan, feedback: Feedback, llm: Any) -> Plan:
        if feedback.edits:
            return Plan.from_dict({**plan.to_dict(), **feedback.edits})
        if feedback.text:
            revised = llm.generate_json(
                system=(
                    "You are a math-explainer storyboard editor. Revise the storyboard "
                    "based on feedback. The visual field is a spatial layout description "
                    "(what's on screen and where) — never code. Return valid JSON."
                ),
                prompt=f"Current storyboard:\n{plan.to_json()}\n\nFeedback: {feedback.text}\n\nReturn revised JSON.",
            )
            return Plan.from_dict(revised)
        return plan
