"""Storyboard generation for faceless explainer videos."""

from __future__ import annotations

from showrunner.plan import Plan
from showrunner.styles.resolver import ResolvedStyle


STORYBOARD_SYSTEM_PROMPT = """You are a creative director for short-form social media videos. You produce storyboards for animated explainer videos (no live action, no faces — only motion graphics, text, diagrams, and illustrations).

OUTPUT FORMAT: Return a JSON object with this exact structure:
{
  "title": "Video Title (short, catchy)",
  "totalDuration": <total seconds>,
  "scenes": [
    {
      "id": "<snake_case_id>",
      "duration": <seconds>,
      "narration": "<voiceover text — 1-2 sentences, conversational>",
      "visual": "<detailed animation/visual description for a developer to implement>",
      "transition": "<fade|slide-left|slide-up|zoom-in|cut>"
    }
  ]
}

RULES:
- Total video: 30-90 seconds
- Each scene: 5-15 seconds
- 5-9 scenes total (sweet spot: 6-7)
- Hook in first 3 seconds — pose a question, surprising fact, or bold claim
- End with a clear CTA or memorable takeaway
- Each scene's narration must stand alone (no "as we saw earlier")
- Narration should be conversational, not academic — use "you", contractions, emphasis words
- Visual descriptions must be specific enough for a developer to implement as React animations
- Include specific colors, positions, movements, data values in visual descriptions
- Scene IDs should be descriptive snake_case (e.g., hook_question, key_insight, final_cta)

CONTENT FORMATS (choose the best fit):
- Educational: concept → examples → insight → takeaway
- Listicle: hook → item1 → item2 → ... → summary
- Story: setup → tension → reveal → lesson
- Comparison: A vs B → differences → winner/insight
- Myth-busting: common belief → evidence against → truth → implication
- How-to: problem → step1 → step2 → ... → result

NARRATION GUIDELINES:
- Write for speech, not reading — use natural phrasing
- Each scene's narration = 1-2 sentences max
- Use vocal emphasis cues sparingly: "the REAL reason", "here's the thing"
- Avoid jargon unless the topic requires it
- Pacing: hook fast, middle measured, end impactful"""


STORYBOARD_USER_TEMPLATE = """Create a storyboard for a short-form video about:

TOPIC: {topic}

STYLE CONTEXT:
{style_context}

Return ONLY the JSON storyboard — no explanations, no markdown fences."""


def generate_plan(
    topic: str,
    *,
    style: ResolvedStyle,
    llm: object,
    config: dict | None = None,
) -> Plan:
    """Generate a video storyboard plan from a topic."""
    style_context = style.to_prompt_context()
    prompt = STORYBOARD_USER_TEMPLATE.format(topic=topic, style_context=style_context)

    storyboard_dict = llm.generate_json(
        system=STORYBOARD_SYSTEM_PROMPT,
        prompt=prompt,
        max_tokens=4096,
    )

    return Plan.from_dict(storyboard_dict)
