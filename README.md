# Showrunner

AI-powered video generation framework. Create animated social media videos from text topics with pluggable formats and providers.

https://github.com/user-attachments/assets/977e15ef-d08e-45a9-800b-60943c16dba9


## Quick Start

```bash
pip install "showrunner @ git+https://github.com/scrollmark/showrunner.git"
```

> **Not on PyPI.** Install from this repository. The name `showrunner` on
> PyPI belongs to an unrelated live-theatre package, so plain
> `pip install showrunner` silently installs the wrong project.

### Prerequisites

- Python 3.11+
- Node.js 18+ (for Remotion video rendering)
- An Anthropic API key (`ANTHROPIC_API_KEY` environment variable)

> **Before your first render:** the default format renders with Remotion,
> which requires a paid license for companies of 4+ people and for hosted or
> automated rendering. See [Licensing](#licensing) and
> [docs/licensing.md](docs/licensing.md).

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

Generate:

```bash
showrunner create "topic"                  # Topic → storyboard → assets → rendered MP4.
                                           # Key flags: --style/--override, --aspect-ratio,
                                           # --captions, --watermark, --music auto|none|<id>,
                                           # --dry-run (plan only), --auto-approve, --parallel,
                                           # --analyze [--sync] (upload for cloud analysis), --json
showrunner render plan.json                # Render a saved storyboard to video
showrunner refine <work_dir> <scene_id> \  # Regenerate ONE scene and re-render (~2-3 min)
  --instruction "..." --output out.mp4
showrunner resume <work_dir>               # Resume an interrupted create from its checkpoints
```

Export:

```bash
showrunner export <work_dir>               # Emit an editable timeline: OTIO (default),
                                           # or -f fcpxml|edl|aaf (needs showrunner[otio-all])
```

Cloud (see [docs/cloud.md](docs/cloud.md)):

```bash
showrunner login                           # Log in (browser OAuth; --with-password for
                                           # email+password — today's production path)
showrunner logout                          # Revoke (best-effort) + clear credentials
showrunner whoami                          # Show identity and token status
showrunner analyze clip.mp4                # Upload for analysis; prints the post_id
showrunner analyze --id <id> [--sync]      # Fetch results/artifacts (--report, --transcript,
                                           # --scenes, --caption, ...); --if-duplicate warn|reuse|fail
showrunner list                            # Your uploads (--local: offline ledger)
```

Discover:

```bash
showrunner formats                         # List video formats
showrunner styles                          # List style presets
showrunner voices                          # List TTS voices
showrunner providers                       # List discovered providers (installed vs configured)
showrunner music list|add|remove|inspect|where   # Manage the local background-music catalog
```

Setup:

```bash
showrunner init                            # Create a .showrunner.yaml config file
```

## Agent mode (`--json`)

Coding agents and other programs driving the CLI should pass `--json`
(either globally, `showrunner --json create ...`, or per command,
`showrunner create ... --json`) instead of scraping human prose:

- **stdout carries only JSON.** For `create`, `refine`, and `resume` it
  is a newline-delimited JSON (NDJSON) event stream — one object per
  line, each with an `"event"` discriminator. For the listing commands
  (`formats`, `styles`, `voices`, `providers`), `export`, and the cloud
  commands (`login`, `logout`, `whoami`, `list`, `analyze --id`) it is a
  single JSON document. `analyze` with a PATH streams NDJSON upload
  events — full shapes in [docs/cloud.md](docs/cloud.md#--json-shapes).
- **Human logging moves to stderr.**
- **Failures end with an `error` event and a non-zero exit code.**
- In human mode (no `--json`), the `WORKDIR: <path>` line on stdout is
  retained for back-compat with existing integrations.

### Stability contract

The schema below is **additive-only**: existing event names and fields
never change meaning or disappear. New events and new fields may appear
in any release, so consumers must ignore unknown events and fields.

### Event stream (`create`, `refine`, `resume`)

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
`export` prints `{"output_path", "format"}`. The cloud commands' JSON
shapes are documented in [docs/cloud.md](docs/cloud.md#--json-shapes).

## Agent Skill (Claude Code / Cursor / etc.)

Showrunner ships a first-party [Agent Skill](skills/showrunner/SKILL.md) so
coding agents can drive video generation correctly on the first try — the
prerequisites check, the `create` → inspect → `refine` loop, style/format
selection, quality self-review, and troubleshooting are all encoded in the
skill rather than left to trial and error.

Install it with the [`skills`](https://github.com/obra/skills) CLI:

```bash
npx skills add scrollmark/showrunner
```

Or copy it manually into your agent's skills directory:

```bash
# Claude Code (project-level)
mkdir -p .claude/skills/showrunner
cp skills/showrunner/SKILL.md .claude/skills/showrunner/

# Claude Code (user-level, all projects)
mkdir -p ~/.claude/skills/showrunner
cp skills/showrunner/SKILL.md ~/.claude/skills/showrunner/
```

Then ask your agent for a video ("make me a 9:16 explainer about black
holes") — it will pick up the skill automatically.

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

# Cloud server for `showrunner login` / cloud analysis (docs/cloud.md).
cloud:
  server_url: https://api.gpt.social
  # oauth (default) or firebase — see "Connecting to SocialGPT" below. The
  # `showrunner login --with-password` flag overrides this.
  auth_method: oauth
```

CLI arguments override config file values.

## Connecting to SocialGPT

Showrunner can upload any local video — or the render inside a
work_dir — to SocialGPT's cloud analyzer and fetch back a deep analysis
(hook, scene breakdown, transcript, themes, technical read).
**[docs/cloud.md](docs/cloud.md) is the full reference** — login methods
and credential storage, every `analyze` flag with sample output, exit
codes, the `--json` shapes, idempotent uploads and the local ledger,
`create --analyze [--sync]`, and troubleshooting. The 30-second version:

```bash
pip install "showrunner[cloud] @ git+https://github.com/scrollmark/showrunner.git"

# 1. Log in — today's production path is email + password:
showrunner login --with-password   # plain `showrunner login` is browser
                                   # OAuth, pending the server deploy (#55)

# 2. Upload — async by default; the bare post_id is the only stdout line:
id=$(showrunner analyze output/cats.mp4)

# 3. Get results whenever they're ready:
showrunner analyze --id "$id"                # one check: report, or exit 2
showrunner analyze --id "$id" --sync         # poll until ready (10 min cap)
showrunner analyze --id "$id" --transcript --caption   # artifacts combine
showrunner list                              # your uploads (--local: offline)
```

Or in one shot (`showrunner analyze clip.mp4 --sync`) — and straight
from generation:

```bash
showrunner create "topic" --auto-approve --analyze         # render, upload, print id
showrunner create "topic" --auto-approve --analyze --sync  # …and wait for the report
```

Essentials (full contracts in [docs/cloud.md](docs/cloud.md)):

- **Exit codes**: `0` success/ready · `1` real error or a terminally
  failed analysis (`failure_reason` on stderr) · `2` **not ready yet —
  retry later, not a failure** (also a `--sync` timeout) · `3` duplicate
  refused under `--if-duplicate fail`.
- **Clean stdout, safe to redirect**: stdout carries only the payload —
  the bare post_id for uploads, the artifact content for reads
  (`--transcript > script.txt` yields a clean file). Progress lives
  behind `--verbose`, on stderr. `--json` streams NDJSON events for
  uploads and prints one JSON object for `--id` reads.
- **Idempotent uploads**: the post_id is minted client-side (UUIDv4)
  before any bytes move; transient failures retry with the same id and
  interrupted uploads resume it — re-running `showrunner analyze` is
  always safe. Every upload is recorded in the local ledger
  (`~/.showrunner/analyses.jsonl`; browse with `showrunner list --local`).
- **Accounts created with Google sign-in have no password** — set one via
  the web app's password reset before `login --with-password`. In CI, set
  `SHOWRUNNER_TOKEN` to a pre-issued token instead of logging in.

## Video Formats

| Format | Renderer | Best for |
|--------|----------|----------|
| `faceless-explainer` (default) | Remotion (React/TSX) | Educational / explainer motion graphics |
| `ai-video` | FFmpeg (AI clip concat) | Cinematic, storytelling |
| `manim-explainer` | Manim CE + FFmpeg | Math animations (equations, graphs, geometry) |

### manim-explainer prerequisites

The `manim-explainer` format renders each scene with [Manim Community Edition](https://www.manim.community/) and stitches clips with FFmpeg:

```bash
pip install "showrunner[manim] @ git+https://github.com/scrollmark/showrunner.git"   # Manim CE >= 0.20
```

You also need:

- A **LaTeX toolchain** on PATH for `MathTex`/`Tex` equations (e.g. TinyTeX, MacTeX, or TeX Live — see the [Manim installation docs](https://docs.manim.community/en/stable/installation.html))
- **FFmpeg** on PATH (used by both Manim and the final concat/narration mix)

```bash
showrunner create "why does e^ipi = -1" --format manim-explainer
```

## Style Presets

| Preset | Description |
|--------|-------------|
| `3b1b-dark` | Navy/blue/gold, math education |
| `bold-neon` | Black/cyan/pink, gaming/tech |
| `clean-corporate` | White/blue, professional |
| `dramatic-story` | Black/gold/red, cinematic |
| `forest-breath` | Sage green/off-white, grounded and calm |
| `minty-fresh` | Mint green/cream, cheerful product marketing |
| `paper-press` | Cream/black/red, newspaper editorial |
| `pastel-gradient` | Lavender/purple, wellness |
| `sunny-editorial` | Warm yellow/cream/charcoal, long-form editorial |
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
   `pip install "showrunner[captions] @ git+https://github.com/scrollmark/showrunner.git"` (uses `faster-whisper` locally).
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
- **ffmpeg** — Clip concatenation for AI video formats

### Video
- **gemini** — Google Veo via Gemini API
- **minimax** — MiniMax video generation

### Adding a provider

Providers are discovered via entry points, just like formats — no core
edits needed. Implement the matching ABC (`showrunner/providers/<kind>/base.py`)
and register it in your package's `pyproject.toml` under
`showrunner.providers.{llm,tts,video,render}`:

```toml
[project.entry-points."showrunner.providers.tts"]
my-tts = "my_package:MyTTSProvider"
```

Then select it in `.showrunner.yaml` (`providers.tts: my-tts`). Constructor
kwargs come from the provider's config section (e.g. a top-level `my-tts:`
mapping). Run `showrunner providers` to see what's installed vs configured.

## Licensing

Showrunner itself is [MIT-licensed](LICENSE) — free for any use, including
commercial. However, **Showrunner's license does not grant you any rights to
Remotion or other third-party providers**. Showrunner shells out to the
Remotion install in your environment, so the license obligation falls on
whoever runs the render.

Key points (verified against [remotion.dev](https://www.remotion.dev/docs/license/terms)
and [remotion.pro](https://www.remotion.pro/license) as of July 2026):

- **Remotion** (used by the default `faceless-explainer` format) is free for
  individuals, nonprofits, and for-profit companies of **up to 3 people**.
  Larger companies need a paid plan: **Creators** ($25/seat/mo) for
  low-volume manual creation, or **Automators** ($0.01/render, $100/mo
  minimum) for automated/hosted rendering — the tier that applies to
  prompt-to-video services.
- The FFmpeg-based **`ai-video` format does not use Remotion** — no Remotion
  license implications on that path.
- Cloud TTS/video providers (ElevenLabs, Veo, MiniMax) have their own
  commercial-use terms.

Full details: [docs/licensing.md](docs/licensing.md).
