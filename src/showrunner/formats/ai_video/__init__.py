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
        resume = getattr(self, "_resume", False)

        # Generate video clips
        clips_dir = work_dir / "clips"
        clips = generate_all_clips(
            plan, video=video, output_dir=clips_dir,
            aspect_ratio=aspect_ratio, parallel=parallel, resume=resume,
        )

        # Generate narrations (+ word-level caption JSON when --captions is on)
        audio_dir = work_dir / "audio"
        captions_dir = (work_dir / "captions") if getattr(self, "_captions", False) else None
        durations = generate_all_narrations(
            plan, tts=tts, output_dir=audio_dir, voice=voice, speed=speed,
            resume=resume, captions_dir=captions_dir,
        )

        return {"clips": clips, "durations": durations, "has_audio": True}

    def compose(self, plan: Plan, assets: dict, work_dir: Path, **kwargs) -> None:
        """Write FFmpeg concat file and scene order for the render provider."""
        from showrunner.formats.ai_video.assets import normalize_clips

        clips = assets.get("clips", {})
        scene_order = [scene.id for scene in plan.scenes]

        # Conform raw provider clips to the storyboard (trim to scene
        # duration, crop to the target aspect, constant fps) — providers
        # quantize clip length and may only output landscape, and the
        # stream-copy concat below needs uniform streams anyway.
        aspect_ratio = getattr(self, "_aspect_ratio", "16:9")
        clips = normalize_clips(
            plan, clips, work_dir=work_dir, aspect_ratio=aspect_ratio,
            keep_audio=getattr(self, "_keep_clip_audio", False),
        )

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

        # Word-level captions: turn captions/{scene_id}.json into an ASS
        # subtitle file the FFmpeg render provider burns in.
        if kwargs.get("captions"):
            self._write_captions_ass(plan, work_dir)

    def _write_captions_ass(self, plan: Plan, work_dir: Path) -> Path | None:
        """Build `captions.ass` from per-scene caption JSON.

        Scene offsets are the cumulative clip durations (clips concat
        back-to-back — no transition overlap in this format). Styling
        (font family + text/highlight colors) follows the active preset.
        Karaoke `\\k` tags give the TikTok-style word highlight.
        """
        from showrunner.captions import group_into_pages, load_all_captions
        from showrunner.captions.ass import generate_ass

        data = load_all_captions(work_dir / "captions")
        if not data:
            return None

        pages = []
        offset_ms = 0
        for scene in plan.scenes:
            captions = data.get(scene.id)
            if captions:
                pages.extend(group_into_pages(captions, offset_ms=offset_ms))
            offset_ms += scene.duration * 1000

        style = getattr(self, "_style", None)
        preset = (style.preset if style else None) or {}
        colors = preset.get("colors") or {}
        typography = preset.get("typography") or {}
        role = typography.get("caption") or typography.get("body") or {}

        from showrunner.formats.ai_video.assets import DIMENSIONS

        aspect_ratio = getattr(self, "_aspect_ratio", "16:9")
        width, height = DIMENSIONS.get(aspect_ratio, (1920, 1080))

        ass_text = generate_ass(
            pages,
            width=width,
            height=height,
            font_family=role.get("family", "Inter"),
            font_size=int(role.get("size", 28)) * 2,
            text_color=colors.get("text", "#ffffff"),
            highlight_color=colors.get("accent") or colors.get("primary") or "#facc15",
        )
        target = work_dir / "captions.ass"
        target.write_text(ass_text, encoding="utf-8")
        return target

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
