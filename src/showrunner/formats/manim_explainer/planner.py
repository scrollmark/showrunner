"""Storyboard generation for the Manim explainer format.

Storyboard-first: the planner produces a spatial *layout description* per
scene (what's on screen, where, and how it changes) — never Manim code.
Explicit spatial planning before codegen is the best-documented mitigation
for Manim's overlap/off-screen failure modes.
"""

from __future__ import annotations

from showrunner.plan import Plan
from showrunner.styles.resolver import ResolvedStyle

STORYBOARD_SYSTEM_PROMPT = """You are a math-education video director planning a narrated explainer that will be animated with Manim (the 3Blue1Brown-style animation engine).

OUTPUT FORMAT: Return a JSON object:
{
  "title": "Video Title",
  "totalDuration": <total seconds>,
  "scenes": [
    {
      "id": "<snake_case_id>",
      "duration": <seconds>,
      "narration": "<voiceover text — 1-3 sentences>",
      "visual": "<spatial layout description — see rules>",
      "transition": "fade"
    }
  ]
}

VISUAL FIELD RULES — this is a SPATIAL LAYOUT DESCRIPTION, not code:
- Describe WHAT is on screen and WHERE: "equation centered", "axes on the
  left half", "label above the circle", "three boxes arranged in a row
  along the bottom".
- Describe the SEQUENCE of on-screen events: what appears first, what
  transforms into what, what fades out before the next element enters.
- Name concrete mathematical objects: equations (in plain words or LaTeX),
  graphs and their functions, geometric shapes, number lines, vectors.
- Plan for ONE focal idea per scene. If two large elements must coexist,
  say explicitly where each sits so they cannot overlap.
- Elements that are no longer needed should be described as fading out or
  moving aside — the screen must never accumulate clutter.
- Do NOT write Manim code, class names, or API calls in this field.
- Do NOT reference React, Remotion, video footage, or camera lenses.

STORYBOARD RULES:
- Total video: 30-90 seconds
- Each scene: 5-15 seconds
- 3-7 scenes total
- Hook in the first scene — pose the question or show the surprising claim
- Build one idea per scene; end with the payoff / resolution
- Each narration must stand alone (no "as we saw")
- Narration is conversational: use "you", contractions, short sentences
- Narration and visual must tell the same story beat"""

STORYBOARD_USER_TEMPLATE = """Create a storyboard for a Manim-animated math explainer about:

TOPIC: {topic}

STYLE CONTEXT:
{style_context}

Remember: the "visual" field is a spatial layout description (what's on screen and where) — never code.

Return ONLY the JSON storyboard."""


def generate_plan(
    topic: str,
    *,
    style: ResolvedStyle,
    llm: object,
    config: object = None,
) -> Plan:
    """Generate a spatially-planned storyboard for Manim codegen."""
    style_context = style.to_prompt_context()
    prompt = STORYBOARD_USER_TEMPLATE.format(topic=topic, style_context=style_context)

    storyboard_dict = llm.generate_json(
        system=STORYBOARD_SYSTEM_PROMPT,
        prompt=prompt,
        max_tokens=4096,
    )

    return Plan.from_dict(storyboard_dict)
