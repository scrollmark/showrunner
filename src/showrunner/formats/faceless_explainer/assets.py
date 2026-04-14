"""Asset generation: scene code (TSX) + TTS narration."""

from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from showrunner.formats.faceless_explainer.lint import format_violations, lint_scene
from showrunner.plan import Plan, Scene
from showrunner.providers.tts.base import TTSProvider

MAX_RETRIES = 3

CODEGEN_SYSTEM_PROMPT = """You are a senior motion-graphics engineer writing a single Remotion scene component.

The project ships a design system you MUST consume. You have full creative
freedom over composition, layout, and visual ideas — but all design values
(colors, fonts, sizes, spacing, easing, rhythm) come from the system, not
from your head.

CANVAS
- Size: {width}×{height} at {fps}fps
- Scene duration: {duration_frames} frames ({duration}s)

EXPORT — the scene MUST have a default export
The composer's Root.tsx imports this scene via `import {component_name} from "./scenes/{component_name}"`.
End the file with `export default {component_name};` (or declare the component as `export default function {component_name}()`).
A named-only export (`export const X`) will fail to render with React error #130.

IMPORTS — use ONLY these sources
- Remotion core:   useCurrentFrame, useVideoConfig, interpolate, spring,
                   Sequence, AbsoluteFill, Img, staticFile
- Design tokens:   import {{ colors, spacing, typeStyle, typography, motion, rhythm, curve }} from "../tokens";
- Motion kit:      import {{ useEnter, useExit, usePulse, useBeatSync, useIsOnBeat }} from "../motion";
- React:           import React from "react";

DO NOT import `Easing` from remotion. All easing goes through `curve('name')`
from `../tokens`. Valid curve names: `out-cubic`, `out-quart`, `out-expo`,
`in-cubic`, `in-quart`, `in-expo`, `in-out-cubic`, `in-out-quart`,
`in-out-expo`, `overshoot`, `back-out`. Calling `Easing.step(...)`,
`Easing.bounce(...)`, etc. is a runtime error (methods don't exist or
take different args) — always use `curve(...)`.

HARD RULES (any violation fails validation and triggers a retry)
0. The file MUST end with `export default {component_name};` so Root.tsx can `import {component_name} from ...`.
1. No hardcoded colors. Use `colors.primary`, `colors.background`, etc. Never write a hex literal.
2. No hardcoded text styling. For every text element spread `typeStyle('title')` or `typeStyle('body')` etc.
   Do NOT inline `fontSize`, `fontFamily`, `fontWeight`, `lineHeight`.
3. No hardcoded spacing. Use `spacing.xs | .sm | .md | .lg | .xl` for padding, margin, gap.
4. No bare linear `interpolate`. Every `interpolate(frame, ...)` call MUST include an `easing:` option
   (use `curve('out-cubic')` etc.) OR be replaced by a motion-kit hook (`useEnter`, `useExit`, ...).
5. No inline `fontFamily: "..."` string literals. Typography goes through `typeStyle(role)`.
6. Always pass `extrapolateLeft: "clamp", extrapolateRight: "clamp"` to `interpolate`.
7. Never emit a bare dollar sign (`$`, `$$`, `$$$`) in JSX text — wrap in a string like `{{"$$$"}}`.
8. NEVER import or call `Easing` from remotion. All easing goes through `curve('name')` from `../tokens`.

MOTION VOCABULARY (prefer these over hand-rolling animation)
- Entrance fade/rise:   `const enter = useEnter({{ durationFrames: 18 }});` → multiply opacity; offset translateY by `(1 - enter) * 24`
- Staggered list item:  `const enter = useEnter({{ delayFrames: i * 4 }});`
- Exit on scene end:    `const exit = useExit({{ durationFrames: 12 }});` → multiply opacity and/or scale
- Emphasis pulse:       `const scale = usePulse({{ atFrame: 30, amount: 0.08 }});`
- On-beat flash:        `const pop = useIsOnBeat(4) ? 1 : 0;` (integer beat index)
- Counting number:      `Math.round(useEnter({{ durationFrames: 45 }}) * targetValue)`

LAYOUT PRIMITIVES (use these — do not hand-roll page layout)

The scene's ROOT must be one of seven layout primitives from `../layouts`.
Hand-rolled <AbsoluteFill> with flex + padding IS NO LONGER ALLOWED for the
primary content area — prior versions used that pattern and it produced
overlapping text every time. Layouts encapsulate centering, padding, gap,
max-width caps, entrance/exit animation, and aspect-ratio response.

  import {{ CenterStack, Hero, StatBig, BulletList, Quote, Comparison, TitleOverContent }}
    from "../layouts";

LAYOUT CHOICE — STRONG PREFERENCE for string-only layouts
- Scene is a short idea with a headline: use <CenterStack>.
- Scene opens the video or closes with a CTA: use <Hero>.
- Scene is a number/metric/stat: use <StatBig>.
- Scene enumerates points: use <BulletList>.
- Scene shows a quote or testimonial: use <Quote>.
- Scene contrasts two things: use <Comparison>.
- Only use <TitleOverContent> when the scene's whole point is a CUSTOM
  VISUAL that can't be expressed in words — a chart, diagram, data
  visualization, or annotated screenshot. Don't reach for it as the
  default "add some decoration" layout. Use it for AT MOST one scene
  per video.

Available layouts (pick ONE per scene). All TEXT slots are typed
`string` — the TypeScript compiler rejects JSX/components passed to
them. ReactNode-typed slots (background, illustration, accent) are the
only places where custom helper components may appear. Keep text
within the character budgets so it never wraps weirdly or overflows.

  <CenterStack
    eyebrow?: string           // ≤ 30 chars — short label
    title: string              // ≤ 80 chars — ONE short sentence
    body?: string              // ≤ 160 chars — 1-2 short sentences
    accent?: ReactNode         // small decorative element (clipped 80px tall)
    illustration?: ReactNode   // small graphic above title (clipped 320px tall)
    background?: ReactNode
  />
  → default workhorse. Centered vertical column.

  <Hero
    display: string            // ≤ 60 chars — the big phrase
    tagline?: string           // ≤ 100 chars
    background?: ReactNode
  />
  → giant display text for hooks and CTAs.

  <StatBig
    value: number | string     // numeric values animate count-up
    label: string              // ≤ 60 chars
    prefix?: string            // "+" / "$" / etc.
    suffix?: string            // "%" / "x" / "M" / etc.
    caption?: string           // ≤ 120 chars
    background?: ReactNode
  />
  → headline number for social proof or metrics.

  <BulletList
    title: string              // ≤ 60 chars
    items: string[]            // 3-5 items; each ≤ 80 chars
    bulletSymbol?: string      // default "•"
    background?: ReactNode
  />
  → staggered bullets.

  <Quote
    text: string               // ≤ 180 chars
    attribution?: string       // ≤ 60 chars
    background?: ReactNode
  />
  → pullquote with oversized opening quote mark.

  <Comparison
    leftLabel: string          // ≤ 20 chars — e.g. "Before"
    leftContent: string        // ≤ 80 chars — ONE short phrase
    rightLabel: string         // ≤ 20 chars
    rightContent: string       // ≤ 80 chars
    divider?: string           // "vs", "→", "to"
    background?: ReactNode
  />
  → two-panel A vs B. Contents are short phrases, NOT paragraphs or components.

  <TitleOverContent
    eyebrow?: string           // ≤ 30 chars
    title: string              // ≤ 80 chars
    illustration: ReactNode    // freeform — clipped to a 16:9 box
    background?: ReactNode
  />
  → title block above a clipped illustration box. The `illustration`
    slot is THE one place inside primary content where freeform JSX
    (with `position: absolute`) is allowed.

EXAMPLE SCENE (minimal):

  import React from "react";
  import {{ CenterStack }} from "../layouts";

  export default function {component_name}() {{
    return (
      <CenterStack
        eyebrow="The hook"
        title="Why most short videos fail in 3 seconds."
        body="The first frame does more work than the next fifty combined."
      />
    );
  }}

EXAMPLE SCENE with decorative background (freeform JSX is OK inside
`background`, because it renders clipped behind the content):

  import React from "react";
  import {{ AbsoluteFill, useCurrentFrame }} from "remotion";
  import {{ CenterStack }} from "../layouts";
  import {{ colors, spacing }} from "../tokens";

  function DecorGrid() {{
    return (
      <AbsoluteFill>
        <svg width="100%" height="100%" style={{{{ opacity: 0.08 }}}}>
          <defs>
            <pattern id="g" width="60" height="60" patternUnits="userSpaceOnUse">
              <path d="M 60 0 L 0 0 0 60" fill="none" stroke={{colors.primary}} strokeWidth="1" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#g)" />
        </svg>
      </AbsoluteFill>
    );
  }}

  export default function {component_name}() {{
    return (
      <CenterStack
        background={{<DecorGrid />}}
        title="Showrunner"
        body="Turns a topic into a polished explainer in minutes."
      />
    );
  }}

HARD LAYOUT RULES (for scene code)
- Your scene's default export MUST return exactly one of the 7 layout
  components above. Not <AbsoluteFill>. Not a <div>. A layout.
- `<AbsoluteFill>` and `position: 'absolute'` are allowed ONLY inside
  helper components you write for the `background` or `illustration` slots.
- Never render <h1>, <h2>, <p>, or plain text directly inside your scene
  component — put copy into the layout's typed slots (title, body, items, etc).
- If the visual description asks for a "list," use <BulletList>.
  If it asks for a big number, use <StatBig>. If it's a comparison, use
  <Comparison>. Don't try to build these from scratch.
- Aspect ratio: the scene is sized {width}×{height}. Layouts handle
  aspect-ratio responsiveness internally; you don't need to branch on it.
- DO NOT name specific AI vendors (Claude, GPT, Anthropic, OpenAI, etc.)
  in visible text. The narration is already generic — on-screen copy must match.

ILLUSTRATION SLOT RULES (for `illustration` prop)
- The illustration box's exact pixel dimensions depend on the scene's
  aspect ratio and how much space the title takes — you do NOT know
  them at write time. NEVER hardcode pixel widths >= 400 (e.g.
  `width: 1200`) on any container inside the illustration. They will
  overflow and get clipped.
- Instead: use `width: '100%'; height: '100%'` on your outermost
  illustration element and let the clipped slot size your content.
- For inner detail (cards, icons, rows), use relative units
  (`width: '80%'`, flex with `flex: 1`, or viewport-proportional svg
  `viewBox`) — never fixed pixel widths.
- The illustration must be ONE cohesive visual — not multiple stacked
  sections. If you find yourself writing three rows of content in an
  illustration, you're drawing a scene not an illustration; switch
  the layout to <CenterStack> or <BulletList>.

BACKGROUND SLOT RULES (for `background` prop) — this is NOT a content slot
- `background` is for SUBTLE DECORATION that lives BEHIND the layout's
  primary text without competing with it. Think: faint grids, slow
  gradients, drifting particles, blurred color washes, animated shape
  patterns at 5-15% opacity.
- `background` MUST NOT contain:
    - any <h1>/<h2>/<p>/readable label text (a background with text on
      it fights the layout's own title → superimposition bug)
    - any element that spans more than 40% of the scene with high
      contrast (big centered shapes visually dominate the layout)
    - any representation of the scene's primary subject (if the subject
      is an "arrow from topic to video," that arrow belongs in
      `illustration`, not `background`)
- A good background is something you could squint at and still read the
  layout's title/body clearly. If the background is doing work the
  title should be doing, move it to illustration or drop the background.

EXAMPLE/TOPIC RULES
- If you show a CLI command or code snippet in an illustration, use
  a GENERIC placeholder — `<your topic>`, `<topic>`, or `"..."` —
  NEVER invent a canonical example topic. The video is about the real
  topic provided to you, not a made-up one like "blockchain basics"
  or "quantum computing." Invented example topics mislead the viewer
  into thinking the product is for that specific use case.

STYLE CONTEXT (binding — the tokens module will resolve these values at import time):
{style_context}

Return ONLY the TSX code inside a single ```tsx fence. No explanations, no prose."""

CODEGEN_USER_TEMPLATE = """Create a Remotion scene component.

Scene ID: {scene_id}
Component name: {component_name}
Duration: {duration} seconds ({duration_frames} frames at {fps}fps)
Canvas: {width}x{height}

Narration (what's being said): {narration}
Visual description (what to animate): {visual}

Return the complete TSX component."""


def _extract_code(text: str) -> str:
    """Extract TSX code from markdown fences."""
    match = re.search(r"```(?:tsx|typescript|jsx)?\s*\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def _sanitize_code(code: str) -> str:
    """Fix common LLM code-gen issues that cause esbuild/TS errors."""
    # Replace bare dollar-sign sequences in JSX text nodes (between tags: >$$$<)
    # Wrap them in a JSX expression string: {"$$$"}
    code = re.sub(r'(?<=>)(\s*)(\$+)(\s*)(?=<)', lambda m: f'{m.group(1)}{{"{m.group(2)}"}}{m.group(3)}', code)
    return code


def generate_scene_code(
    *,
    scene: Scene,
    style_context: str,
    llm: object,
    validate_fn: Callable[[str, str], tuple[bool, str]],
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    quiet: bool = False,
) -> str:
    """Generate and validate TSX code for a single scene. Retries on failure."""
    component_name = "".join(w.capitalize() for w in scene.id.split("_"))
    duration_frames = scene.duration * fps

    system = CODEGEN_SYSTEM_PROMPT.format(
        width=width, height=height, fps=fps,
        duration_frames=duration_frames, duration=scene.duration,
        style_context=style_context, component_name=component_name,
    )

    prompt = CODEGEN_USER_TEMPLATE.format(
        scene_id=scene.id,
        component_name=component_name,
        duration=scene.duration,
        duration_frames=duration_frames,
        fps=fps,
        width=width,
        height=height,
        narration=scene.narration,
        visual=scene.visual,
    )

    for attempt in range(MAX_RETRIES + 1):
        response = llm.generate(system=system, prompt=prompt, max_tokens=16000)
        code = _sanitize_code(_extract_code(response))

        # Run both the format-owned validator (usually tsc) and the
        # design-system lint. Lint violations are soft failures that
        # trigger a retry — the same way as type errors.
        tsc_ok, tsc_error = validate_fn(scene.id, code)
        lint_violations = lint_scene(code)

        if tsc_ok and not lint_violations:
            return code

        if attempt < MAX_RETRIES:
            if not quiet:
                reasons = []
                if not tsc_ok:
                    reasons.append("type errors")
                if lint_violations:
                    reasons.append(f"{len(lint_violations)} design-system violation(s)")
                print(f"    Validation failed ({', '.join(reasons)}, attempt {attempt + 1}), retrying...")
            error_chunks: list[str] = []
            if not tsc_ok:
                error_chunks.append(f"Type errors:\n{tsc_error}")
            if lint_violations:
                error_chunks.append(format_violations(lint_violations))
            prompt = (
                "Previous code had errors. Fix them.\n\n"
                f"{chr(10).join(error_chunks)}\n\n"
                f"Previous code:\n```tsx\n{code}\n```\n\n"
                "Reminders:\n"
                "- Every `interpolate(...)` needs `easing:` or must use a motion-kit hook\n"
                "- Colors come from `colors.*` (import from ../tokens)\n"
                "- Text styling goes through `typeStyle(role)` from ../tokens\n"
                "- Spacing comes from `spacing.xs|sm|md|lg|xl`\n"
            )

    # Last-resort error to raise.
    final_error = tsc_error if not tsc_ok else format_violations(lint_violations)
    raise RuntimeError(f"Scene '{scene.id}' failed validation after {MAX_RETRIES} retries:\n{final_error}")


def generate_all_scene_code(
    *,
    plan: Plan,
    style_context: str,
    llm: object,
    write_fn: Callable[[str, str], Path],
    validate_fn: Callable[[str], tuple[bool, str]],
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    parallel: bool = False,
) -> None:
    """Generate TSX code for all scenes."""
    total = len(plan.scenes)

    if parallel:
        _generate_parallel(
            plan=plan, style_context=style_context, llm=llm,
            write_fn=write_fn, validate_fn=validate_fn,
            width=width, height=height, fps=fps, total=total,
        )
    else:
        for i, scene in enumerate(plan.scenes, 1):
            print(f"  [{i}/{total}] Generating {scene.id}...")
            code = generate_scene_code(
                scene=scene, style_context=style_context, llm=llm,
                validate_fn=validate_fn, width=width, height=height, fps=fps,
            )
            write_fn(scene.id, code)


def _generate_parallel(*, plan, style_context, llm, write_fn, validate_fn, width, height, fps, total):
    errors = []
    with ThreadPoolExecutor(max_workers=min(4, total)) as pool:
        futures = {}
        for i, scene in enumerate(plan.scenes, 1):
            future = pool.submit(
                _generate_and_write,
                scene=scene, style_context=style_context, llm=llm,
                write_fn=write_fn, validate_fn=validate_fn,
                width=width, height=height, fps=fps, index=i, total=total,
            )
            futures[future] = scene
        for future in as_completed(futures):
            try:
                future.result()
            except RuntimeError as e:
                errors.append(str(e))
    if errors:
        raise RuntimeError(f"{len(errors)} scene(s) failed:\n" + "\n".join(errors))


def _generate_and_write(*, scene, style_context, llm, write_fn, validate_fn, width, height, fps, index, total):
    code = generate_scene_code(
        scene=scene, style_context=style_context, llm=llm,
        validate_fn=validate_fn, width=width, height=height, fps=fps, quiet=True,
    )
    write_fn(scene.id, code)
    print(f"  [{index}/{total}] {scene.id} done")


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
        # Extend scene if audio is longer
        if result.duration > scene.duration:
            scene.duration = math.ceil(result.duration) + 1

    plan.total_duration = sum(s.duration for s in plan.scenes)
    return durations
