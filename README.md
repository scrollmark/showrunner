# Showrunner

**Your coding agent is the director. Showrunner is the studio.**

Showrunner turns any coding agent (Claude Code, Cursor, Codex, Copilot, …)
into a video production system: workflows with staged contracts, a typed
motion design system, narration + music tooling, and machine-enforced
quality gates — so agent-made videos come out designed, not defaulted.

https://github.com/user-attachments/assets/977e15ef-d08e-45a9-800b-60943c16dba9

## How it works

You (or your agent) author the two creative artifacts — the **storyboard**
and the **visuals** — and drive the production through a staged CLI. Every
stage is validated; nothing renders until the whole project passes
`showrunner check`.

```
showrunner new my-video --workflow explainer --style 3b1b-dark
# → author storyboard.json
showrunner storyboard validate my-video
showrunner tts my-video                 # narration synthesized, durations measured
# → author src/scenes/*.tsx against the design system
showrunner scene validate my-video
showrunner compose my-video --music auto
showrunner check my-video               # the gate: schema + lint + types + timing
showrunner render my-video -o out/final.mp4
```

Open this repo in your coding agent and ask for a video — `AGENTS.md` and
`skills/` teach it the whole flow.

## Setup

```bash
pip install showrunner        # Python 3.11+
```

- Node.js ≥ 18 for the Remotion runtime (≥ 22 for the hyperframes runtime)
- TTS runs locally by default (kokoro) — no API key needed
- `pip install "showrunner[audio]"` for beat analysis (`music analyze`)

## Workflows

| Workflow | What it makes | Runtime |
|---|---|---|
| `explainer` | narrated animated explainer, 30–90s | remotion |
| `kinetic-typography` | type-driven motion piece, 8–45s | hyperframes |
| `carousel-reel` | beat-synced image reel from your images + music, 8–60s | hyperframes |

`showrunner workflows` prints each workflow's stage contract. Each stage
declares the artifact it produces and the check that gates it
(`src/showrunner/workflows/<name>/manifest.yaml`).

## What makes the output good

- **A real design system.** Scenes are written against typed tokens
  (colors, type roles, spacing, easing curves, a BPM rhythm grid), seven
  layout primitives, and a restricted background library. Lint + the
  TypeScript compiler reject hardcoded values, linear easing, and layout
  hand-rolling — the classic tells of generated video.
- **Measured, not assumed, timing.** Narration is synthesized first and
  scene durations stretch to the real audio; music beds duck under
  narration with a computed per-frame envelope and resolve on a
  beat-aligned outro.
- **Beat grids.** `showrunner music analyze` extracts BPM + beat times from
  your licensed tracks; beat-locked workflows enforce cut alignment to the
  frame.
- **One gate.** `showrunner check` runs every stage's validator and
  fingerprints the project; `render` refuses stale or failing projects.
- **Loudness done right.** `showrunner audio master` normalizes the final
  render to -14 LUFS so platforms don't re-level your mix.

## CLI reference

```bash
showrunner new DIR --workflow W --style S   # scaffold a project
showrunner workflows                        # workflows + stage contracts
showrunner storyboard validate DIR          # storyboard rules gate
showrunner tts DIR                          # narration + measured durations
showrunner scene validate DIR [SCENE]       # design-system lint + types
showrunner compose DIR [--music auto]       # build the timeline
showrunner check DIR                        # full quality gate → check.json
showrunner render DIR -o OUT.mp4            # gated render
showrunner preview DIR                      # live preview/studio
showrunner music list|add|analyze           # licensed catalog + beat grids
showrunner audio master IN -o OUT           # loudness normalization
showrunner styles | voices | providers      # discovery
```

Every validation command takes `--json` for machine-readable findings.

## Configuration

`.showrunner.yaml` in your working directory:

```yaml
default_style: 3b1b-dark
providers:
  tts: kokoro        # or elevenlabs
  render: remotion
kokoro:
  voice: af_heart
  speed: 1.0
```

## Style presets

`showrunner styles` lists all presets (3b1b-dark, bold-neon,
clean-corporate, dramatic-story, pastel-gradient, tech-startup,
warm-minimal, and more). Each preset is a full token set: palette, six
typography roles, spacing scale, motion curves, rhythm (BPM), and music
mood.

## Music

Showrunner ships no music. `showrunner music add` builds a catalog from
tracks you have licensed (license provenance stored per track);
`--music auto` picks deterministically by the preset's mood and BPM.

## Runtimes

- **remotion** — React/TSX scenes over the typed design system; used by
  narrated, layout-driven workflows.
- **hyperframes** — single-file HTML compositions with `data-*` timing
  (pinned CLI version); used by motion-graphics workflows. The runtime's
  own `check` (console, layout, determinism, contrast) runs inside
  `showrunner check`.

## Legacy one-shot mode

The original embedded pipeline (`showrunner create "topic"` — LLM plans and
codes scenes via an Anthropic/OpenAI API key) still works and remains
useful for headless smoke runs, but the agent-driven workflows above are
the primary interface.

## License

MIT
