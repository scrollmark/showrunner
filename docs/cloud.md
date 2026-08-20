# Showrunner Cloud: login, video analysis, uploads

The definitive reference for connecting showrunner to SocialGPT's cloud
API: logging in, uploading videos for deep analysis, fetching results
and artifacts, the local upload ledger, and the `create --analyze`
integration. The README has a
[quick-start](../README.md#connecting-to-socialgpt); this document is
the full contract.

Everything here requires the optional cloud dependency group:

```bash
pip install "showrunner[cloud] @ git+https://github.com/scrollmark/showrunner.git"      # httpx
pip install keyring                  # optional: OS-keychain credential storage
```

## Contents

- [Overview and architecture](#overview-and-architecture)
- [Login (`showrunner login` / `whoami` / `logout`)](#login)
- [Where credentials live](#where-credentials-live)
- [`showrunner analyze` — full reference](#showrunner-analyze--full-reference)
  - [Sources: PATH xor `--id`](#sources-path-xor---id)
  - [Artifact flags](#artifact-flags)
  - [`--sync` and `--timeout`](#--sync-and---timeout)
  - [Exit codes](#exit-codes)
  - [Output contract (quiet stdout)](#output-contract-quiet-stdout)
  - [`--json` shapes](#--json-shapes)
- [Idempotent uploads](#idempotent-uploads)
  - [`--if-duplicate {warn,reuse,fail}`](#--if-duplicate-warnreusefail)
- [The local ledger](#the-local-ledger)
- [`showrunner list`](#showrunner-list)
- [`create --analyze [--sync]`](#create---analyze---sync)
- [Analysis payload shapes](#analysis-payload-shapes)
- [Troubleshooting](#troubleshooting)

## Overview and architecture

```
showrunner CLI                SocialGPT platform
──────────────                ──────────────────
showrunner login  ──────────► Firebase Identity Toolkit (email+password)
                              or {server}/oauth/* (PKCE, pending deploy)

showrunner analyze clip.mp4 ► POST /api/v1/drafts          (multipart upload)
                                   │
                                   ▼
                              async analyzer (~30–60s typical)
                                   │
showrunner analyze --id <id> ► GET /api/v1/drafts/{id}/analysis
                              (404 = still processing; 200 = the analysis)

other endpoints:              GET  /api/v1/drafts                  (list)
                              GET  /api/v1/drafts/{id}/video       (signed URL)
                              POST /api/v1/drafts/{id}/generate-caption
```

The upload endpoints are SocialGPT's **drafts** bridge. An upload creates
a draft under your account and queues the same deep analysis that powers
SocialGPT's `get_video_analysis` (hook, scene breakdown, themes,
technical read). Analysis is **asynchronous**: the upload returns
immediately with a `post_id`, and the analysis appears at the polling
endpoint when the analyzer finishes.

One deliberate convention: on `GET /api/v1/drafts/{id}/analysis`, **404
means "still processing"** — because the `post_id` was just minted by a
successful upload, a 404 there can only mean the analysis does not exist
*yet*. The CLI treats it as pending and never as an error. 404s on every
other endpoint remain real errors.

Every API request carries `Authorization: Bearer <token>` and
`X-Client-Surface: cli`. Expired tokens are refreshed proactively (from
the stored expiry) and reactively (exactly one automatic
refresh-and-retry on a 401).

The default server is `https://api.gpt.social`. Point elsewhere (e.g.
staging) with `--server` on any cloud command, or persistently:

```yaml
# .showrunner.yaml
cloud:
  server_url: https://api.gpt.social
  auth_method: oauth        # or firebase; --with-password overrides
  # firebase_api_key: ...   # override the shipped public web API key
```

## Login

Two methods exist. **What works against production today is
`--with-password`**; plain `showrunner login` (browser OAuth) is the
default-in-waiting.

### Email + password (`--with-password`) — works today

```bash
showrunner login --with-password   # prompts Email, then Password (hidden)
```

Signs in against Firebase Auth via Google's public Identity Toolkit REST
API — the same way `firebase-tools` does — using the SocialGPT project's
public web API key (Firebase web API keys identify the project, not a
secret; the production frontend ships the same key to every browser).
Use the same email and password as the SocialGPT web app.

**Accounts created with Google sign-in have no password.** Set one via
the web app's password-reset flow first, or wait for browser OAuth login
to reach production. The CLI maps the Identity Toolkit error codes to
actionable messages (wrong password, unknown email, account disabled,
too many attempts).

Firebase ID tokens last about an hour; the CLI refreshes them
automatically via Google's secure-token endpoint (refresh tokens may
rotate; the newest one is persisted). Refresh happens eagerly — within 5
minutes of expiry — so a long upload never straddles the expiry
mid-request.

### Browser OAuth (default, pending server deploy)

```bash
showrunner login              # opens your browser (OAuth 2.1 PKCE)
showrunner login --no-browser # headless/SSH: prints the authorize URL,
                              # you paste the redirect URL (or code) back
```

An RFC 8252 native-app flow: public client `showrunner-cli` (no secret),
PKCE S256, loopback redirect `http://127.0.0.1:<ephemeral-port>/callback`,
scopes `analysis:read analysis:upload offline_access`, and a `resource`
parameter of `{server_url}/api/v1`. Access tokens last ~1h; refresh
tokens rotate on every use. The flow times out after 5 minutes waiting
for the browser callback.

This activates once the server's OAuth chain deploys
([scrollmark/showrunner#55](https://github.com/scrollmark/showrunner/issues/55)).
Until then, an OAuth attempt against production fails with an **"Unknown
OAuth client"** error, which the CLI detects and answers with a hint:

```
The server does not recognize the CLI's OAuth client — its OAuth login
chain is probably not deployed yet. Log in with email + password instead:

  showrunner login --with-password
```

Pick a persistent default with `cloud.auth_method: oauth|firebase` in
`.showrunner.yaml`; the `--with-password` flag always overrides it.

### `whoami` and `logout`

```bash
showrunner whoami    # identity + token status; exit 1 when not logged in
showrunner logout    # revoke (best-effort) and clear stored credentials
```

- Under a **firebase** session, `whoami` decodes the stored ID token's
  claims locally (email, user id, expiry) — display only, no signature
  check; the server verifies tokens on every request. Under an **oauth**
  session it calls `GET /api/v1/me` (best-effort; degrades to local token
  info when the server is unreachable).
- `logout` attempts RFC 7009 revocation at `{server}/oauth/revoke` for
  OAuth sessions (best-effort — local credentials are cleared either
  way). Firebase sessions are cleared locally only.
- `login`, `whoami`, and `logout` all support `--json` (a single JSON
  document) and `--server`.

## Where credentials live

Lookup order — first hit wins:

1. **`SHOWRUNNER_TOKEN` environment variable** — the CI escape hatch.
   Used as-is for `Authorization: Bearer`; credential storage is never
   read or written for it and there is no refresh — issue short-lived
   tokens per job. If the server rejects it (401), the CLI says so
   rather than trying to refresh.
2. **OS keyring** (when the optional `keyring` package is installed and
   a keychain is available) — one entry per server URL under the
   `showrunner` service.
3. **`~/.showrunner/credentials.json`** — created with file mode `0600`
   (directory `0700`), keyed by server URL, supports multiple servers.

`showrunner login` prints which backend stored the credentials.

## `showrunner analyze` — full reference

```
showrunner analyze [PATH | --id ID] [flags]
```

Upload a video for cloud analysis, or fetch the results and artifacts of
a previous upload. **Async by default**: an upload returns immediately
with the minted post_id, and you fetch the result whenever it is ready.

```bash
id=$(showrunner analyze output/cats.mp4)  # upload; bare post_id on stdout
showrunner analyze --id "$id"             # one check: report, or exit 2
showrunner analyze --id "$id" --sync      # poll until ready (10 min cap)
showrunner analyze output/cats.mp4 --sync # upload + wait in one shot
showrunner analyze --id "$id" --transcript --caption
```

### Sources: PATH xor `--id`

Exactly one source is required — a **PATH** to upload, or **`--id`** for
an already-uploaded analysis. Zero or both is a usage error (exit 2).

**PATH** may be:

- a video file — supported extensions `.mp4 .mov .m4v .avi .mkv .webm`
  (unsupported types fail fast, before any bytes move, with an ffmpeg
  conversion hint; the same allowlist is enforced server-side);
- a showrunner **work_dir** — the rendered mp4 is resolved
  automatically: `showrunner.json`'s `output_path` first, then
  `refined.mp4` (the `showrunner refine` default), then the newest
  top-level `*.mp4`. An empty work_dir exits 2 with a hint to
  `showrunner resume`.

**`--id`** takes a post_id from a previous upload — recover lost ids
with `showrunner list --local`. The id is validated client-side before
any server request: a non-UUID value is a usage error (exit 2) with a
hint about the empty-shell-variable trap (`--id $ID` with `ID` unset
makes click consume the next flag as the id).

### Artifact flags

Artifact flags select what to show once a result is available — with
`--id`, or with a PATH under `--sync`. They **combine**; when none is
given, `--report` is the default. Using an artifact flag (or `--output`)
with a PATH but *without* `--sync` is a usage error (there is no result
yet to render).

| Flag | Output |
|------|--------|
| `--report` | Human-readable summary (the default) |
| `--full` | The complete raw analysis JSON |
| `--transcript` | The spoken script — plain text; time-coded segments under `--json` |
| `--overlays` | On-screen text, time-coded when timing is available |
| `--scenes` | Numbered scene breakdown |
| `--caption` | Generate a social caption server-side — **anew on every call**; results may differ between calls |
| `--video [FILE]` | Download the stored video to FILE (default name: the original upload's filename from the ledger, else `<id>.mp4`) |
| `--video-url` | Print the signed download URL instead of downloading |
| `--output FILE` | Additionally write the shown result to FILE |

Sample outputs (human mode):

```console
$ showrunner analyze --id "$id"          # --report is the default
Summary
  A tight 40-second explainer of why cats purr, anchored by a strong
  question hook.

Hook
  - [0.0] What if purring is not what you think it is?

Scenes (3)
  1. [0.0] Question hook over a slow zoom
  2. [8.0] The mechanism: laryngeal muscles at 25-150 Hz
  3. [30.0] Payoff: purring as self-repair

Themes
  cats, animal science, curiosity

$ showrunner analyze --id "$id" --transcript
What if purring is not what you think it is?
Cats purr with their laryngeal muscles, twitching 25 to 150 times a second.

$ showrunner analyze --id "$id" --overlays
[0.5-2.0] NOT WHAT YOU THINK
[8.0-11.5] 25–150 Hz

$ showrunner analyze --id "$id" --scenes
1. [0.0] Question hook over a slow zoom
2. [8.0] The mechanism: laryngeal muscles at 25-150 Hz

$ showrunner analyze --id "$id" --video-url
https://storage.googleapis.com/…?X-Goog-Signature=…
```

With a single artifact, stdout is the bare content (pipeable — the
`--video-url` output above is exactly one URL line). With several,
human output prints titled sections:

```
Report
------
Summary
  …

Transcript
----------
What if purring is not what you think it is?
…
```

`--video` writes the file and prints `Downloaded to <path>` on
**stderr** (the payload went to the file; stdout stays clean). The
download is two hops: the authenticated drafts endpoint mints a signed
URL, then the bytes stream from it (typically GCS).

### `--sync` and `--timeout`

- With a **PATH**, `--sync` uploads and then polls until the analysis is
  ready, printing the requested artifacts — one shot.
- With **`--id`**, the default is a *single* non-blocking check (ready →
  artifacts, not ready → exit 2); `--sync` polls instead.
- `--timeout SECONDS` (default `600`, i.e. 10 minutes) caps the `--sync`
  wait. On timeout the CLI exits 2 — the analysis may still finish
  server-side; check later with `showrunner analyze --id <id>`.

Polling backoff starts at ~5s and grows 1.5× per pending poll, capped at
~15s. Analyses typically take ~30–60s.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success — upload submitted (async), or the analysis is ready and the artifacts were rendered |
| `1` | Real error: not logged in, server rejection, network failure, or a **terminally failed analysis** (its `failure_reason` goes to stderr) |
| `2` | **Not ready yet** — not a failure. A single `--id` check found the analysis still processing, or a `--sync` wait timed out. Also used for usage errors (Click's convention), for a PATH/work_dir that resolves to no video, and for missing cloud deps on the upload path |
| `3` | Duplicate refused under `--if-duplicate fail` |

Exit 2 means "try again later", not "broken" — agents and scripts should
retry or switch to `--sync`, never treat it as terminal.

### Output contract (quiet stdout)

In human mode, **stdout carries only the payload**:

- an async upload prints exactly the bare post_id plus newline — so
  `id=$(showrunner analyze clip.mp4)` and redirection stay clean;
- a read (`--id`, or PATH `--sync`) prints exactly the artifact
  content — `showrunner analyze --id X --transcript > script.txt`
  yields a clean file.

Progress and status lines (the `Analyzing …` banner, upload %, retry
notices, polling status) are **off by default**; `--verbose` re-enables
them, on **stderr only**. Two notices are considered warnings that
matter and always go to stderr even without `--verbose`: the duplicate
warning and the resumed-upload notice. Errors always go to stderr with
their exit codes.

### `--json` shapes

Two different shapes, matching the two sources:

**Uploads (PATH) stream NDJSON events** on stdout — one JSON object per
line, each with an `"event"` discriminator, additive-only schema (same
contract as `create --json`):

| Event | Fields | Meaning |
|-------|--------|---------|
| `upload_progress` | `bytes_sent`, `total_bytes`, `pct` | Streaming upload progress, throttled to ~1% steps |
| `duplicate_warning` | `sha256`, `prior_post_id`, `prior_uploaded_at` | Same bytes uploaded within ~24h (mode `warn`) |
| `upload_resume` | `post_id` | An interrupted upload's id is being reused |
| `upload_retry` | `post_id`, `attempt`, `max_attempts`, `reason`, `retry_after_seconds` | Transient failure; retrying with the same id |
| `submitted` | `post_id`, `video_path`, `deduped` | Terminal for an async upload. With `--if-duplicate reuse`, carries the prior ledger record and `"deduped": true` |
| `analysis_pending` | `post_id`, `status`, `retry_after_seconds` | `--sync` only: still processing (expected, not an error) |
| `done` | `post_id`, `status: "ready"`, `video_path`, `analysis`, one key per requested artifact | Terminal for PATH `--sync` |
| `error` | `stage: "analyze"`, `message`; `status`/`failure_reason` when applicable | Terminal failure; exits nonzero |

```console
$ showrunner analyze clip.mp4 --sync --json
{"event": "upload_progress", "bytes_sent": 0, "total_bytes": 4194304, "pct": 0.0}
{"event": "upload_progress", "bytes_sent": 4194304, "total_bytes": 4194304, "pct": 100.0}
{"event": "analysis_pending", "status": "processing", "post_id": "8f2c…", "retry_after_seconds": 5.0}
{"event": "done", "post_id": "8f2c…", "status": "ready", "video_path": "clip.mp4", "report": "Summary\n  …", "analysis": {…}}
```

The terminal `done` always carries `analysis` (the raw payload) in
addition to the requested artifact keys, kept for the additive contract.

**Reads (`--id`) print ONE JSON object** (not NDJSON):

```json
{"post_id": "8f2c…", "status": "ready", "report": "…", "transcript": […]}
```

with one key per requested artifact. While processing:
`{"post_id": …, "status": "pending"}` with exit 2 (a `--sync` timeout
adds `"message"`). On terminal failure:
`{"post_id": …, "status": "failed", "failure_reason": "…"}` with exit 1.
Other errors: `{"post_id": …, "status": "error", "message": "…"}`.

Under `--json`, `--transcript` and `--overlays` return the time-coded
segment lists (not flattened text), and `--full` returns the raw
analysis object.

## Idempotent uploads

The upload id is **minted client-side** — a UUIDv4 created before any
bytes move — and sent as the `post_id` form field of
`POST /api/v1/drafts` (multipart, file field `video_file`). Because the
id is client-minted:

- **Transient failures retry with the same id.** Network errors and 5xx
  responses are retried automatically — 3 attempts with short linear
  backoff (1s, then 2s) — and can never create duplicate drafts. 4xx
  responses are never retried (they are rejections, not glitches).
- **Interrupted uploads resume.** The CLI records the attempt in the
  local ledger (an `upload_status: "pending"` line) *before* the bytes
  move. If the process dies mid-upload, the next
  `showrunner analyze <same file>` (within ~24h) finds the lone pending
  line and reuses its id instead of minting a fresh one — the server
  sees one draft either way.
- Retrying a failed `showrunner analyze` by just re-running it is always
  safe.

Server-side rejections come back as actionable messages: 400 unsupported
type (with the allowlist), 401/403 missing the `analysis:upload`
permission (re-login hint), 429 rate limited (with the `Retry-After`
seconds when the server provides them).

### `--if-duplicate {warn,reuse,fail}`

Uploads only (default `warn`). Before uploading, the CLI hashes the file
(sha256) and checks the local ledger for the same bytes uploaded within
~24h:

- **`warn`** — print a gentle warning with the prior post_id on stderr
  and upload anyway.
- **`reuse`** — print the **prior** post_id and skip the upload entirely
  (exit 0). Under `--json`, the single `submitted` event carries the
  prior ledger record plus `"deduped": true`. Recommended in agent
  loops.
- **`fail`** — refuse to upload: message on stderr naming the prior id,
  exit 3.

A lone *pending* (interrupted) record is not a duplicate — `reuse` will
not return an id the server never finished receiving; the upload
proceeds and resumes that id instead. Ledger problems never block an
upload.

## The local ledger

Because uploads are async, the minted post_ids must live somewhere you
can find again: `~/.showrunner/analyses.jsonl` (file mode `0600`,
directory `0700` — post_ids are not secrets, but the ledger reveals
filenames and activity). Append-only JSON lines:

```json
{"post_id": "8f2c…", "file": "/path/clip.mp4", "sha256": "…",
 "size_bytes": 4194304, "uploaded_at": "2026-07-20T12:34:56+00:00",
 "server": "https://api.gpt.social", "upload_status": "uploaded"}
```

- Each upload writes **two lines with the same post_id**: a
  `"pending"` line before the bytes move and an `"uploaded"` line after
  success. Duplicate lines per id are expected — **the latest line
  wins** on read. A lone `"pending"` line marks an interrupted upload
  whose id the next attempt of the same file reuses.
- Readers skip corrupt or foreign lines (a damaged ledger degrades to
  "some history missing", never a broken CLI), and ledger I/O failures
  never fail an upload that succeeded server-side.
- The recorded sha256 powers duplicate detection (`--if-duplicate`) and
  the default `--video` download filename.

## `showrunner list`

```bash
showrunner list                 # remote: your uploaded videos (drafts)
showrunner list --limit 50      # server-side limit (server caps at 100)
showrunner list --status done   # only rows with a known matching status
showrunner list --local         # offline: the local upload ledger
```

The default (remote) list calls `GET /api/v1/drafts` and prints one row
per upload: post_id, relative age, analysis status (`-` when unknown),
name. **Note**: the remote list currently accepts only password
(Firebase) sessions — under an OAuth session the server answers 401/403
and the CLI prints a hint to re-login with `--with-password` (OAuth
tokens work once
[scrollmark/platform#15546](https://github.com/scrollmark/platform/issues/15546)
lands). Pagination is server-side limit-only today (no cursors).

`--local` reads the ledger instead — newest first, one row per post_id
(latest line wins), works offline and logged out. `--status
{pending,done}` filters client-side and only matches rows whose status
is *known*; ledger rows carry no analysis status, so `--status` never
matches under `--local` (the CLI says so rather than showing an empty
lie).

Under `--json`: the remote list emits `{"videos": [...raw server
records...]}`; `--local` emits `{"analyses": [...ledger records...]}`.

## `create --analyze [--sync]`

The generate→analyze loop, built into `showrunner create`:

```bash
showrunner create "Why do cats purr?" --auto-approve --analyze          # async
showrunner create "Why do cats purr?" --auto-approve --analyze --sync   # + wait
```

**`--analyze`** (async, the default): after a successful render, the
output mp4 is uploaded exactly like `showrunner analyze <output>` — same
client-minted id, same ledger records, same duplicate handling — and the
post_id is printed after the render summary:

```
Video rendered: output/why-do-cats-purr.mp4
Analysis submitted: 8f2c1f9e-0000-4000-8000-000000000001
  Fetch it later with: showrunner analyze --id 8f2c1f9e-…
```

It never polls, and analysis problems can **never un-render the
video** — if the analyze step fails (not logged in, network, quota), the
mp4 is on disk and reported, the failure lands on stderr, and the exit
code is nonzero so scripts notice.

**`--analyze --sync`** additionally waits: render → upload (post_id
still printed as above) → poll until the analysis is ready → print the
human report (the `--report` rendering) after the render summary.
`--timeout SECONDS` (default 600) caps the wait; `--verbose` shows
upload/polling progress on stderr (quiet otherwise). `--sync` without
`--analyze` is a usage error.

Exit codes with `--analyze --sync` (the render is on disk in all of
these except a render failure):

| Situation | Exit |
|-----------|------|
| Render failure | unchanged — the render's own failure handling |
| Render OK, analysis ready, report printed | `0` |
| Render OK, analysis still pending at `--timeout` | `2` (fetch later with `analyze --id`) |
| Render OK, analysis terminally failed | `1` (`failure_reason` on stderr) |

Under `--json`, the `create` NDJSON stream keeps its documented events
and terminal `done` exactly as without `--analyze`; the analyze leg
appends after it:

- async `--analyze`: upload events, then a terminal
  `{"event": "submitted", "post_id": …, "deduped": false}` (or `error`);
- `--analyze --sync`: upload events, `submitted` (same as async), then
  `analysis_pending` events, then a terminal
  `{"event": "analysis", "post_id": …, "status": "ready", "report": …,
  "analysis": {…}}` — the analyze-side result shape as an event. It is
  named `analysis` (not `done`) because the render's `done` has already
  been emitted; a stream never carries two `done` events. On failure the
  stream ends with `{"event": "error", "stage": "analyze", …}` instead
  (with `"status"`/`"failure_reason"` for a failed analysis, and
  `"status": "pending"` for a timeout).

## Analysis payload shapes

Production analyses (the `analysis` object in `--full`, `--json`, and
the raw poll response) carry the transcript and on-screen text as
nested segment lists:

```json
{
  "transcription": {"segments": [{"text": "…", "start_time": 0.0, "end_time": 2.0}, …],
                     "text": "…"},
  "text_overlays": {"segments": [{"text": "…", "start_time": 0.5, "end_time": 1.5}, …]},
  "scenes": […], "hooks": […], "content_themes": […],
  "executive_summary": "…", "video_analysis": "…"
}
```

The CLI reads **`transcription.segments`** and
**`text_overlays.segments`** first, falling back to the flat
prompt-schema names (`transcript_segments`, `text_overlay_segments`, a
bare `transcript` string, or `summary.audio_transcript`) so older or
text-only analyses still render. Consumers of `--json` output should do
the same. Field shapes inside segments are server-defined; the CLI is
deliberately defensive (e.g. `start_time`/`start`/`timestamp` all
render).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Cloud commands require the optional cloud dependencies` | `httpx` not installed | `pip install "showrunner[cloud] @ git+https://github.com/scrollmark/showrunner.git"` |
| `Not logged in. Run showrunner login…` / 401 errors | No (or expired-beyond-refresh) session | `showrunner login --with-password`; in CI set `SHOWRUNNER_TOKEN` |
| `login` fails with "Unknown OAuth client" | The server's OAuth chain is not deployed yet | `showrunner login --with-password` (email + password) |
| `login --with-password` says incorrect password but the web app works | Account was created with Google sign-in — it has **no password** | Set a password via the web app's password reset, or wait for OAuth login to ship |
| Upload rejected with HTTP 400 | Unsupported file type | Convert: `ffmpeg -i input -c copy output.mp4` (supported: mp4, mov, m4v, avi, mkv, webm) |
| Upload rejected with HTTP 401/403 | Login missing the `analysis:upload` permission | Re-run `showrunner login`; if it persists, the account may not have upload access |
| Upload rejected with HTTP 422 | Request validation failed server-side — usually a CLI/server contract mismatch (e.g. an old CLI sending the wrong multipart field name) | Upgrade showrunner (`pip install -U "showrunner @ git+https://github.com/scrollmark/showrunner.git"`) and retry |
| Upload rejected with HTTP 429 | Rate limited | Wait (the message includes `Retry-After` when the server sends it) and retry |
| Upload dies mid-transfer (network drop, 5xx) | Transient failure | Already retried 3× with the same id; just re-run `showrunner analyze <path>` — it resumes the SAME id from the ledger, no duplicate drafts |
| `--id … is not a valid analysis id` (usage error, exit 2) | The id is not a UUID — the classic cause is an empty shell variable (`--id $ID` with `ID` unset), which makes click consume the *next flag* as the id | Check the variable is set; get real ids from `showrunner analyze <path>` or `showrunner list`. The CLI validates the id client-side, before any server request |
| `analyze --id` exits 2 | Analysis still processing — **not an error** | Retry in ~30s, or `--sync` to wait |
| Pending "forever" (`--sync` timed out, later checks still exit 2) | Analyzer backlog, or the analysis failed without a terminal record | Keep the post_id and re-check later; verify the upload exists (`showrunner list` / `--local`); if it never resolves, re-upload (`--if-duplicate warn` uploads the same bytes under a fresh id) |
| Analysis exits 1 with a `failure_reason` | The analyzer terminally failed on this video | If it looks transient, `showrunner analyze` again; otherwise re-encode (`ffmpeg -i in.mp4 -c:v libx264 out.mp4`) and retry |
| `showrunner list` fails with 401/403 under an OAuth login | Remote listing accepts Firebase sessions only for now | `showrunner login --with-password`, or `showrunner list --local` |
| Lost a post_id | — | `showrunner list --local` (offline ledger) or `showrunner list` (server) |
| `analyze` exits 3 | Same bytes uploaded within ~24h under `--if-duplicate fail` | Use the prior id from the message (`analyze --id <id>`), or re-run with `--if-duplicate warn`/`reuse` |
| `create --analyze` exits nonzero but the mp4 exists | The analyze step failed after a successful render | The render is fine — fix the analyze issue (usually login) and run `showrunner analyze <output>` |
| `SHOWRUNNER_TOKEN` rejected (401) | Env tokens are never refreshed | Issue a fresh token, or unset it and `showrunner login` |
