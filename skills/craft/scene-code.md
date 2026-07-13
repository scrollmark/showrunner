# Scene Code Craft (Remotion runtime)

How to write a scene component that passes `showrunner scene validate` and
looks designed rather than defaulted. You have full creative freedom over
composition and ideas — every design VALUE (color, type, size, spacing,
easing, rhythm) comes from the token system, never from your head.

## File contract

- One file per scene: `src/scenes/<PascalCaseOfSceneId>.tsx`
  (`hook_question` → `HookQuestion.tsx`).
- The file MUST end with a default export of the component
  (`export default function HookQuestion() {…}`); Root.tsx imports it by
  that name. A named-only export fails at render with React error #130.

## Imports — only these sources

```tsx
import React from "react";
import { useCurrentFrame, useVideoConfig, interpolate, spring,
         Sequence, AbsoluteFill, Img, staticFile } from "remotion";
import { colors, spacing, typeStyle, typography, motion, rhythm, curve } from "../tokens";
import { useEnter, useExit, usePulse, useBeatSync, useIsOnBeat } from "../motion";
import { CenterStack, Hero, StatBig, BulletList, Quote, Comparison,
         TitleOverContent } from "../layouts";
import { GridBackground, DotBackground, GradientWash, SparkleField,
         WavyLines } from "../backgrounds";
```

Never import `Easing` from remotion — all easing goes through `curve(name)`:
`out-cubic`, `out-quart`, `out-expo`, `in-cubic`, `in-quart`, `in-expo`,
`in-out-cubic`, `in-out-quart`, `in-out-expo`, `overshoot`, `back-out`.

## Hard rules (lint enforces every one)

1. No hex/color literals — use `colors.primary`, `colors.background`, etc.
2. No inline `fontSize`, `fontFamily`, `fontWeight`, `lineHeight` — spread
   `typeStyle('title')` / `typeStyle('body')` etc. on every text element.
3. No hardcoded padding/margin/gap — use `spacing.xs|sm|md|lg|xl`.
4. Every `interpolate(frame, …)` needs an `easing:` option
   (`easing: curve('out-cubic')`) or use a motion hook instead. Always pass
   `extrapolateLeft: "clamp", extrapolateRight: "clamp"`.
5. Scene root must be ONE of the seven layout primitives — not
   `<AbsoluteFill>`, not a `<div>`. `position: 'absolute'` is allowed only
   inside helpers passed to `background`/`illustration` slots.
6. `background` props accept ONLY components from `../backgrounds` (at most
   two, combined in a fragment) — never custom JSX, never text.
7. No fixed pixel widths ≥ 400 inside illustrations — use `width: '100%'`
   and relative units; the slot's real size isn't knowable at write time.
8. Never emit a bare `$` in JSX text — wrap it: `{"$$$"}`.
9. Don't name third-party AI models or vendors in visible text.

## Choosing a layout (strong preference for string-only layouts)

| Scene is… | Layout |
|---|---|
| a short idea with a headline | `<CenterStack eyebrow? title body? accent? illustration? background?>` |
| the opener or a CTA | `<Hero display tagline? background?>` |
| a number/metric/stat | `<StatBig value label prefix? suffix? caption? background?>` (numeric values count up) |
| an enumeration | `<BulletList title items bulletSymbol? background?>` (3–5 items) |
| a quote/testimonial | `<Quote text attribution? background?>` |
| a contrast of two things | `<Comparison leftLabel leftContent rightLabel rightContent divider? background?>` |
| a custom visual (chart, diagram) | `<TitleOverContent eyebrow? title illustration background?>` — at most ONE scene per video |

Text slots are typed `string` with budgets (titles ≤ 80 chars, body ≤ 160,
items ≤ 80 each) — stay inside them so nothing wraps or overflows. The
`illustration` slot of `TitleOverContent` is the one place for freeform JSX,
and it must be one cohesive visual, not stacked sections.

## Motion vocabulary (prefer hooks over hand-rolled animation)

```tsx
const enter = useEnter({ durationFrames: 18 });        // fade/rise in: opacity=enter, y=(1-enter)*24
const enter = useEnter({ delayFrames: i * 4 });        // staggered list items
const exit  = useExit({ durationFrames: 12 });         // fade out at scene end
const scale = usePulse({ atFrame: 30, amount: 0.08 }); // emphasis pulse
const pop   = useIsOnBeat(4) ? 1 : 0;                  // on-beat flash
Math.round(useEnter({ durationFrames: 45 }) * target)  // counting number
```

Rhythm: the preset defines a BPM grid (`rhythm`, `useBeatSync`,
`useIsOnBeat`) — land emphasis on beats and the scene will feel cut to the
music even before the bed is added.

## Minimal example

```tsx
import React from "react";
import { CenterStack } from "../layouts";
import { GradientWash } from "../backgrounds";

export default function KeyInsight() {
  return (
    <CenterStack
      background={<GradientWash from="background" to="primary" />}
      eyebrow="The insight"
      title="Short videos are won in the first three seconds."
      body="The opening frame does more work than the next fifty combined."
    />
  );
}
```

## Working loop

Write the scene → `showrunner scene validate <dir> <scene_id> --json` → fix
each finding (rule name + line) → revalidate. Validate scene-by-scene as you
write; a whole-project type pass runs again inside `showrunner check`.
