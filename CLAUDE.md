# CLAUDE.md — Showrunner

AI-powered video generation framework. `pip install showrunner`.

## Architecture

```
src/showrunner/
├── __init__.py          # Public API: Pipeline, Plan, Format, Feedback
├── pipeline.py          # Orchestrator: plan → assets → compose → render
├── plan.py              # Plan + Scene dataclasses (storyboard model)
├── config.py            # .showrunner.yaml loading + CLI override merging
├── feedback.py          # Feedback dataclass for plan/asset revision
├── formats/
│   ├── base.py          # Format ABC (plan, generate_assets, compose, revise)
│   ├── registry.py      # Entry point discovery via importlib.metadata
│   ├── faceless_explainer/  # Remotion + React animated explainers
│   │   ├── planner.py       # LLM → storyboard JSON
│   │   ├── assets.py        # LLM → TSX scene code + TTS narration
│   │   └── composer.py      # Generates Root.tsx for Remotion timeline
│   └── ai_video/            # AI video clips + FFmpeg
│       ├── planner.py       # LLM → storyboard with video gen prompts
│       └── assets.py        # VideoProvider clips + TTS narration
├── providers/
│   ├── registry.py      # Entry point discovery (showrunner.providers.<kind>)
│   ├── llm/             # LLMProvider ABC → anthropic, openai
│   ├── tts/             # TTSProvider ABC → kokoro, elevenlabs
│   ├── video/           # VideoProvider ABC → gemini, minimax
│   └── render/          # RenderProvider ABC → remotion, ffmpeg
│       └── template/    # Embedded Remotion TypeScript project
├── styles/
│   ├── resolver.py      # ResolvedStyle + preset loading
│   └── presets/         # 7 JSON presets (3b1b-dark, bold-neon, etc.)
└── cli/
    └── main.py          # Click CLI (create, formats, styles, voices, init)
```

## Pipeline Flow

```
Topic + Style
  → format.plan()           — LLM generates storyboard (Plan with Scenes)
  → format.generate_assets() — TTS audio + scene code or video clips
  → format.compose()        — Build Remotion Root.tsx or FFmpeg concat manifest
  → render.render()         — Remotion CLI or FFmpeg → final MP4
```

## Two Built-in Formats

| Format | Render | Visual Field | Use Case |
|--------|--------|-------------|----------|
| `faceless-explainer` | Remotion (React/TSX) | Animation code description | Educational, explainer |
| `ai-video` | FFmpeg (clip concat) | Video generation prompt | Cinematic, storytelling |

Both use the same `Plan`/`Scene` model — `Scene.visual` is interpreted differently by each format's planner prompt.

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
python -m pytest tests/ -v    # Run tests (111 tests)
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
| Modify the CLI | `cli/main.py` — Click commands |
| Change the storyboard format | `plan.py` — Plan/Scene dataclasses |
