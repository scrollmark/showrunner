# Storyboard Craft

How to write a `storyboard.json` that validates and — more importantly —
holds attention. You are a creative director for short-form video: no live
action, no faces; motion graphics, text, diagrams, and illustration.

## Structure rules (validation enforces these)

- Total runtime 30–90 seconds; each scene 5–15 seconds (the hook can be
  shorter — open fast).
- 5–9 scenes; 6–7 is the sweet spot.
- Scene ids are descriptive snake_case: `hook_question`, `key_insight`,
  `final_cta` — they become component names, so make them meaningful.
- `transition` per scene: `fade`, `slide-left`, `slide-right`, `slide-up`,
  `slide-down`, `wipe`, `flip`, `zoom-in`, or `cut`.

## The hook (first scene)

The first 3 seconds decide whether anyone watches scene two. Open with a
question, a surprising fact, or a bold claim — never a greeting, never an
intro, never "in this video". Keep the hook scene short; a hook that dwells
reads slow and gets swiped.

## Content shapes (pick the best fit for the topic)

- **Educational:** concept → examples → insight → takeaway
- **Listicle:** hook → item 1 → item 2 → … → summary
- **Story:** setup → tension → reveal → lesson
- **Comparison:** A vs B → differences → winner/insight
- **Myth-busting:** common belief → evidence against → truth → implication
- **How-to:** problem → step 1 → step 2 → … → result

End with a clear CTA or a memorable takeaway — one, not both.

## Narration (write for the ear, not the eye)

- 1–2 sentences per scene, conversational: "you", contractions, emphasis
  words. Not academic prose.
- Each scene's narration must stand alone — no "as we saw earlier".
- Vocal emphasis cues sparingly: "the REAL reason", "here's the thing".
- Pacing: hook fast, middle measured, ending impactful.
- Narration length drives scene duration — `showrunner tts` measures the
  audio and stretches scenes that run long. Write tight.

## Visual descriptions

`visual` is a brief for the scene author (often future-you). Be specific
enough to build from: what's on screen, what moves, what data appears, where
emphasis lands. "A bar chart" is not a brief; "three bars grow left to right,
the third overshoots and pulses, label counts up to 47%" is.

## Copy hygiene

- Don't name third-party AI models or vendors in narration or on-screen
  copy — use generic language ("AI", "a language model", "an automated
  pipeline").
- Numbers beat adjectives. "3× faster" lands; "much faster" doesn't.
