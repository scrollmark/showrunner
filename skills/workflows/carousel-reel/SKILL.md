---
name: carousel-reel
description: Produce a beat-synced image reel (8–60s) — user-supplied images cut to a music bed's beat grid, no narration.
---

# Carousel Reel Workflow

A set of images becomes a rhythmic reel: every cut lands on a beat, subtle
motion (pan/zoom/scale) keeps each slide alive between cuts. The music is
the clock — pick it before authoring anything.

Contract: `showrunner workflows` (stages: storyboard → music → composition →
render).

## Stage 0 — scaffold + assets

```bash
showrunner new <dir> --workflow carousel-reel --aspect-ratio 9:16
```

Copy the user's images into `<dir>/assets/images/`. Ask for them if you have
none — this workflow does not invent imagery.

## Stage 1 — storyboard

Scenes are slides. `visual` says which image and what motion; `narration`
stays empty:

```json
{
  "title": "Studio Tour",
  "totalDuration": 16,
  "scenes": [
    {"id": "slide_one", "duration": 2, "narration": "",
     "visual": "images/01.jpg — slow push-in, exposure up on entry",
     "transition": "cut"}
  ]
}
```

Gate: `showrunner storyboard validate <dir> --json`.

## Stage 2 — music

The bed comes from the user's licensed catalog:

```bash
showrunner music list
showrunner music analyze <track-path> --json
```

Copy the chosen track into `assets/audio/` and record the analysis in
`<dir>/music.json`:

```json
{
  "track": "assets/audio/bed.wav",
  "bpm": 120.0,
  "beats": [0.0, 0.5, 1.0, 1.5],
  "volume": 0.8
}
```

`showrunner check` verifies the track exists, the grid is present, and —
once the composition exists — that every clip start sits on a beat.

## Stage 3 — composition

Read `craft/html-composition.md`. Author `index.html`: one `class="clip"`
per slide with `data-start` **snapped to values from `music.json` beats**
(the check enforces ±1 frame), the track as an `<audio>` child of the
composition root, and motion per slide on the single paused timeline.

Craft notes:

- Cut on beats; let stronger images hold 2 beats, minor ones 1.
- One motion idea per slide (push-in OR drift OR scale settle) — alternate
  direction between adjacent slides so cuts feel intentional.
- No two adjacent slides with the same motion AND the same framing.
- End on the strongest image with a longer hold and a settle, not a cut to
  black.

Gate: `showrunner check <dir> --json` (runs the beat-alignment check + the
runtime gate).

## Stage 4 — render

```bash
showrunner render <dir> -o out/<name>.mp4
```
