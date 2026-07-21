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

```bash
showrunner create "topic"     # Generate a video
showrunner styles             # List style presets
showrunner formats            # List video formats
showrunner voices             # List TTS voices
showrunner providers          # List discovered providers (installed vs configured)
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

# Cloud server for `showrunner login` / cloud analysis.
cloud:
  server_url: https://api.gpt.social
  # oauth (default) or firebase — see "Cloud login" below. The
  # `showrunner login --with-password` flag overrides this.
  auth_method: oauth
```

CLI arguments override config file values.

## Cloud login

Some features (uploading videos for cloud analysis) talk to the SocialGPT
cloud API and need a login.

**Try it today** — the production server currently authenticates with
Firebase email + password, via the `--with-password` flag:

```bash
pip install "showrunner[cloud]"
showrunner login --with-password  # prompts email + password (Firebase)
showrunner analyze output/cats.mp4
```

Sign in with the same email and password you use on the SocialGPT web
app. Accounts created with Google sign-in have no password — set one via
the web app's password reset first. `showrunner whoami` shows the
logged-in identity (decoded locally from the ID token) and
`showrunner logout` clears the stored credentials.

Plain `showrunner login` (no flag) is the browser OAuth PKCE flow — the
default, ready for when the server's OAuth chain deploys
([scrollmark/showrunner#55](https://github.com/scrollmark/showrunner/issues/55)
tracks the rollout). Until then, an OAuth attempt against production
fails with an "Unknown OAuth client" error and the CLI points you at
`--with-password`:

```bash
showrunner login              # opens your browser (OAuth PKCE)
showrunner login --no-browser # headless/SSH: paste the redirect URL back
```

Pick a default with `cloud.auth_method: oauth|firebase` in
`.showrunner.yaml` (`--with-password` overrides it);
`cloud.firebase_api_key` overrides the built-in public Firebase web API
key (e.g. for staging). `login`, `whoami`, and `logout` all support
`--json` for machine-readable output.

**Where credentials live**: the OS keyring when the optional `keyring`
package is installed and a keychain is available; otherwise
`~/.showrunner/credentials.json`, created with mode `0600`. Access tokens
last about an hour and are refreshed automatically (refresh tokens rotate
on every use).

**CI escape hatch**: set the `SHOWRUNNER_TOKEN` environment variable to a
pre-issued access token. It is used as-is for `Authorization: Bearer`,
skips credential storage entirely, and is never refreshed — issue
short-lived tokens per job.

The server defaults to the public API; point `--server` (or
`cloud.server_url` in `.showrunner.yaml`) elsewhere for staging.

## Cloud analysis (`showrunner analyze`)

Upload any local video — or the render inside a showrunner work_dir — for
the same deep analysis that powers SocialGPT's `get_video_analysis` (hook,
scene breakdown, themes, technical read). Requires a login (above).

`analyze` takes exactly one source: a PATH to upload, or `--id` for an
already-uploaded analysis. It is **async by default** — an upload returns
immediately with the minted post_id (the bare id is the only stdout line,
so it is scriptable), and you fetch the result whenever it is ready:

```bash
id=$(showrunner analyze output/cats.mp4)  # upload; bare post_id on stdout
showrunner analyze --id "$id"             # one check: report, or exit 2
showrunner analyze --id "$id" --sync      # wait until ready (10 min cap)
showrunner analyze output/cats.mp4 --sync # upload + wait in one shot
showrunner list                           # your uploads (see below)
```

PATH may be a video file (mp4, mov, m4v, avi, mkv, webm) or a work_dir
(the rendered mp4 is resolved automatically). Type and rate limits are
enforced server-side and reported with actionable messages. `--timeout`
caps the `--sync` wait (default 600s).

**Exit codes**: `0` = success/ready; `1` = real error, including a
terminally failed analysis (its `failure_reason` goes to stderr); `2` =
the analysis is not ready yet (short message on stderr — retry later, or
add `--sync`; a `--sync` timeout also exits 2).

**Artifact flags** (combinable; the default is `--report`) select what to
show once a result is available — with `--id`, or with a PATH under
`--sync`:

| Flag | Output |
|------|--------|
| `--report` | Human-readable analysis summary (default) |
| `--full` | Complete raw analysis JSON |
| `--transcript` | The spoken script — plain text (time-coded segments under `--json`) |
| `--overlays` | On-screen text (`text_overlay_segments`) |
| `--scenes` | Scene breakdown |
| `--caption` | Generate a social caption — server-side, anew on **every** call |
| `--video [FILE]` | Download the stored video (default name: the original filename from the ledger, else `<id>.mp4`) |
| `--video-url` | Print the signed download URL instead of downloading |

With several artifacts, human output prints titled sections; `--output
FILE` also writes the shown result to a file.

Under `--json`:

- An upload streams NDJSON events (additive-only contract, as `create`):
  `upload_progress`, optionally `duplicate_warning`, then a terminal
  `{"event": "submitted", "post_id": ...}` — or, with `--sync`,
  `analysis_pending` events and a terminal `done` carrying the requested
  artifact keys (plus `analysis`, kept for compatibility).
- `--id` prints ONE JSON object: `{"post_id", "status", ...}` with one
  key per requested artifact when ready; `{"status": "pending"}` with
  exit 2 while processing; `{"status": "failed", "failure_reason": ...}`
  with exit 1 on terminal failure.

Failures on the upload leg emit `{"event": "error", "stage": "analyze",
...}` and exit nonzero. `analysis_pending` is expected while the analyzer
works — it is not an error (under the hood the poll endpoint 404s until
the analysis exists, and the CLI treats that as "still processing").

**The local ledger**: every successful upload appends one JSON line —
`{post_id, file, sha256, size_bytes, uploaded_at, server}` — to
`~/.showrunner/analyses.jsonl` (file mode 0600; corrupt lines are
skipped, never fatal). If the same file bytes (sha256) were uploaded
within ~24h, `analyze` prints a gentle duplicate warning with the prior
post_id — and proceeds anyway.

**The generate→analyze loop**: `showrunner create "topic" --auto-approve
--analyze` uploads the finished render automatically and prints the
post_id after the render summary. It never polls — fetch the result later
with `showrunner analyze --id <id>`. The analyze step can never break the
render: if it fails (not logged in, network, quota), the video is still
on disk, the failure is reported (in `--json`: upload events then
`submitted` — or `error` — after the render's `done` event), and the exit
code is nonzero so scripts notice.

## Listing your uploads (`showrunner list`)

```bash
showrunner list                 # remote: your uploaded videos (drafts)
showrunner list --limit 50      # server-side limit (capped at 100)
showrunner list --status done   # only rows with a known matching status
showrunner list --local         # offline: the local upload ledger
```

The default (remote) list calls `GET /api/v1/drafts` and shows post_id,
name, age, and analysis status (`-` when unknown). **Note**: the remote
list currently requires a password (Firebase) session — OAuth tokens will
work once
[scrollmark/platform#15546](https://github.com/scrollmark/platform/issues/15546)
lands; under an OAuth session the CLI prints exactly that hint.
Pagination is server-side limit-only today (no cursors).

`--local` reads `~/.showrunner/analyses.jsonl` instead — recent uploads
from this machine, newest first; works offline and logged out. `--status`
is applied client-side and only matches rows whose status is known
(ledger rows carry none). Under `--json`, the remote list emits
`{"videos": [...raw server records...]}` and `--local` emits
`{"analyses": [...ledger records...]}`.

## Video Formats

| Format | Renderer | Best for |
|--------|----------|----------|
| `faceless-explainer` (default) | Remotion (React/TSX) | Educational / explainer motion graphics |
| `ai-video` | FFmpeg (AI clip concat) | Cinematic, storytelling |
| `manim-explainer` | Manim CE + FFmpeg | Math animations (equations, graphs, geometry) |

### manim-explainer prerequisites

The `manim-explainer` format renders each scene with [Manim Community Edition](https://www.manim.community/) and stitches clips with FFmpeg:

```bash
pip install "showrunner[manim]"   # Manim CE >= 0.20
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
