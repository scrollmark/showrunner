"""AI Video format — generates videos using AI video generation APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from showrunner.feedback import Feedback
from showrunner.formats.base import Format
from showrunner.formats.ai_video.assets import generate_all_clips, generate_all_narrations
from showrunner.formats.ai_video.planner import generate_plan
from showrunner.plan import Plan
from showrunner.styles.resolver import ResolvedStyle


class AIVideoFormat(Format):
    """AI-generated video clips with narration."""

    name = "ai-video"
    description = "AI-generated video clips stitched with narration"
    required_providers = ["llm", "tts", "video", "render"]
    preferred_render_provider = "ffmpeg"
    requires_video_provider = True

    def plan(self, topic: str, style: Any, config: Any, llm: Any) -> Plan:
        return generate_plan(topic, style=style, llm=llm, config=config)

    def generate_assets(self, plan: Plan, providers: dict, work_dir: Path) -> dict:
        video = providers["video"]
        tts = providers["tts"]

        aspect_ratio = getattr(self, "_aspect_ratio", "16:9")
        voice = getattr(self, "_voice", "af_heart")
        speed = getattr(self, "_speed", 1.0)
        parallel = getattr(self, "_parallel", False)

        # Generate video clips
        clips_dir = work_dir / "clips"
        clips = generate_all_clips(
            plan, video=video, output_dir=clips_dir,
            aspect_ratio=aspect_ratio, parallel=parallel,
        )

        # Generate narrations
        audio_dir = work_dir / "audio"
        durations = generate_all_narrations(
            plan, tts=tts, output_dir=audio_dir, voice=voice, speed=speed,
        )

        return {"clips": clips, "durations": durations, "has_audio": True}

    def compose(self, plan: Plan, assets: dict, work_dir: Path, **kwargs) -> None:
        """Write FFmpeg concat file and scene order for the render provider."""
        clips = assets.get("clips", {})
        scene_order = [scene.id for scene in plan.scenes]

        # Write concat file
        lines = []
        for scene_id in scene_order:
            clip_path = clips.get(scene_id)
            if clip_path and Path(clip_path).exists():
                lines.append(f"file '{clip_path}'")
        concat_path = work_dir / "concat.txt"
        concat_path.write_text("\n".join(lines) + "\n")

        # Write scene order (for audio mixing)
        scene_order_path = work_dir / "scene_order.txt"
        scene_order_path.write_text("\n".join(scene_order) + "\n")

    def revise(self, plan: Plan, feedback: Feedback, llm: Any) -> Plan:
        if feedback.edits:
            return Plan.from_dict({**plan.to_dict(), **feedback.edits})
        if feedback.text:
            revised = llm.generate_json(
                system="You are a video storyboard editor. Revise the storyboard based on feedback. The visual field should be an AI video generation prompt (describe shots, not code). Return valid JSON.",
                prompt=f"Current storyboard:\n{plan.to_json()}\n\nFeedback: {feedback.text}\n\nReturn revised JSON.",
            )
            return Plan.from_dict(revised)
        return plan
