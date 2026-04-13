"""Faceless explainer video format."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from showrunner.feedback import Feedback
from showrunner.formats.base import Format
from showrunner.formats.faceless_explainer.assets import (
    generate_all_narrations,
    generate_all_scene_code,
)
from showrunner.formats.faceless_explainer.composer import generate_root_tsx
from showrunner.formats.faceless_explainer.planner import generate_plan
from showrunner.plan import Plan
from showrunner.styles.resolver import ResolvedStyle

DIMENSIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


class FacelessExplainerFormat(Format):
    """Animated faceless explainer videos with AI narration and motion graphics."""

    name = "faceless-explainer"
    description = "Animated explainer videos with AI narration and motion graphics"
    required_providers = ["llm", "tts", "render"]

    def plan(self, topic: str, style: Any, config: Any, llm: Any) -> Plan:
        return generate_plan(topic, style=style, llm=llm, config=config)

    def generate_assets(self, plan: Plan, providers: dict, work_dir: Path) -> dict:
        llm = providers["llm"]
        tts = providers["tts"]
        render = providers.get("render")

        aspect_ratio = getattr(self, "_aspect_ratio", "9:16")
        width, height = DIMENSIONS.get(aspect_ratio, (1080, 1920))
        voice = getattr(self, "_voice", "af_heart")
        speed = getattr(self, "_speed", 1.0)
        parallel = getattr(self, "_parallel", False)

        # Materialize the active preset as TypeScript before generating any
        # scene code — scene components import from `./tokens`, which only
        # exists once the preset has been written.
        style = getattr(self, "_style", None)
        if render is not None and style is not None and hasattr(render, "write_preset_tokens"):
            render.write_preset_tokens(work_dir, style.preset)

        # TTS
        audio_dir = work_dir / "public" / "audio"
        durations = generate_all_narrations(plan, tts=tts, output_dir=audio_dir, voice=voice, speed=speed)

        # Scene code
        style_context = style.to_prompt_context() if style else ""

        def write_fn(scene_id: str, code: str) -> Path:
            name = "".join(w.capitalize() for w in scene_id.split("_"))
            path = work_dir / "src" / "scenes" / f"{name}.tsx"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code)
            return path

        def validate_fn(code: str) -> tuple[bool, str]:
            return True, ""  # TODO: wire up render provider validation

        generate_all_scene_code(
            plan=plan, style_context=style_context, llm=llm,
            write_fn=write_fn, validate_fn=validate_fn,
            width=width, height=height, parallel=parallel,
        )

        return {"durations": durations, "has_audio": True, "width": width, "height": height}

    def compose(self, plan: Plan, assets: dict, work_dir: Path, **kwargs) -> None:
        width = assets.get("width", 1080)
        height = assets.get("height", 1920)
        has_audio = assets.get("has_audio", True)
        captions = kwargs.get("captions", False)
        watermark = kwargs.get("watermark", None)

        tsx = generate_root_tsx(
            plan, width=width, height=height, fps=30,
            has_audio=has_audio, captions=captions, watermark=watermark,
        )
        root_path = work_dir / "src" / "Root.tsx"
        root_path.write_text(tsx)

    def revise(self, plan: Plan, feedback: Feedback, llm: Any) -> Plan:
        if feedback.edits:
            return Plan.from_dict({**plan.to_dict(), **feedback.edits})
        if feedback.text:
            revised = llm.generate_json(
                system="You are a video storyboard editor. Revise the storyboard based on feedback. Return valid JSON.",
                prompt=f"Current storyboard:\n{plan.to_json()}\n\nFeedback: {feedback.text}\n\nReturn revised JSON.",
            )
            return Plan.from_dict(revised)
        return plan
