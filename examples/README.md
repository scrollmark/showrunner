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

Filled in as Wave 3 completes — one row per example: engine, cost, rubric score,
eval-target pass/fail. See `results/manifest.json` for machine-readable detail.

| # | Example | Engine | Rubric (/35) | Eval target | Status |
|---|---------|--------|--------------|-------------|--------|
| 1.1 | GRWM | ai-video | — | parallel timelines | pending |
| 1.2 | Storytime | ai-video | — | tone + captions | pending |
| 1.3 | POV | ai-video | — | camera-as-entity | pending |
| 2.1 | Greenscreen reaction | composite | — | fg/bg segmentation | pending (needs E4) |
| 2.2 | Faceless explainer | faceless-explainer | — | visual relevance | pending |
| 2.3 | Reddit TTS | composite | — | multi-stream OCR | pending (needs E3+E4) |
| 3.1 | Recipe | ai-video | — | temporal ordering | pending |
| 3.2 | Unboxing | ai-video | — | object/attribute tracking | pending |
| 3.3 | ASMR | ai-video (Veo) | — | audio-visual sync | pending (needs E5) |
| 4.1 | Duet | composite | — | split-attention | pending (needs E4) |
| 4.2 | Lip-sync/dance | ai-video | — | mismatch detection (negative fixture) | pending |
| 4.3 | Multi-character skit | ai-video | — | entity resolution | pending (needs E1) |
