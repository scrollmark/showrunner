# Showrunner

AI-powered video generation framework. Create animated social media videos from text topics with pluggable formats and providers.

https://github.com/user-attachments/assets/977e15ef-d08e-45a9-800b-60943c16dba9


## Quick Start

```bash
pip install showrunner
```

### Prerequisites

- Python 3.11+
- Node.js 18+ (for Remotion video rendering)
- An Anthropic API key (`ANTHROPIC_API_KEY` environment variable)

### Generate a video

```bash
showrunner create "Why do cats purr?"
```

### Customize

```bash
showrunner create "The history of the internet" \
  --style bold-neon \
  --aspect-ratio 16:9 \
  --captions \
  --watermark "@mychannel"
```

### Available commands

```bash
showrunner create "topic"     # Generate a video
showrunner styles             # List style presets
showrunner formats            # List video formats
showrunner voices             # List TTS voices
showrunner providers          # Show configured providers
showrunner init               # Create config file
```

## Agent mode (`--json`)

Coding agents and other programs driving the CLI should pass `--json`
(either globally, `showrunner --json create ...`, or per command,
`showrunner create ... --json`) instead of scraping human prose:

- **stdout carries only JSON.** For `create` and `refine` it is a
  newline-delimited JSON (NDJSON) event stream — one object per line,
  each with an `"event"` discriminator. For the listing commands
  (`formats`, `styles`, `voices`, `providers`) it is a single JSON
  document.
- **Human logging moves to stderr.**
- **Failures end with an `error` event and a non-zero exit code.**
- In human mode (no `--json`), the `WORKDIR: <path>` line on stdout is
  retained for back-compat with existing integrations.

### Stability contract

The schema below is **additive-only**: existing event names and fields
never change meaning or disappear. New events and new fields may appear
in any release, so consumers must ignore unknown events and fields.

### Event stream (`create`, `refine`)

| Event | Fields | Meaning |
|-------|--------|---------|
| `plan_ready` | `title`, `scenes` (count), `total_duration` (s), `plan` (full storyboard object) | Storyboard planned |
| `work_dir_ready` | `work_dir` | Work directory created (pass it to `showrunner refine`) |
| `stage_started` | `stage` (`plan`/`assets`/`compose`/`render`/`refine`/...), `progress_pct` (0-100 or null) | Stage began |
| `stage_completed` | `stage`, `progress_pct` | Stage finished |
| `asset_progress` | `scene_id`, `kind` (`tts`\|`code`\|`clip`), `status` (`started`\|`completed`), `index`/`total` or `duration_seconds` | Per-scene asset progress |
| `scene_failed` | `scene_id`, `error` | A scene exhausted its codegen retries |
| `repair_attempt` | `attempt`, `error_excerpt` | Reserved for the render repair loop (not yet emitted) |
| `done` | `output_path`, `work_dir`; optional `usage`, `cost_usd`, `dry_run`, `preview` | Terminal success. `output_path`/`work_dir` are null for `--dry-run` |
| `error` | `stage`, `message` | Terminal failure; the process exits non-zero |
| `cancelled` | `work_dir` (resumable, may be null) | Terminal cancellation |

Example:

```bash
$ showrunner create "Why do cats purr?" --json 2>/dev/null
{"event": "stage_started", "stage": "plan", "progress_pct": 0.0}
{"event": "plan_ready", "title": "Why Do Cats Purr?", "scenes": 6, "total_duration": 42, "plan": {...}}
{"event": "stage_completed", "stage": "plan", "progress_pct": 10.0}
{"event": "work_dir_ready", "work_dir": "/tmp/showrunner-abc123"}
{"event": "asset_progress", "scene_id": "hook", "kind": "code", "status": "completed", "index": 1, "total": 6}
...
{"event": "done", "output_path": "output/why-do-cats-purr.mp4", "work_dir": "/tmp/showrunner-abc123"}
```

### Single-document commands

`formats`, `styles`, `voices`, and `providers` print one JSON object:
`{"formats": [{"name", "description"}, ...]}`, `{"styles": [...]}`,
`{"voices": [...]}`, `{"providers": {"llm": "anthropic", ...}}`.

## Configuration

Create `.showrunner.yaml` in your project:

```yaml
default_format: faceless-explainer
default_style: 3b1b-dark

providers:
  llm: anthropic
  tts: kokoro
  render: remotion

anthropic:
  model: claude-sonnet-4-5-20250929

kokoro:
  voice: af_heart
  speed: 1.0

output:
  aspect_ratio: "9:16"
  captions: false

# Max render→repair retries: on a failed render the error output is fed
# back to the LLM (Format.revise) and the render retried. 0 disables.
repair_attempts: 2
```

CLI arguments override config file values.

## Style Presets

| Preset | Description |
|--------|-------------|
| `3b1b-dark` | Navy/blue/gold, math education |
| `bold-neon` | Black/cyan/pink, gaming/tech |
| `clean-corporate` | White/blue, professional |
| `dramatic-story` | Black/gold/red, cinematic |
| `pastel-gradient` | Lavender/purple, wellness |
| `tech-startup` | Dark/indigo/pink, SaaS |
| `warm-minimal` | Cream/brown, lifestyle |

Custom style overrides:

```bash
showrunner create "topic" --style 3b1b-dark --override "use green accents, faster pacing"
```

## As a Library

```python
from showrunner import Pipeline

pipeline = Pipeline(format_name="faceless-explainer")
video_path = pipeline.run(
    "Why do cats purr?",
    style="3b1b-dark",
    captions=True,
)
```

### Dry run (plan only, no render)

```python
plan = pipeline.run("topic", dry_run=True)
print(plan.to_json())
```

## Captions (work_dir contract)

`--captions` produces word-level, TikTok-style captions in both built-in
formats. After TTS, each scene's word timings are written into the work_dir
(printed as `WORKDIR: <path>` during create) as:

```
captions/{scene_id}.json
```

Each file is a `Caption[]` array matching the `@remotion/captions` shape, so
exporters and NLE handoff tools can consume it directly:

```json
[
  { "text": "Cats", "startMs": 0, "endMs": 280, "timestampMs": 140 },
  { "text": "purr", "startMs": 280, "endMs": 590, "timestampMs": 435 }
]
```

Word timing sources, in preference order:

1. **TTS timing metadata** — Kokoro token timestamps are used directly (exact
   alignment, no extra cost).
2. **Whisper transcription** — install the optional dependency with
   `pip install "showrunner[captions]"` (uses `faster-whisper` locally).
3. **Estimation** — words are distributed proportionally across the audio
   duration as a last resort.

Rendering:

- **faceless-explainer** — captions are grouped into short pages and rendered
  by a Remotion overlay (`src/captions/captions.generated.ts`), styled from
  the active style preset (caption font family, `colors.text` for unspoken
  words, `colors.accent` highlight for the spoken word).
- **ai-video** — the same JSON is converted to `captions.ass` with karaoke
  word-highlight tags and burned in by FFmpeg's `ass` filter.

## Creating Format Plugins

Formats are Python packages that register via entry points:

```python
from showrunner import Format, Plan, Feedback
from pathlib import Path

class MyFormat(Format):
    name = "my-format"
    description = "My custom video format"
    required_providers = ["llm", "tts", "render"]

    def plan(self, topic, style, config, llm):
        ...

    def generate_assets(self, plan, providers, work_dir):
        ...

    def compose(self, plan, assets, work_dir, **kwargs):
        ...

    def revise(self, plan, feedback, llm):
        ...
```

Register in your package's `pyproject.toml`:

```toml
[project.entry-points."showrunner.formats"]
my-format = "my_package:MyFormat"
```

Then it's automatically available:

```bash
showrunner create "topic" --format my-format
```

## Providers

### LLM
- **anthropic** (default) — Claude via Anthropic API
- **openai** — GPT via OpenAI API

### TTS
- **kokoro** (default) — Free local TTS (82M params, Apache 2.0)
- **elevenlabs** — Cloud TTS (paid API)

### Render
- **remotion** (default) — React-based programmatic video

## License

MIT
