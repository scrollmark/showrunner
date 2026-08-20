# CLAUDE.md — Showrunner

AI-powered video generation framework. Installed from this repository, not from
PyPI — the `showrunner` name on PyPI is an unrelated live-theatre package.

## Architecture

```
src/showrunner/
├── __init__.py          # Public API: Pipeline, Plan, Format, Feedback
├── pipeline.py          # Orchestrator: plan → assets → compose → render (+ checkpoints, refine, resume)
├── plan.py              # Plan + Scene dataclasses (storyboard model)
├── config.py            # .showrunner.yaml loading + CLI override merging
├── feedback.py          # Feedback dataclass for plan/asset revision
├── checkpoints.py       # Per-stage checkpoint_<stage>.json files (resume support, docs/workdir-layout.md)
├── events.py            # Typed pipeline events (StageStarted, PlanReady, ...) — stability contract (docs/embedding.md)
├── costs.py             # Static pricing tables for Pipeline.estimate()
├── captions/            # Word-level captions: TTS timings → whisper → estimate; Caption JSON + pages + ASS
├── cloud/               # Showrunner Cloud: login/OAuth/Firebase auth, upload+analyze client, local ledger (docs/cloud.md)
├── exporters/
│   └── otio.py          # OTIO/FCPXML/EDL/AAF timeline export (`showrunner export`)
├── music/               # Local music catalog, mood picker, ducking (`showrunner music`, --music flags)
├── formats/
│   ├── base.py          # Format ABC (plan, generate_assets, compose, revise)
│   ├── registry.py      # Entry point discovery via importlib.metadata
│   ├── faceless_explainer/  # Remotion + React animated explainers
│   │   ├── planner.py       # LLM → storyboard JSON
│   │   ├── assets.py        # LLM → TSX scene code + TTS narration
│   │   ├── composer.py      # Generates Root.tsx for Remotion timeline
│   │   └── lint.py          # Static checks on generated TSX
│   ├── ai_video/            # AI video clips + FFmpeg
│   │   ├── planner.py       # LLM → storyboard with video gen prompts
│   │   └── assets.py        # VideoProvider clips + TTS narration; file:// local-asset ingestion
│   ├── manim_explainer/     # Manim CE math animations + FFmpeg
│   │   ├── planner.py       # LLM → spatially-planned storyboard
│   │   ├── assets.py        # LLM → Manim Scene code (repair loop) + TTS
│   │   └── renderer.py      # manim CLI invocation per scene
│   └── composite/           # Layered scenes: PiP/chromakey/split-screen (no LLM planner — --storyboard only)
├── providers/
│   ├── registry.py      # Entry point discovery (showrunner.providers.<kind>)
│   ├── llm/             # LLMProvider ABC → anthropic, openai
│   ├── tts/             # TTSProvider ABC → kokoro, elevenlabs
│   ├── video/           # VideoProvider ABC → gemini, minimax
│   └── render/          # RenderProvider ABC → remotion, ffmpeg
│       ├── template/         # Embedded Remotion TypeScript project
│       └── ffmpeg_compose.py # Compositing filtergraph builders (overlay/chromakey/hstack/vstack) for composite
├── styles/
│   ├── resolver.py      # ResolvedStyle + preset loading
│   └── presets/         # 11 JSON presets (3b1b-dark, bold-neon, etc.)
└── cli/
    ├── main.py          # Click CLI: create, render, refine, resume, export, analyze, list,
    │                    #   login/logout/whoami, formats, styles, voices, providers, music, init
    └── json_out.py      # --json agent mode: NDJSON event stream (additive-only schema, README)
```

## Pipeline Flow

```
Topic + Style
  → format.plan()           — LLM generates storyboard (Plan with Scenes)
  → format.generate_assets() — TTS audio + scene code or video clips
  → format.compose()        — Build Remotion Root.tsx or FFmpeg concat manifest
  → render.render()         — Remotion CLI or FFmpeg → final MP4
```

Each stage writes a `checkpoint_<stage>.json` into the work_dir
(`checkpoints.py`) so `showrunner resume` can pick up an interrupted run;
progress is surfaced to hosts via typed events (`events.py`, see
docs/embedding.md) and to agents as NDJSON under `--json`
(`cli/json_out.py`, schema in README).

## Four Built-in Formats

| Format | Render | Visual Field | Use Case |
|--------|--------|-------------|----------|
| `faceless-explainer` | Remotion (React/TSX) | Animation code description | Educational, explainer |
| `ai-video` | FFmpeg (clip concat) | Video generation prompt | Cinematic, storytelling |
| `manim-explainer` | Manim CE per scene + FFmpeg concat | Spatial layout description | Math animations (equations, graphs) |
| `composite` | FFmpeg (per-scene compositing + ai-video's concat) | N/A — scenes declare `layers`, not `visual` | Picture-in-picture, greenscreen reaction, split-screen/duet |

All use the same `Plan`/`Scene` model — `Scene.visual` is interpreted differently by each format's planner prompt. `composite` is the exception: its scenes declare `Scene.layers` instead (a base + overlays, or two-plus hstack/vstack layers — see `formats/composite/__init__.py`'s docstring) and it has no LLM planner, so it's only usable via `showrunner create --storyboard <plan.json>`.

## Provider System

Providers are swappable via config. Each has an ABC in `providers/<type>/base.py`:

- **LLM**: `generate(system, prompt)`, `generate_json(system, prompt)` — anthropic (default), openai
- **TTS**: `synthesize(text, output_path, voice, speed)` → `AudioFile` — kokoro (default, local), elevenlabs
- **Video**: `generate(prompt, duration, aspect_ratio, output_path)`, `poll(id)` — gemini (Veo 3.1), minimax
- **Render**: `setup(work_dir)`, `render(work_dir, output_path)`, `preview(work_dir)` — remotion (default), ffmpeg

Providers are discovered via entry points (groups `showrunner.providers.{llm,tts,video,render}`, mirrored in `providers/registry.py` built-ins) — same pattern as formats. `Pipeline._create_providers()` resolves configured names through the registry; only the selected provider's module is imported. Unknown names raise `ValueError` listing installed providers. `showrunner providers` lists discovered vs configured. External packages add providers by declaring an entry point — no core edits.

## Format Plugin System

Formats register via Python entry points (`showrunner.formats` group in pyproject.toml). The registry discovers them at runtime. External packages can add formats by declaring the entry point.

A Format subclass must implement: `plan()`, `generate_assets()`, `compose()`, `revise()`.

## Data Models

- **`Plan`**: title, total_duration, scenes list. Serializes to camelCase JSON (Remotion compat). `from_dict()` accepts both camelCase and snake_case.
- **`Scene`**: id, duration, narration, visual, transition
- **`Feedback`**: level (plan/asset/composition), scene_id, text, edits dict
- **`ResolvedStyle`**: colors, typography, animation dicts + `to_prompt_context()` for LLM prompts
- **`Config`**: default_format, default_style, providers dict, provider_config dict. Loaded from `.showrunner.yaml`.

## Development

```bash
pip install -e ".[dev]"       # Install with dev deps
python -m pytest tests/ -v    # Run tests (~690 tests; a handful need optional provider deps)
ruff check src/ tests/        # Lint
```

Tests use `unittest.mock` extensively — providers are mocked, no real API calls in tests.

## Git Conventions

- Commit messages: `feat:`, `fix:`, `test:`, `docs:`, `chore:` prefixes
- No Co-authored-by lines
- `.showrunner.yaml` is gitignored (user-specific config)

## Key Files for Common Tasks

| Task | Files |
|------|-------|
| Add a new video provider | Implement `providers/video/base.py` ABC (own package or module), add entry point under `showrunner.providers.video` in `pyproject.toml` (+ builtin table in `providers/registry.py` if in-tree), optional dep in `pyproject.toml` |
| Add a new format | New dir in `formats/`, implement Format ABC, add entry point in `pyproject.toml` |
| Add a new TTS provider | Implement `providers/tts/base.py` ABC, add entry point under `showrunner.providers.tts` (+ builtin table if in-tree) |
| Add a new render provider | Implement `providers/render/base.py` ABC, add entry point under `showrunner.providers.render` (+ builtin table if in-tree) |
| Add a style preset | New JSON in `styles/presets/`, follows existing schema (colors, typography, animation) |
| Modify the CLI | `cli/main.py` — Click commands; `cli/json_out.py` for the `--json` event schema (additive-only) |
| Change the storyboard format | `plan.py` — Plan/Scene dataclasses |
| Cloud login / analyze / list commands | `cloud/` (auth, client, analyze, ledger) + the command bodies in `cli/main.py`; contract in `docs/cloud.md` |
| Timeline export (`showrunner export`) | `exporters/otio.py` + the `export` command in `cli/main.py` |
| Manim math-animation format | `formats/manim_explainer/` (planner, assets w/ repair loop, renderer) |
| Compositing (PiP/chromakey/split-screen) | `formats/composite/` + `providers/render/ffmpeg_compose.py` (filtergraph builders) |
| Music catalog / background beds | `music/` (catalog, picker, ducking) + `music` command group and `--music*` flags in `cli/main.py` |
| Captions / word timings | `captions/` (generate, pages, ASS) — work_dir contract in README |
| Checkpoints / resume semantics | `checkpoints.py`, `pipeline.py`; contract in `docs/workdir-layout.md` |
