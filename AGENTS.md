# Showrunner — Agent Guide

You are the director. Showrunner gives you a production toolchain — storyboard
validation, narration synthesis, a typed design system, quality gates, and
rendering — and you supply the creative decisions: what the video says, how
each scene looks, how it moves.

## Rule Zero

For ANY request to make a video, read `skills/INDEX.md` first, pick the
workflow that fits, and follow its SKILL.md stage by stage. Do not improvise a
pipeline; do not call render before `showrunner check` passes.

## How a production runs

1. `showrunner new <dir> --workflow <name> --style <preset>` — scaffold a project.
2. Author `storyboard.json` (see `skills/craft/storyboard.md`), then
   `showrunner storyboard validate <dir>`.
3. `showrunner tts <dir>` — synthesize narration; durations are measured and
   written back.
4. Author the visuals the workflow calls for (e.g. scene components per
   `skills/craft/scene-code.md`), validating as you go
   (`showrunner scene validate <dir>`).
5. `showrunner compose <dir>` — build the timeline (where the workflow uses it).
6. `showrunner check <dir>` — the gate. Fix findings until it passes.
7. `showrunner render <dir> -o out.mp4`.

## Non-negotiables

- **The gate is real.** `showrunner render` refuses to run unless the last
  `showrunner check` passed and nothing changed since. Fix findings; don't
  reach for `--force` unless a human explicitly asks.
- **Generated files are generated.** `src/Root.tsx`,
  `src/tokens/preset.generated.ts`, and `src/music/envelope.generated.ts` are
  written by tools. Never hand-edit them — rerun the tool that owns them.
- **Design values come from the system.** Colors, type, spacing, easing, and
  rhythm come from the style preset's tokens. Validation enforces this;
  hardcoded values fail the check.
- **Validator output is your fix list.** Every command supports `--json`;
  findings name the scene, the rule, and what to change.

## Discovering the surface

- `showrunner workflows` — available workflows + their stage contracts
- `showrunner styles` — style presets
- `showrunner voices` — narration voices
- `showrunner music list` — the user's licensed music catalog
