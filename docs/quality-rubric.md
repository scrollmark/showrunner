# Showrunner Quality Rubric

A scoring framework for evaluating the craft of a generated video. Used to:

1. **Calibrate** current output against reference material.
2. **Gate** phase completions — each phase has a target score delta.
3. **Catch** regressions — any generated video should stay above a floor across all dimensions.

The rubric is deliberately qualitative. Automated CI checks (snapshot diff, generated-code linter, render-budget) catch regressions in specific primitives; this rubric catches overall craft.

## How to use

For each video under evaluation:

1. Watch in full at least twice. Score silent and again with audio.
2. Assign 0–5 on each of the seven dimensions below using the anchors.
3. Sum to a **total out of 35**. Record the breakdown — dimension scores matter more than the sum for diagnostic work.

| Total | Band | What it means |
|---|---|---|
| 30–35 | **Reference-tier** | Indistinguishable from hand-crafted output; publishable as-is. |
| 24–29 | **Shippable** | Clearly purposeful craft; a typical viewer would not notice it's generated. |
| 17–23 | **Rough** | Ideas are legible but the execution reads as "AI-made." |
| 10–16 | **Prototype** | Watchable but visibly amateur. |
| 0–9 | **Broken** | Unusable as a final artifact. |

## The seven dimensions

Each dimension is scored 0 (absent) / 1 (present but broken) / 3 (functional) / 5 (intentional craft). 2 and 4 are allowed as in-betweens.

### 1. Typographic hierarchy

The use of weight, scale, case, tracking, and leading to separate information.

| Score | Anchor |
|---|---|
| 0 | One font at one weight and one size. All text looks like body copy. |
| 2 | Different sizes but no weight contrast. Hierarchy is signalled by size alone. |
| 3 | Weight + size contrast used correctly. Hierarchy readable at a glance. |
| 4 | Variable weights (300–900) used with intent. Tracking/leading tuned per role. Display type clearly distinct from body. |
| 5 | Typographic pairings feel composed. Display weights carry emotion (condensed, italic, semibold). Quotes, stats, labels each have their own treatment. |

### 2. Easing quality

The naturalness of entrance, exit, and emphasis animations. The single strongest "AI-made" tell.

| Score | Anchor |
|---|---|
| 0 | All animations are linear `interpolate`. Objects slide at constant velocity. |
| 2 | Some springs, but overshoot is wrong — bouncy when it should be snappy, or slow when it should be confident. |
| 3 | Entrances use ease-out curves; exits use ease-in. Consistent across scenes. |
| 4 | Motion feels weighted. Large elements take longer than small ones. Emphasis pulses use a different curve than entrances. |
| 5 | Motion reads as deliberate. Different curve vocabulary for different gestures (reveal vs. transition vs. pulse vs. flourish). Occasional signature curve repeats across scenes as a motif. |

### 3. Transition sophistication

How scenes join. The #2 "AI-made" tell after linear easing.

| Score | Anchor |
|---|---|
| 0 | Cuts only, or opacity fades on a div. |
| 2 | A couple of transition types (fade + slide) but applied uniformly, without feeling chosen. |
| 3 | Transitions chosen per scene pair. Uses `@remotion/transitions` primitives correctly. |
| 4 | Transitions carry semantic weight — a slide means "continuation," a fade means "time jump," a wipe means "contrast." |
| 5 | Signature transition motifs. A shape, word, or color bridges between scenes. Transitions occasionally break the fourth wall (an element from scene A becomes part of scene B). |

### 4. Audio-visual sync

The relationship between sound and motion.

| Score | Anchor |
|---|---|
| 0 | Narration only. No music. No SFX. Audio is the TTS output dropped in. |
| 2 | Background music present but ignores the cuts. Transitions land mid-bar. |
| 3 | Cuts land on downbeats. Music level ducks under narration. |
| 4 | SFX on transitions (whoosh, stinger, click). Captions synced word-by-word to narration. Moments of intentional silence. |
| 5 | Rhythm is composed. Scene durations are beat-multiples. Stingers punctuate key lines. The video would feel broken without its audio layer. |

### 5. Layout density and rhythm

Negative space, alignment, hierarchy of visual elements, and consistency across scenes.

| Score | Anchor |
|---|---|
| 0 | Center-aligned text on a flat color. Same treatment every scene. |
| 2 | Some asymmetry but padding/margin are inconsistent scene-to-scene. |
| 3 | Grid discipline within scenes. Consistent margins. Negative space deployed, not forgotten. |
| 4 | Visual density varies with emotion — breathing room on quiet beats, filled frames on payoffs. Typography anchors to a consistent baseline. |
| 5 | Scenes feel composed, not laid out. Each scene has a deliberate visual center. Layouts vary confidently across the video while still feeling of-a-piece. |

### 6. Visual motifs and brand identity

Recurring elements that make the video feel like one piece rather than a deck.

| Score | Anchor |
|---|---|
| 0 | No recurring element. Each scene is visually disconnected. |
| 2 | One recurring element (a color or logo), applied mechanically. |
| 3 | A color palette, a shape vocabulary, and a type system used consistently. |
| 4 | A signature motif — a shape that travels, a recurring framing, a distinct accent use — that shows up 3+ times with variation. |
| 5 | The video has a recognizable visual identity. You could recognize another video made by the same system without being told. |

### 7. Depth, texture, and material

Layering, grain, blur, parallax, perspective — the signals that separate "flat" from "world-inhabiting."

| Score | Anchor |
|---|---|
| 0 | Flat color fills. Everything on one plane. |
| 2 | Occasional gradient or shadow, applied inconsistently. |
| 3 | Multi-layer scenes. Foreground and background distinguished by blur or scale. Soft shadows used intentionally. |
| 4 | Parallax on multi-plane scenes. Selective motion blur on fast movement. Grain or film texture overlay adds subtle character. |
| 5 | Scenes read as physical spaces — with depth, light direction, and material response. Motion feels embodied, not computed. |

## Scoring worksheet template

```
Video: <filename or URL>
Style preset: <name>
Reviewer: <name>
Date: <YYYY-MM-DD>

1. Typographic hierarchy        __ / 5   notes:
2. Easing quality               __ / 5   notes:
3. Transition sophistication    __ / 5   notes:
4. Audio-visual sync            __ / 5   notes:
5. Layout density / rhythm      __ / 5   notes:
6. Visual motifs / brand        __ / 5   notes:
7. Depth / texture / material   __ / 5   notes:

TOTAL: __ / 35
BAND: (Broken / Prototype / Rough / Shippable / Reference-tier)

Top-3 observed strengths:
- 

Top-3 observed weaknesses:
-

Concrete follow-up tickets:
-
```

## Phase gates

Each roadmap phase ships with a target rubric delta, measured on a fixed evaluation set (same 3 topics × 3 presets = 9 videos, regenerated per phase).

| Phase | Target |
|---|---|
| Phase 0 — baseline | Score current output; establish floor. No target. |
| Phase 1 — tactical polish | **+6 points** on avg total. Largest gains in dims 1, 2, 3, 5. |
| Phase 2 — primitive library | **+5 points**. Largest gains in dims 1, 2, 6. Reduced variance across the evaluation set. |
| Phase 3 — audio/rhythm | **+5 points**. Largest gains in dim 4. |
| Phase 4 — signature motion | **+4 points**. Largest gains in dims 6, 7. |

Rubric + automated CI checks (snapshot diff, code linter) together form the phase-completion gate. Neither one alone is sufficient — the rubric catches craft regressions that CI misses; CI catches quiet degradations the rubric misses.

## Reference material

Reviewers should maintain a personal library of 10–20 reference clips representing the craft bar. Rescore both reference clips and generated output in the same sitting; the contrast is what makes the scoring honest. Reference material is not committed to the repo.
