# Contributing to Showrunner

Thanks for your interest in contributing! Showrunner is an open-source AI video generation framework.

## Getting Started

```bash
git clone https://github.com/scrollmark/showrunner.git
cd showrunner
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Requires Python 3.11+.

## Development Workflow

1. Fork the repo and create a feature branch
2. Write tests first — we use TDD
3. Implement the feature
4. Run `python -m pytest tests/ -v` and `ruff check src/ tests/`
5. Open a pull request

## Running Tests

```bash
python -m pytest tests/ -v          # All tests
python -m pytest tests/test_foo.py  # Single file
python -m pytest -k "test_name"     # Single test
```

Tests mock all external APIs (Anthropic, Google, Minimax, etc.). No API keys needed to run the test suite.

## Project Structure

```
src/showrunner/
├── pipeline.py          # Core orchestrator
├── plan.py              # Data models (Plan, Scene)
├── formats/             # Video format plugins
│   ├── faceless_explainer/  # Remotion + React
│   └── ai_video/            # AI video clips + FFmpeg
├── providers/           # Pluggable backends
│   ├── llm/             # Language models (anthropic, openai)
│   ├── tts/             # Text-to-speech (kokoro, elevenlabs)
│   ├── video/           # Video generation (gemini, minimax)
│   └── render/          # Video rendering (remotion, ffmpeg)
├── styles/              # Style presets
└── cli/                 # Click CLI
```

## Adding a Provider

Providers follow the strategy pattern. To add a new one:

1. Check the ABC in `providers/<type>/base.py` for the interface
2. Create a new file (e.g., `providers/tts/my_tts.py`)
3. Implement the abstract methods
4. Wire it into `pipeline.py:_create_providers()`
5. Add an optional dependency in `pyproject.toml` if needed
6. Write tests with mocked API calls

## Adding a Format

Formats are plugins discovered via entry points.

1. Create a new directory under `formats/`
2. Implement the `Format` ABC (`plan`, `generate_assets`, `compose`, `revise`)
3. Register it in `pyproject.toml`:
   ```toml
   [project.entry-points."showrunner.formats"]
   my-format = "showrunner.formats.my_format:MyFormat"
   ```
4. Write tests covering the full format flow

## Code Style

- **Linter**: ruff (configured in `pyproject.toml`)
- **Line length**: 100 characters
- **Target**: Python 3.11
- **Imports**: Group by stdlib, third-party, local. Use `from __future__ import annotations`.
- **Type hints**: Use them for function signatures. `str | None` over `Optional[str]`.
- **Docstrings**: Module-level docstrings on all files. Function docstrings where behavior isn't obvious from the name.

## Commit Messages

Use conventional prefixes:

- `feat:` — New feature
- `fix:` — Bug fix
- `test:` — Tests only
- `docs:` — Documentation
- `chore:` — Maintenance, deps, config

## What We're Looking For

- New video providers (Runway, Kling, Pika, etc.)
- New TTS providers
- New format plugins
- Style presets
- Bug fixes and test coverage improvements
- Documentation improvements

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
