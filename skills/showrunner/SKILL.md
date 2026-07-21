---
name: showrunner
description: >
  Drive Showrunner — the AI-powered video generation framework — from an agent
  session. Use this skill whenever the user asks to create, refine, or export an
  animated video, explainer, or social clip with Showrunner (or asks for "a video
  about <topic>"). Covers install/prerequisite checks, the
  create → inspect → refine → export loop, style/format selection, parsing CLI
  output, quality self-review against the rubric, and troubleshooting
  Remotion/FFmpeg failures.
---

# Showrunner: agent driving guide

Showrunner turns a text topic into a finished MP4: an LLM plans a storyboard,
generates per-scene React/TSX animation code (or AI video clips), synthesizes
TTS narration, and renders with Remotion (or FFmpeg). You drive it through the
`showrunner` CLI. This guide is ordered the way a session should run.

## 1. Prerequisites check (do this first)

Verify before generating anything — failures here surface as confusing errors
later:

```bash
python3 --version        # need 3.11+
node --version           # need 18+ (Remotion renders via Node)
echo "${ANTHROPIC_API_KEY:+set}"   # must print "set" (planner + scene codegen)
showrunner --version     # confirms install
```

Install if missing:

```bash
pip install showrunner
```

Then create a project config (idempotent — it refuses to overwrite):

```bash
showrunner init          # writes .showrunner.yaml with sensible defaults
```

Defaults: format `faceless-explainer`, style `3b1b-dark`, LLM `anthropic`,
TTS `kokoro` (free, local — no extra key), render `remotion`, aspect `9:16`.
Edit `.showrunner.yaml` or pass CLI flags to override (flags win).

Discovery commands (cheap, safe to run any time):

```bash
showrunner formats    # available formats
showrunner styles     # style presets with descriptions
showrunner voices     # TTS voice ids
showrunner providers  # what's configured
```

## 2. Pick a format

| Format | Renderer | Best for | Cost/requirements |
|---|---|---|---|
| `faceless-explainer` (default) | Remotion (React/TSX codegen) | Educational, explainer, product, listicle — anything driven by typography + motion graphics | Node 18+, no extra API keys |
| `ai-video` | FFmpeg concat of generated clips | Cinematic, storytelling, live-action feel | A video provider (Gemini Veo / MiniMax) API key + FFmpeg installed |

Default to `faceless-explainer` unless the user explicitly wants
photorealistic/cinematic footage. It is cheaper, faster, and fully local after
the LLM calls.

## 3. Pick a style preset

Map topic + audience to a preset (run `showrunner styles` for the live list):

| Topic / audience | Preset |
|---|---|
| Math, science, education | `3b1b-dark` |
| Gaming, tech energy, hype | `bold-neon` |
| Business, B2B, professional | `clean-corporate` |
| Drama, history, true-crime, cinematic | `dramatic-story` |
| Wellness, mindfulness, lifestyle | `pastel-gradient` or `forest-breath` |
| SaaS, startup, product launch | `tech-startup` |
| Lifestyle, editorial, food | `warm-minimal` or `sunny-editorial` |
| News, opinion, essay | `paper-press` |
| Product marketing, cheerful | `minty-fresh` |

Fine-tune with free-form overrides instead of switching presets:

```bash
showrunner create "topic" --style 3b1b-dark --override "use green accents, faster pacing"
```

## 4. Create

```bash
showrunner create "Why do cats purr?" \
  --style 3b1b-dark \
  --aspect-ratio 9:16 \
  --auto-approve \
  --output output/cats.mp4
```

Useful flags: `--captions` (burn subtitles), `--watermark "@handle"`,
`--voice <id>` / `--speed 1.1` (TTS), `--music none|auto|<track-id>`,
`--parallel` (concurrent scene codegen), `--no-audio`.

Always pass `--auto-approve` in agent sessions — it skips the interactive
storyboard review.

**Cheap iteration trick**: `--dry-run` runs only the planner and prints the
storyboard JSON (title, scenes with `id`, `duration`, `narration`, `visual`,
`transition`) without rendering. Use it to sanity-check scene structure for
long or high-stakes topics before paying for a full render (~5–8 min).

### Parse the output — capture WORKDIR

`create` prints a machine-readable line the moment the working directory
exists:

```
WORKDIR: /tmp/showrunner-abc123
```

**Capture this path.** It is required for `refine` later. The final line on
success is `Video rendered: <path>`.

A `--json` event-stream mode (NDJSON events: `StageStarted`, `PlanReady`,
`WorkDirReady`, `SceneCompleted`, `RenderCompleted`, `PipelineFailed`, …) is
landing in a parallel PR;
once it merges, prefer `--json` and parse events instead of scraping prose.
Until then, the `WORKDIR:` and `Video rendered:` lines are the stable contract.

## 5. Inspect the work_dir

The work_dir is a full Remotion project you can read (and that `refine`
mutates in place):

```
<work_dir>/
├── src/
│   ├── Root.tsx          # composition timeline: scene order, durations, transitions
│   └── scenes/           # one generated TSX component per scene (PascalCase of scene_id)
│       ├── HookIntro.tsx
│       └── ...
├── public/
│   ├── audio/<scene_id>.wav   # per-scene TTS narration
│   └── music/                 # background music bed (if selected)
└── package.json, tsconfig.json
```

To review what was made: read `src/Root.tsx` for structure, then the scene
files whose content you want to check. Scene component names are the
PascalCase of the storyboard scene ids (`hook_intro` → `HookIntro.tsx`).

## 6. Refine (surgical single-scene edits)

Never re-run `create` to fix one scene. `refine` regenerates only the named
scene's TSX and re-renders (~2–3 min vs ~5–8 min for full create), reusing
TTS, sibling scenes, and the composition:

```bash
showrunner refine <work_dir> <scene_id> \
  --instruction "make the chart animate in from the left and slow the counter" \
  --output output/cats-v2.mp4
```

- `<scene_id>` is the snake_case storyboard id (e.g. `hook_intro`); fuzzy
  matching is tolerant, but if it errors it lists the available ids.
- `--instruction` and `--output` are required options.
- Pass `--style <preset>` if the video was created with a non-default style,
  so the refined scene stays on-palette.
- The work_dir is mutated in place — refine again as many rounds as needed.

## 7. Export for NLE handoff

For users who want to finish the edit in a real NLE (DaVinci Resolve, Final
Cut Pro, Premiere), Showrunner's `export` command emits an OTIO / FCPXML
timeline from a work_dir so the scene cuts, durations, and narration audio
land on an editable timeline instead of a flattened MP4. This is a
differentiator — offer it whenever the user mentions an editor. The `export`
command is landing in a parallel PR; check `showrunner --help` for it, and if
it is not present yet, hand off the work_dir path (it contains all per-scene
audio and the timeline structure in `Root.tsx`).

## 8. Cloud analysis (`showrunner analyze` / `showrunner list`)

Showrunner can upload a video to SocialGPT's cloud analyzer and get back a
deep analysis (hook, scene breakdown, themes, technical read) — the same
analysis that powers competitor research. Use it to review a render with
more rigor than frame-sampling, or to analyze any local video the user
provides. Requires the `[cloud]` extra and a login:

```bash
pip install "showrunner[cloud]"   # once
showrunner login --with-password  # once — prompts email + password (Firebase)
showrunner whoami                 # check login state (exit 0 = logged in)
```

`--with-password` is today's working path: the production server only
accepts Firebase email + password for now. Accounts created with Google
sign-in have no password; the user must set one via the web app's
password reset first. Plain `showrunner login` (no flag) is the browser
OAuth PKCE flow, which activates when the server's OAuth chain ships
(scrollmark/showrunner#55) — if it fails with "Unknown OAuth client",
the server chain is not deployed yet and the CLI will tell you to use
`--with-password`. In CI, set `SHOWRUNNER_TOKEN` to a pre-issued token
instead of logging in.

`analyze` is async by default and takes exactly one source — a PATH
(video file or work_dir; the rendered mp4 is resolved automatically) XOR
`--id`:

```bash
id=$(showrunner analyze output/cats.mp4)   # upload; bare post_id on stdout
showrunner analyze --id "$id"              # one check: report, or exit 2
showrunner analyze --id "$id" --sync       # wait until ready (--timeout)
showrunner analyze output/cats.mp4 --sync  # upload + wait in one shot
showrunner list --local                    # recent uploads (local ledger)
```

Exit codes: 0 = ready/success; 1 = real error (including a terminally
failed analysis — failure_reason on stderr); **2 = not ready yet** (also
for a `--sync` timeout) — exit 2 means "try again later", NOT a failure;
3 = duplicate refused under `--if-duplicate fail`.

Output is **clean stdout, safe to redirect**: stdout carries only the
payload (the bare post_id for an upload; the artifact content for
reads — `showrunner analyze --id X --transcript > script.txt` yields a
clean file). Progress/status lines are off by default; `--verbose`
prints them on stderr. Warnings and errors always land on stderr.

Uploads are **idempotent**: the post_id is minted client-side (UUIDv4)
before the bytes move, and transient failures (network errors, 5xx)
retry with the SAME id — 3 attempts, short backoff — so a retry never
creates a duplicate draft (4xx never retries). An interrupted upload's
id is resumed automatically the next time the same file is analyzed
(within ~24h, via the local ledger).

Artifact flags combine (default `--report`) and work with `--id` or with
a PATH under `--sync`: `--full` (raw JSON), `--transcript` (spoken
script), `--overlays` (on-screen text), `--scenes`, `--caption`
(server-generated anew each call), `--video [FILE]` (download),
`--video-url` (signed URL). Under `--json`: uploads stream NDJSON events
(`upload_progress`, `duplicate_warning`, `upload_resume`,
`upload_retry`) ending in `{"event": "submitted", "post_id": ...,
"deduped": false}` (or `done` with `--sync`); `--id` prints ONE object
`{"post_id", "status", + artifacts}`.

Notes for agents:

- Prefer the async flow: upload early, keep working, `--id` later.
  Every upload is recorded in `~/.showrunner/analyses.jsonl` (a
  "pending" line before the bytes move, an "uploaded" line after —
  latest line per post_id wins); recover lost ids with `showrunner
  list --local` (offline) or `showrunner list` (server-side; currently
  needs a `--with-password` session — OAuth works after
  scrollmark/platform#15546).
- Re-uploading identical bytes within ~24h triggers `--if-duplicate`
  (default `warn`: stderr warning with the prior post_id, then upload
  anyway). Prefer `--if-duplicate reuse` in agent loops — it prints
  the prior post_id WITHOUT uploading (exit 0; under `--json` the
  `submitted` event carries the prior record and `"deduped": true`).
  `--if-duplicate fail` refuses with exit 3 for strict pipelines.
- Server rejections (unsupported file type, rate limits, missing upload
  permission) come back as actionable error messages — follow the
  instruction in the message (convert/re-encode, wait, re-login).
  Supported types: mp4, mov, m4v, avi, mkv, webm.
- The generate→analyze loop: `showrunner create "topic" --auto-approve
  --analyze` renders, then uploads the output and prints the post_id
  after the render summary (it never polls). If the analyze step fails
  (e.g. not logged in) the exit code is nonzero BUT the render itself
  succeeded — check for the `Video rendered:` line (or the `done` event)
  before treating the run as failed, and just run `showrunner login
  --with-password` + `showrunner analyze <output>` to finish.

## 9. Self-review before declaring success

Do not declare the video done just because a file exists. Review the render
against `docs/quality-rubric.md` (seven dimensions, 0–5 each, 35 total:
typographic hierarchy, easing quality, transition sophistication,
audio-visual sync, layout density/rhythm, visual motifs, depth/texture).

Minimum agent pass: extract a few frames and check them —

```bash
ffmpeg -i output/cats.mp4 -vf "select='not(mod(n,90))'" -vsync vfr frames/%02d.png
```

Look for the classic failure tells: clipped or overflowing text, text
overlapping other elements, scenes that are one centered line on a flat
color, off-palette colors, an abrupt black tail at the end. Score honestly
against the rubric bands — below "Shippable" (24/35), run a `refine` round on
the weakest scene(s) before presenting the result. One refine round is
normal, not a failure.

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ANTHROPIC_API_KEY` / auth error at plan stage | Key missing or wrong | Export the key; verify with `echo "${ANTHROPIC_API_KEY:+set}"` |
| `node: command not found` or Remotion install fails | Node < 18 or missing | Install Node 18+; re-run — the work_dir template runs `npm install` on first render |
| Render fails with a TSX/TypeScript error naming a scene file | Generated scene code didn't compile | `showrunner refine <work_dir> <scene_id> --instruction "fix the compile error: <paste error>" --output <path>` |
| Text clipped / overlapping in a scene | Layout bug in generated scene | `refine` that scene: "keep all text inside safe margins, reduce font size if needed" |
| Colors look wrong / off-brand | Preset mismatch | Re-create with a different `--style`, or `--override "use <colors>"` |
| Narration cut off or out of sync | Scene duration too short for its narration | `refine` with "extend the scene to fit the narration" — or regenerate with `--dry-run` first and check durations |
| `ffmpeg: command not found` (ai-video format) | FFmpeg not installed | `brew install ffmpeg` / `apt install ffmpeg`, or switch to `faceless-explainer` |
| Video provider errors (ai-video) | Missing Gemini/MiniMax key | Set the provider key in `.showrunner.yaml`, or use `faceless-explainer` |
| `kokoro` TTS import error | Optional TTS dep not installed | `pip install "showrunner[kokoro]"`, or `--no-audio` to skip narration |
| Music command/flag confusion | — | `--music none` disables, `--music auto` mood-picks from the preset, `--music-seed` makes the pick deterministic |
| Same topic keeps picking the same music track | Seed defaults to the topic | Pass a different `--music-seed` |
| `analyze` says not logged in | No cloud session | `showrunner login --with-password` (or `SHOWRUNNER_TOKEN` in CI), then re-run `showrunner analyze` |
| `login` fails with "Unknown OAuth client" | Server's OAuth chain not deployed yet | Use `showrunner login --with-password` (email + password) |
| `analyze --id` exits 2 | Analysis still processing — NOT an error | Retry in ~30s, or use `--sync` to wait |
| Lost a post_id | — | `showrunner list --local` (ledger, offline) or `showrunner list` (server; needs a `--with-password` session for now) |
| `analyze` refuses the upload (unsupported type, rate limited, missing permission) | Server-side limits | Follow the message: convert to mp4/mov/m4v/avi/mkv/webm (`ffmpeg -i input -c copy output.mp4`), wait out the rate limit, or `showrunner login --with-password` again |
| Upload dies mid-transfer (network drop, 5xx) | Transient failure | The CLI already retried 3× with the same client-minted id; just re-run `showrunner analyze <path>` — it resumes the SAME id from the ledger, so no duplicate drafts |
| `analyze` exits 3 | Same bytes uploaded within ~24h under `--if-duplicate fail` | Use the prior post_id from the message (`analyze --id <id>`), or re-run with `--if-duplicate warn`/`reuse` |
| `create --analyze` exits nonzero but the video exists | Analyze step failed after a successful render | The render is fine — fix the analyze issue (usually login) and run `showrunner analyze <output>` |

When a full `create` fails mid-run, the `WORKDIR:` line has usually already
been printed — inspect the work_dir to see how far it got before retrying.
