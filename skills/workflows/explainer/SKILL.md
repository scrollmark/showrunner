---
name: explainer
description: Produce a narrated animated explainer (30–90s, motion graphics + voiceover) through the staged toolchain with quality gates.
---

# Explainer Workflow

Turn a topic into a narrated, design-system-clean explainer video. You author
two things — the storyboard and the scene components; the toolchain owns
narration timing, the timeline, music, and rendering.

Contract: `showrunner workflows` (stages: storyboard → narration → scenes →
compose → render; every stage is gated by `showrunner check`).

## Stage 0 — scaffold

```bash
showrunner new <dir> --workflow explainer --style <preset> --aspect-ratio 9:16
```

Pick the preset with `showrunner styles`; pick a voice with
`showrunner voices` (pass `--voice`). The scaffold contains the Remotion
template, the design tokens for your preset (`src/tokens/`), layout
primitives (`src/layouts/`), backgrounds (`src/backgrounds/`), and motion
hooks (`src/motion/`).

## Stage 1 — storyboard

Read `craft/storyboard.md`, then write `<dir>/storyboard.json`. Shape:

```json
{
  "title": "Video Title",
  "totalDuration": 45,
  "scenes": [
    {
      "id": "hook_question",
      "duration": 4,
      "narration": "One or two conversational sentences.",
      "visual": "Specific description of what to build and animate.",
      "transition": "fade"
    }
  ]
}
```

Gate it:

```bash
showrunner storyboard validate <dir> --json
```

Fix every error finding (warnings are advisory but usually right).

## Stage 2 — narration

```bash
showrunner tts <dir>
```

This synthesizes one WAV per scene into `public/audio/`, records measured
durations in `narration.json`, and **stretches scene durations in
storyboard.json when the voice runs long** — re-read storyboard.json after
this stage; the durations you planned may have changed.

## Stage 3 — scenes

Read `craft/scene-code.md`, then write one component per scene at
`src/scenes/<PascalCaseOfSceneId>.tsx` (e.g. `hook_question` →
`HookQuestion.tsx`). Validate as you go — after each scene, not at the end:

```bash
showrunner scene validate <dir> <scene_id> --json
```

Findings are your fix list: the rule name, the line, and what to change.
Type errors come from the project's real `tsc`; lint enforces the design
system.

## Stage 4 — compose

```bash
showrunner compose <dir> --music auto
```

Generates `src/Root.tsx`: scene transitions on the preset's beat grid,
narration audio offsets on the transition-compressed timeline, and a music
bed with a narration-ducking envelope. `--music none` skips music;
`--music <track-id>` picks from `showrunner music list`. Never edit
Root.tsx by hand — change the storyboard or flags and rerun compose.

## Stage 5 — gate + render

```bash
showrunner check <dir>
showrunner render <dir> -o out/<name>.mp4
```

`check` runs every stage's validator (storyboard rules, narration coverage,
scene lint + whole-project types, compose freshness) and fingerprints the
project. `render` refuses if the check is missing, failed, or stale — that's
by design; fix and re-check rather than forcing.

To iterate visually before rendering: `showrunner preview <dir>` opens the
runtime's studio.

## Revising

- Narration change → edit storyboard.json → rerun from Stage 2.
- Visual change in one scene → edit that scene's TSX → `showrunner scene
  validate` → `showrunner check` → render.
- Timing/transition/music change → edit storyboard.json or compose flags →
  rerun Stage 4 onward.
