---
name: kinetic-typography
description: Produce a short type-driven motion piece (8–45s) — words as the visual, beat-locked animation, single HTML composition.
---

# Kinetic Typography Workflow

Type IS the visual: a hook line, a quote, a manifesto, a stat — animated so
the motion carries the meaning. No scene components, no compose step; you
author one HTML composition directly.

Contract: `showrunner workflows` (stages: storyboard → narration →
composition → render).

## Stage 0 — scaffold

```bash
showrunner new <dir> --workflow kinetic-typography --aspect-ratio 9:16
```

The scaffold writes a contract-valid `index.html` skeleton (root composition
div + one paused timeline) and `assets/` directories.

## Stage 1 — storyboard

Even a single-composition piece gets a storyboard — it's the timing contract
the checks verify against. Scenes here are *beats of copy*, not components:

```json
{
  "title": "Ship Small",
  "totalDuration": 12,
  "scenes": [
    {"id": "line_one", "duration": 4, "narration": "",
     "visual": "SHIP — slams in from above, settles with overshoot",
     "transition": "cut"},
    {"id": "line_two", "duration": 4, "narration": "",
     "visual": "SMALL. — letters cascade in one per beat", "transition": "cut"}
  ]
}
```

Narration is optional — leave `narration` empty for a music-only piece.
Gate: `showrunner storyboard validate <dir> --json`.

## Stage 2 — narration

```bash
showrunner tts <dir>
```

Run this even for silent pieces — it records the (possibly empty) narration
map the check expects. Scenes with empty narration are skipped.

## Stage 3 — composition

Read `craft/html-composition.md` (the composition contract) — then write the
piece into `index.html`. Principles that make kinetic type read as designed:

- **One idea per beat.** Each storyboard scene is a `class="clip"` element
  with `data-start`/`data-duration` matching the storyboard timings.
- **Type does the work.** Scale, weight, and timing carry emphasis — not
  decoration. 2 sizes per piece beat 5.
- **Land on beats.** Pick the piece's BPM; place every entrance on the grid
  (`60/bpm` second multiples). Off-beat motion is what makes type feel cheap.
- **Overshoot with restraint.** One springy entrance per piece is a
  signature; five is a toy.

Gate as you iterate:

```bash
showrunner check <dir> --json
```

The composition stage runs the runtime's own gate (console errors, layout
defects, timeline determinism, contrast) — findings name selectors.

## Stage 4 — render

```bash
showrunner render <dir> -o out/<name>.mp4
```

`showrunner preview <dir>` opens the live editor while iterating.
