# CLAUDE.md — Showrunner

AI-powered video generation framework. `pip install showrunner`.

> **Asked to MAKE A VIDEO?** Stop here — read `AGENTS.md` and follow
> `skills/INDEX.md`. This file documents developing showrunner itself.

## Architecture

Agent-first: a coding agent drives production through staged CLI commands
and repo skills; Python owns validation, synthesis, composition, and
rendering. Workflow contracts are YAML manifests; `showrunner check` is the
machine-enforced gate between authoring and rendering.

```
src/showrunner/
├── __init__.py          # Public API: Pipeline, Plan, Format, Feedback
├── project.py           # ProjectManifest (showrunner.json) + DIMENSIONS
├── storyboard.py        # Finding + validate_storyboard (workflow rules)
├── checks.py            # Named stage checks + run_checks → check.json + fingerprint
├── workflows/           # WorkflowSpec loader + <name>/manifest.yaml (package data)
│   ├── explainer/           # remotion: storyboard→narration→scenes→compose→render
│   ├── kinetic-typography/  # hyperframes: type-driven pieces
│   └── carousel-reel/       # hyperframes: beat-synced image reels (music gate)
├── plan.py              # Plan + Scene dataclasses (storyboard model)
├── pipeline.py          # Legacy one-shot orchestrator (embedded LLM calls)
├── config.py            # .showrunner.yaml loading
├── events.py            # Typed pipeline events + CancelToken (legacy embed API)
├── cli/
│   ├── main.py              # Click group; command registration
│   ├── project_cmds.py      # new (scaffold + runtime dispatch)
│   ├── storyboard_cmds.py   # storyboard validate (+ shared loaders/echo)
│   ├── tts_cmds.py          # tts (narration.json + duration stretch-back)
│   ├── scene_cmds.py        # scene validate (lint + tsc per scene)
│   ├── compose_cmds.py      # compose (Root.tsx from storyboard + narration)
│   ├── check_cmds.py        # check (the gate)
│   ├── render_cmds.py       # render/preview (check-gated, runtime dispatch)
│   └── audio_cmds.py        # audio master (ffmpeg loudnorm)
├── formats/             # Legacy Format plugins (entry points: showrunner.formats)
│   ├── faceless_explainer/  # planner/assets(codegen)/composer/lint/music_staging
│   └── ai_video/
├── providers/
│   ├── factory.py       # Shared provider construction (CLI + Pipeline)
│   ├── llm/             # anthropic, openai (legacy pipeline only)
│   ├── tts/             # kokoro (local, default), elevenlabs
│   ├── video/           # gemini (Veo), minimax
│   └── render/          # remotion (embedded template/), ffmpeg,
│                        # hyperframes (pinned npx CLI wrapper)
├── styles/              # ResolvedStyle + presets/*.json (token sets)
└── music/               # catalog, picker, selection, ducking, analyze (BPM), cli
skills/                  # Agent-facing: INDEX.md router, workflows/, craft/
AGENTS.md                # Rule Zero for agents producing videos
```

## The staged flow (primary interface)

```
new → [author storyboard.json] → storyboard validate → tts
    → [author visuals] → scene validate (remotion) → compose (remotion)
    → check → render
```

- Projects are persistent directories with a `showrunner.json` manifest.
- `check.json` carries a sha256 fingerprint of the gated artifacts;
  `render` refuses when it's missing/failed/stale (`--force` bypasses).
- Runtimes: `remotion` (React/TSX + design system) and `hyperframes`
  (single-file HTML, version pinned in `providers/render/hyperframes.py`).

## Key invariants

- Workflow manifests are package data — a new workflow is
  `workflows/<name>/manifest.yaml` + `skills/workflows/<name>/SKILL.md`;
  `tests/test_skills_surface.py` enforces the pairing and that skills only
  reference real CLI commands.
- Named checks live in `checks.py:CHECKS`; stages reference them by name.
- Generated files (`Root.tsx`, `preset.generated.ts`,
  `envelope.generated.ts`) are tool-owned; commands regenerate them.
- Scene TSX must pass `formats/faceless_explainer/lint.py` + `tsc` — the
  design system is enforced, not suggested.

## Development

```bash
pip install -e ".[dev]"       # or: uv pip install -e ".[dev]"
python -m pytest tests/ -v    # Run tests (260+)
ruff check src/ tests/        # Lint
```

Tests use `unittest.mock` extensively — providers and subprocesses are
mocked; no real API calls, npm, npx, or ffmpeg in tests.

## Git Conventions

- Commit messages: `feat:`, `fix:`, `test:`, `docs:`, `chore:` prefixes
- No Co-authored-by lines
- `.showrunner.yaml` is gitignored (user-specific config)
- `docs/superpowers/` stays untracked (local working notes)

## Key Files for Common Tasks

| Task | Files |
|------|-------|
| Add a workflow | `src/showrunner/workflows/<name>/manifest.yaml`, `skills/workflows/<name>/SKILL.md`, INDEX row; new named checks in `checks.py` if needed |
| Add a stage check | `checks.py` (`CHECKS` map + function), reference by name in manifests |
| Add a CLI command | new module in `cli/`, register in `cli/main.py`, cover in `tests/` |
| Add a render runtime | provider in `providers/render/`, wire `factory.create_render`, `project_cmds._scaffold_runtime`, `render_cmds._runtime_provider` |
| Add a TTS/LLM/video provider | provider module + `providers/factory.py` + optional dep in `pyproject.toml` |
| Add a style preset | JSON in `styles/presets/` (palette, 6 type roles, spacing, motion, rhythm, music) |
| Change storyboard rules | `storyboard.py` + workflow `constraints` |
| Change the design system | `providers/render/template/src/{tokens,layouts,backgrounds,motion}` + `formats/faceless_explainer/lint.py` + `skills/craft/scene-code.md` |
