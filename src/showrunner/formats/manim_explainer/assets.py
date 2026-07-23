"""Asset generation for the Manim explainer: Scene code + TTS narration.

Per-scene codegen with a repair loop: static lint (forbidden-API list)
first, then a render attempt via the manim CLI; any traceback is fed
back to the LLM for a fix. This mirrors the render->traceback->revise
loop the LLM-to-Manim literature converges on.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Callable

from showrunner.plan import Plan, Scene
from showrunner.providers.tts.base import TTSProvider

MAX_RETRIES = 3

MANIM_VERSION = "0.20"

# Single source of truth for the forbidden-API list: used verbatim in the
# codegen system prompt AND enforced statically by lint_code() before any
# render attempt. Mostly ManimGL / pre-CE names — the CE/GL split is the
# top hallucination source for LLM-written Manim.
FORBIDDEN_APIS: list[tuple[str, str]] = [
    ("from manimlib", "ManimGL import — this project uses Manim CE; write `from manim import *`"),
    ("import manimlib", "ManimGL import — this project uses Manim CE; write `from manim import *`"),
    ("ShowCreation", "removed in Manim CE — use `Create(...)`"),
    ("TextMobject", "removed in Manim CE — use `Text(...)`"),
    ("TexMobject", "removed in Manim CE — use `Tex(...)` or `MathTex(...)`"),
    ("GraphScene", "removed in Manim CE — build an `Axes(...)` inside a plain `Scene`"),
    ("get_graph", "removed in Manim CE — use `axes.plot(lambda x: ..., ...)`"),
    ("ApplyMethod", "deprecated in Manim CE — use the `.animate` syntax, e.g. `self.play(mob.animate.shift(UP))`"),
    ("CONFIG =", "the CONFIG dict was removed in Manim CE — set attributes directly in construct()"),
]


def _forbidden_api_block() -> str:
    return "\n".join(f"- `{name}` — {hint}" for name, hint in FORBIDDEN_APIS)


CODEGEN_SYSTEM_PROMPT = """You are a senior Manim animator writing ONE Manim scene for a narrated math explainer.

TARGET API — Manim Community Edition v{manim_version}.x ONLY
- Import exactly: `from manim import *`
- NEVER use ManimGL / manimlib or pre-CE APIs. FORBIDDEN (each is an automatic failure):
{forbidden_apis}

SCENE CONTRACT
- Define exactly one class: `class {class_name}(Scene):` with a `construct(self)` method.
- The file must be self-contained: `from manim import *` plus optional
  `import numpy as np` / `import math`. No other imports, no file I/O,
  no network access.
- First line of construct(): `self.camera.background_color = "{background_color}"`

DURATION — the narration for this scene lasts {duration} seconds
- The total scene runtime (sum of all `run_time`s and `self.wait(...)`s)
  MUST be at least {duration} seconds. Budget your animations, then END
  the scene with a `self.wait(...)` that pads the remainder — e.g. if
  animations total 6s and the target is 9s, finish with `self.wait(3)`.
- Always end construct() with a final `self.wait(...)` — never end on a
  `self.play(...)` call.

CANVAS & FRAME BOUNDS
- Output resolution: {width}x{height}. The Manim frame is {frame_height:.1f}
  units tall and {frame_width:.2f} units wide (x in [-{half_width:.2f}, {half_width:.2f}],
  y in [-{half_height:.2f}, {half_height:.2f}]).
- Keep ALL content inside a ~0.5 unit safe margin from every edge.
- Scale text and equations so they fit: use `.scale(...)` or
  `font_size=...`, and `.scale_to_fit_width(...)` for wide equations.

LAYOUT DISCIPLINE (violations cause overlap — the #1 failure mode)
- Position everything RELATIVELY: `.next_to(...)`, `.to_edge(...)`,
  `.to_corner(...)`, `.arrange(...)`, `.move_to(ORIGIN)`, `.shift(UP * 2)`.
- Group related mobjects with `VGroup(...)` and arrange the group —
  do not hand-place members at absolute coordinates.
- NEVER hard-code absolute coordinates like `.move_to([3.7, -2.1, 0])`.
  Direction constants (UP, DOWN, LEFT, RIGHT, UL, UR, DL, DR) with small
  multipliers are fine.
- Before introducing a new large element, FadeOut or shift away elements
  that are done — the frame must never accumulate clutter.
- One focal idea on screen at a time, per the visual layout description.

ANIMATION VOCABULARY (Manim CE v{manim_version})
- Create/draw: `Create`, `Write` (text/equations), `FadeIn`, `GrowFromCenter`, `DrawBorderThenFill`
- Change: `Transform`, `ReplacementTransform`, `TransformMatchingTex`, `FadeTransform`
- Move/restyle: `.animate` syntax — `self.play(mob.animate.shift(UP).set_color(BLUE))`
- Remove: `FadeOut`, `Uncreate`
- Emphasis: `Indicate`, `Circumscribe`, `Flash`, `Wiggle`
- Graphs: `axes = Axes(x_range=[...], y_range=[...])`, `graph = axes.plot(lambda x: ..., color=...)`,
  labels via `axes.get_axis_labels(...)`; `MathTex` for equations.
- Pace with `run_time=` and `self.wait(...)` between beats so the
  animation breathes with the narration.

STYLE CONTEXT (use these colors/mood; Manim color constants or hex strings are both fine):
{style_context}

Return ONLY the Python code inside a single ```python fence. No explanations, no prose."""

CODEGEN_USER_TEMPLATE = """Write the Manim CE scene.

Scene ID: {scene_id}
Class name: {class_name}
Narration duration to fill: {duration} seconds

Narration (what's being said): {narration}
Visual layout description (what to animate, and where): {visual}

Return the complete Python file."""


def scene_class_name(scene_id: str) -> str:
    """Map a snake_case scene id to a valid Manim Scene class name."""
    name = "".join(w.capitalize() for w in re.split(r"[^0-9a-zA-Z]+", scene_id) if w)
    if not name or name[0].isdigit():
        name = f"Scene{name}"
    return name


def _extract_code(text: str) -> str:
    """Extract Python code from markdown fences."""
    match = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def lint_code(code: str, class_name: str) -> list[str]:
    """Static checks before any render attempt. Returns violation messages."""
    violations = []
    for name, hint in FORBIDDEN_APIS:
        if name in code:
            violations.append(f"forbidden API `{name}`: {hint}")
    if f"class {class_name}(" not in code:
        violations.append(f"missing scene class: file must define `class {class_name}(Scene):`")
    if "from manim import" not in code and "import manim" not in code:
        violations.append("missing import: file must start with `from manim import *`")
    if "self.wait(" not in code:
        violations.append(
            "missing `self.wait(...)`: the scene must end with a wait that pads "
            "runtime to the narration duration"
        )
    return violations


def format_violations(violations: list[str]) -> str:
    return "Lint violations:\n" + "\n".join(f"- {v}" for v in violations)


def build_codegen_system_prompt(
    *,
    class_name: str,
    duration: int,
    width: int,
    height: int,
    style_context: str,
    background_color: str = "#000000",
) -> str:
    frame_height = 8.0
    frame_width = frame_height * width / height
    return CODEGEN_SYSTEM_PROMPT.format(
        manim_version=MANIM_VERSION,
        forbidden_apis=_forbidden_api_block(),
        class_name=class_name,
        duration=duration,
        width=width,
        height=height,
        frame_height=frame_height,
        frame_width=frame_width,
        half_width=frame_width / 2,
        half_height=frame_height / 2,
        style_context=style_context,
        background_color=background_color,
    )


def generate_scene_code(
    *,
    scene: Scene,
    style_context: str,
    llm: object,
    validate_fn: Callable[[str, str], tuple[bool, str]],
    width: int = 1080,
    height: int = 1920,
    background_color: str = "#000000",
    quiet: bool = False,
) -> str:
    """Generate + validate Manim code for one scene, with a repair loop.

    `validate_fn(scene_id, code)` writes the code to disk and attempts a
    real render; it returns (ok, error) where `error` is the manim
    traceback on failure. Static lint runs first so obvious ManimGL
    hallucinations never cost a render.
    """
    class_name = scene_class_name(scene.id)

    system = build_codegen_system_prompt(
        class_name=class_name,
        duration=scene.duration,
        width=width,
        height=height,
        style_context=style_context,
        background_color=background_color,
    )

    prompt = CODEGEN_USER_TEMPLATE.format(
        scene_id=scene.id,
        class_name=class_name,
        duration=scene.duration,
        narration=scene.narration,
        visual=scene.visual,
    )

    error = ""
    for attempt in range(MAX_RETRIES + 1):
        response = llm.generate(system=system, prompt=prompt, max_tokens=8000)
        code = _extract_code(response)

        violations = lint_code(code, class_name)
        if violations:
            ok, error = False, format_violations(violations)
        else:
            ok, error = validate_fn(scene.id, code)

        if ok:
            return code

        if attempt < MAX_RETRIES:
            if not quiet:
                print(f"    Scene '{scene.id}' failed (attempt {attempt + 1}), retrying...")
            prompt = (
                "The previous code failed. Fix it.\n\n"
                f"Error:\n{error}\n\n"
                f"Previous code:\n```python\n{code}\n```\n\n"
                "Reminders:\n"
                f"- Manim CE v{MANIM_VERSION}.x only — never ManimGL names\n"
                f"- Exactly one `class {class_name}(Scene):` with construct()\n"
                "- Relative layout only (next_to/arrange/VGroup) — keep everything in frame\n"
                f"- End with `self.wait(...)` so runtime reaches {scene.duration}s\n"
            )

    raise RuntimeError(
        f"Scene '{scene.id}' failed after {MAX_RETRIES} repair attempts:\n{error}"
    )


def generate_all_narrations(
    plan: Plan,
    *,
    tts: TTSProvider,
    output_dir: Path,
    voice: str = "af_heart",
    speed: float = 1.0,
) -> dict[str, float]:
    """Generate TTS narration for all scenes. Returns {scene_id: duration}.

    Each scene's own `voice` (if set) overrides the run's default.

    Extends each scene's planned duration to cover its narration — the
    codegen prompt then targets the extended duration and pads with
    `self.wait(...)`, keeping video and audio in sync at concat time.
    """
    durations = {}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for scene in plan.scenes:
        output_path = output_dir / f"{scene.id}.wav"
        result = tts.synthesize(
            scene.narration, output_path=output_path, voice=scene.voice or voice, speed=speed
        )
        durations[scene.id] = result.duration
        if result.duration > scene.duration:
            scene.duration = math.ceil(result.duration) + 1

    plan.total_duration = sum(s.duration for s in plan.scenes)
    return durations
