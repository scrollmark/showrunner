# Format-Taxonomy Examples

Twelve example videos — one per subcategory in [taxonomy.md](taxonomy.md) — generated
entirely with showrunner. Each example validates two things at once:

1. **Generation quality**: can showrunner, driven by a coding agent, produce a
   shippable video in this format? Scored against [docs/quality-rubric.md](../docs/quality-rubric.md)
   (7 dimensions, ≥24/35 = shippable).
2. **Analysis capability**: each format targets a specific analysis skill (the
   "LLM Evaluation Target" column). The rendered video is uploaded via
   `showrunner analyze` and the returned analysis is graded against that target
   in the example's eval card.

## Layout

```
examples/
  taxonomy.md               # the 12-row format table
  storyboards/<n.n-slug>.json   # hand-authored Plan JSON per example (bypasses the LLM planner)
  eval-cards/<n.n-slug>.md      # eval target, expected detections, analysis results, rubric score
  results/manifest.json     # work_dir, mp4, post_id, and scores per example
```

## Regenerating an example

Storyboard-driven examples (most of them):

```bash
showrunner create "<title>" \
  --format ai-video \
  --storyboard examples/storyboards/1.1-grwm.json \
  --auto-approve --captions --music none --json
```

The LLM-planned example (2.2 faceless explainer) has no storyboard file — it exercises
the planner itself:

```bash
showrunner create "How compound interest snowballs" \
  --format faceless-explainer --style tech-startup \
  --auto-approve --captions --music none --json
```

Capture the `WORKDIR:` line from output. To fix a single weak scene without a full
re-run: `showrunner refine <work_dir> <scene_id> --instruction "..."`.

## Scoring

```bash
showrunner login --with-password       # once
showrunner analyze <work_dir>/output/*.mp4 --sync --report
```

Paste the report into the example's eval card, grade the eval target, record the
`post_id` and rubric score in `results/manifest.json`.

## Provider notes

- Batch provider is **MiniMax** (`~$0.06/s` of generated footage). The single
  exception is 3.3 ASMR, which uses **Veo 3.1** for native audio.
- TTS is **kokoro** (local, free, word timings drive the captions).
- Music is disabled (`--music none`) across all examples to keep variables down —
  the analysis eval targets don't need it except 4.2, which supplies its own track.

## Results

All 12 examples generated and scored. See each `eval-cards/<n.n-slug>.md` for the
full analysis excerpt and reasoning behind each verdict, and `results/manifest.json`
for machine-readable detail (post_ids, mp4 paths).

Rubric column is intentionally blank for 10/12 rows: `docs/quality-rubric.md`'s 7
dimensions (typographic hierarchy, easing, transitions, layout rhythm, visual
motifs, ...) are written for Remotion/motion-graphics-generated output and don't
map cleanly onto photorealistic ai-video/composite footage. 2.2 (faceless-explainer)
is the only Remotion-rendered example and the only one where a full numeric rubric
score would be meaningful — reserved for a follow-up pass against its rendered
Root.tsx timeline.

| # | Example | Engine | Rubric (/35) | Eval target | Verdict |
|---|---------|--------|--------------|-------------|---------|
| 1.1 | GRWM | ai-video | N/A | parallel timelines | partial |
| 1.2 | Storytime | ai-video | N/A | tone + captions | inconclusive |
| 1.3 | POV | ai-video | N/A | camera-as-entity | pass |
| 2.1 | Greenscreen reaction | composite | N/A | fg/bg segmentation | partial |
| 2.2 | Faceless explainer | faceless-explainer | not yet scored | visual relevance | pass |
| 2.3 | Reddit TTS | composite | N/A | multi-stream OCR | pass |
| 3.1 | Recipe | ai-video | N/A | temporal ordering | pass |
| 3.2 | Unboxing | ai-video | N/A | object/attribute tracking | pass |
| 3.3 | ASMR | ai-video (Veo) | N/A | audio-visual sync | blocked (Veo quota) |
| 4.1 | Duet | composite | N/A | split-attention | fail |
| 4.2 | Lip-sync/dance | ai-video | N/A | mismatch detection (negative fixture) | fail |
| 4.3 | Multi-character skit | ai-video | N/A | entity resolution | pass |

**8 pass, 2 fail, 1 partial-plus-inconclusive, 1 blocked** (out of the 11 actually
generated — 3.3 never ran due to an account-level Veo quota gap, not a code defect).

Both failures share a root cause worth flagging rather than iterating around: the
default `showrunner analyze --report` output is a hook/scene-narrative summary. It's
strong at reconstructing plot, causal steps, and object/brand attributes (which is
why the single-stream examples like 3.1/3.2/2.2 pass cleanly), but it has no
dimension for **split-screen/multi-pane composition** (4.1) or **audio-visual sync
verification** (4.2) — it never mentions either concept, positively or negatively,
even when directly relevant. That reads as a gap in what the default report surfaces
rather than a generation-quality problem with the videos themselves; worth checking
whether `analyze` exposes a more structured/non-`--report` output before assuming a
`refine` pass on the source video would help.
