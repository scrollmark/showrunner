"""Upload a local video for cloud analysis via the drafts endpoints.

Endpoint contract (server counterpart: the platform drafts bridge —
authoritative, do not change unilaterally):

1. ``POST /api/v1/drafts`` — multipart form upload with a
   CLIENT-MINTED idempotency id: form fields ``post_id`` (a UUIDv4
   string minted before any bytes move) and ``file`` (filename +
   content type set). Supported extensions: .mp4 .mov .m4v .avi .mkv
   .webm. Success is ``201 {post_id, user_id}``. Failures: 400
   (unsupported type / invalid post_id), 401/403 (missing the
   ``analysis:upload`` scope), 429 (rate limited — retry later).
   Because the id is client-minted, transient failures (network
   errors, 5xx) are retried with the SAME post_id — bounded at
   :data:`UPLOAD_MAX_ATTEMPTS` attempts with short backoff — and can
   never create duplicate drafts. 4xx responses are never retried.
   (The server also has an auto-id ``POST /api/v1/drafts/upload``
   alias; this module deliberately does not use it.)
2. Poll ``GET /api/v1/drafts/{post_id}/analysis``. **404 means the
   analysis is still processing — keep polling** (backoff starts ~5s,
   caps ~15s; overall timeout configurable, default 10 min). Done:
   ``200 {post_id, user_id, analysis: {...}}``. A 200 body carrying
   ``status: "failed"`` is terminal, with ``failure_reason``.
3. After success, ``GET /api/v1/drafts/{post_id}/video`` returns a
   signed download URL for the stored video (see :func:`get_video_url`).

The 404-as-pending convention applies ONLY to the polling endpoint —
because the ``post_id`` was just minted by a successful 201 upload, a
404 there can only mean "not analyzed yet". 404s anywhere else in this
module remain real errors.

Progress and polling are surfaced through an ``on_event(dict)``
callback with NDJSON-shaped events (``upload_progress``,
``analysis_pending``) so the CLI can stream them under ``--json``.

httpx is imported lazily (optional `[cloud]` dep group).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Callable

from showrunner.cloud.client import CloudClient
from showrunner.cloud.credentials import CloudError

ANALYSIS_PATH = "/api/v1/drafts/{post_id}/analysis"
VIDEO_PATH = "/api/v1/drafts/{post_id}/video"
CAPTION_PATH = "/api/v1/drafts/{post_id}/generate-caption"
DRAFTS_PATH = "/api/v1/drafts"

#: Extension → MIME allowlist mirror (server-enforced by filename).
CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}
SUPPORTED_EXTENSIONS = sorted(CONTENT_TYPES)

#: Give up polling after this long (analysis normally takes ~30-60s).
DEFAULT_MAX_WAIT_SECONDS = 600.0

#: Poll backoff: start ~5s, grow 1.5x per pending poll, cap ~15s.
POLL_INITIAL_DELAY = 5.0
POLL_MAX_DELAY = 15.0
_POLL_BACKOFF_FACTOR = 1.5

#: Upload retry policy for TRANSIENT failures (network errors, 5xx):
#: retry with the same client-minted post_id, short linear backoff
#: (1s, then 2s). 4xx responses are never retried.
UPLOAD_MAX_ATTEMPTS = 3
UPLOAD_RETRY_DELAY = 1.0


class AnalyzeError(CloudError):
    """The analyze flow failed with a non-retryable client/server error."""


class AnalysisTimeout(AnalyzeError):
    """Polling gave up while the analysis was still pending (not a
    terminal failure — the analysis may still finish server-side; the
    CLI maps this to exit code 2 for `analyze --id ... --sync`)."""


class ListUnauthorized(AnalyzeError):
    """The drafts listing was refused (401/403). Under an OAuth session
    this is expected for now — the platform's drafts listing accepts
    only Firebase sessions until scrollmark/platform#15546 lands; the
    CLI adds a `--with-password` hint for that case."""


class AnalysisFailed(AnalyzeError):
    """The server stored the upload but analysis ended in status=failed."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            f"Analysis failed: {reason}. If this looks transient, try "
            "`showrunner analyze` again; otherwise re-encode the video "
            "(e.g. `ffmpeg -i in.mp4 -c:v libx264 out.mp4`) and retry."
        )


# ── input resolution ─────────────────────────────────────────────────


def guess_content_type(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "video/mp4")


def check_supported_type(path: Path) -> None:
    """Fail fast (before uploading bytes) on a type the server will 400."""
    if path.suffix.lower() not in CONTENT_TYPES:
        raise AnalyzeError(
            f"Unsupported video type '{path.suffix or path.name}'. Supported: "
            f"{', '.join(SUPPORTED_EXTENSIONS)} — convert with "
            "`ffmpeg -i input -c copy output.mp4` (or re-encode)."
        )


def resolve_video_path(path: Path) -> Path:
    """Resolve a video file OR a showrunner work_dir to the mp4 to upload.

    For a work_dir: `showrunner.json`'s ``output_path`` (as written by a
    completed `showrunner create` run), then `refined.mp4` (written by
    `showrunner refine`'s default), then the newest top-level ``*.mp4``.
    """
    path = Path(path)
    if path.is_file():
        return path
    if not path.is_dir():
        raise AnalyzeError(f"No such file or directory: {path}")

    manifest = path / "showrunner.json"
    if manifest.exists():
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
        out = meta.get("output_path")
        if out:
            candidate = Path(out)
            if not candidate.is_absolute():
                candidate = path / candidate
            if candidate.exists():
                return candidate

    refined = path / "refined.mp4"
    if refined.exists():
        return refined

    mp4s = sorted(path.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if mp4s:
        return mp4s[0]

    raise AnalyzeError(
        f"Could not find a rendered video in {path}: no showrunner.json "
        "output_path, refined.mp4, or top-level *.mp4. Pass the mp4 file "
        "directly, or re-render with `showrunner resume <work_dir>`."
    )


# ── upload progress ──────────────────────────────────────────────────


class _ProgressReader:
    """Seekable file-like wrapper emitting ``upload_progress`` events.

    httpx streams multipart file fields by calling ``read()``; wrapping
    the file gives per-chunk progress without buffering the video in
    memory. ``seek``/``tell`` keep the field rewindable so the client's
    one refresh-and-retry on 401 re-sends the full body.

    Events are throttled to ~1% steps (plus 0% and 100%) so --json
    streams stay reasonable for large files.
    """

    def __init__(self, fileobj, size: int, emit: Callable[[dict], None]):
        self._f = fileobj
        self._size = size
        self._emit = emit
        self._sent = 0
        self._last_pct = -1.0

    def _progress(self) -> None:
        pct = round(100.0 * self._sent / self._size, 1) if self._size else 100.0
        if pct >= 100.0 or pct - self._last_pct >= 1.0:
            self._last_pct = pct
            self._emit({
                "event": "upload_progress",
                "bytes_sent": self._sent,
                "total_bytes": self._size,
                "pct": pct,
            })

    def read(self, n: int = -1) -> bytes:
        chunk = self._f.read(n)
        self._sent += len(chunk)
        if chunk:
            self._progress()
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        pos = self._f.seek(offset, whence)
        self._sent = pos
        self._last_pct = -1.0
        return pos

    def tell(self) -> int:
        return self._f.tell()


# ── error rendering ──────────────────────────────────────────────────


def _body(resp) -> dict:
    try:
        parsed = resp.json()
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _detail(resp) -> str | None:
    body = _body(resp)
    for key in ("detail", "message", "error"):
        val = body.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _upload_error(resp) -> AnalyzeError:
    """Actionable error for a non-201 upload response."""
    status = resp.status_code
    detail = _detail(resp)
    if status == 400:
        return AnalyzeError(
            "The server rejected the upload"
            + (f": {detail}" if detail else " (unsupported file type)")
            + f". Supported types: {', '.join(SUPPORTED_EXTENSIONS)}."
        )
    if status in (401, 403):
        return AnalyzeError(
            "The server refused the upload (HTTP "
            f"{status}): your login is missing the analysis:upload "
            "permission. Re-run `showrunner login`; if it persists, your "
            "account may not have upload access yet."
        )
    if status == 429:
        retry_after = resp.headers.get("Retry-After")
        hint = (
            f" Try again in ~{retry_after}s."
            if retry_after
            else " Wait a minute and try again."
        )
        return AnalyzeError("Upload rate limit reached." + hint)
    return AnalyzeError(
        f"Uploading the video failed (HTTP {status})"
        + (f": {detail}" if detail else ".")
    )


# ── the flow ─────────────────────────────────────────────────────────


def mint_post_id() -> str:
    """Mint the client-side idempotency id for one upload (UUIDv4)."""
    return str(uuid.uuid4())


def is_valid_post_id(value) -> bool:
    """True when `value` is a UUID string the server will accept."""
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def upload(
    client: CloudClient,
    video_path: Path,
    *,
    post_id: str | None = None,
    on_event: Callable[[dict], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = UPLOAD_MAX_ATTEMPTS,
) -> str:
    """Multipart-upload a video to the drafts endpoint; return the post_id.

    The post_id is CLIENT-MINTED (UUIDv4) before any bytes move — pass
    one to resume an interrupted upload with the same id, or leave it
    None to mint fresh. Transient failures (network errors, 5xx) are
    retried with the SAME id — bounded by `max_attempts`, short backoff
    via `sleep` — so retries can never create duplicate drafts; a
    ``{"event": "upload_retry"}`` event is emitted before each retry.
    4xx responses raise immediately (never retried).

    Raises AnalyzeError on rejection or when the attempts are
    exhausted; NotLoggedInError propagates from the client.
    """
    import httpx  # noqa: PLC0415 — optional dep, lazy import

    emit = on_event or (lambda d: None)
    video_path = Path(video_path)
    check_supported_type(video_path)
    size = video_path.stat().st_size
    if size <= 0:
        raise AnalyzeError(f"{video_path} is empty — nothing to upload.")
    if post_id is None:
        post_id = mint_post_id()
    elif not is_valid_post_id(post_id):
        raise AnalyzeError(
            f"post_id must be a UUID string, got {post_id!r} — omit it to "
            "mint a fresh one."
        )
    content_type = guess_content_type(video_path)

    last_error = ""
    for attempt in range(1, max_attempts + 1):
        emit({
            "event": "upload_progress",
            "bytes_sent": 0,
            "total_bytes": size,
            "pct": 0.0,
        })
        resp = None
        try:
            with open(video_path, "rb") as f:
                reader = _ProgressReader(f, size, emit)
                resp = client.post(
                    DRAFTS_PATH,
                    data={"post_id": post_id},
                    # The non-alias create-draft endpoint names its upload field
                    # `video_file` (only the /drafts/upload alias renames it to `file`).
                    files={"video_file": (video_path.name, reader, content_type)},
                )
        except httpx.TransportError as e:
            last_error = f"{type(e).__name__}: {e}".rstrip(": ")
        if resp is not None:
            if resp.status_code == 201:
                # The id is client-minted; a server-echoed post_id (the
                # normal case) is authoritative if it ever differs.
                return _body(resp).get("post_id") or post_id
            if resp.status_code < 500:
                raise _upload_error(resp)  # 4xx: not transient, no retry
            last_error = f"HTTP {resp.status_code}"
        if attempt < max_attempts:
            delay = UPLOAD_RETRY_DELAY * attempt
            emit({
                "event": "upload_retry",
                "post_id": post_id,
                "attempt": attempt + 1,
                "max_attempts": max_attempts,
                "reason": last_error,
                "retry_after_seconds": delay,
            })
            sleep(delay)
    raise AnalyzeError(
        f"Uploading the video failed after {max_attempts} attempts "
        f"({last_error}). Every attempt reused the same upload id "
        f"({post_id}), so no duplicate drafts were created — running "
        "`showrunner analyze` again is safe."
    )


def check_analysis(client: CloudClient, post_id: str) -> dict | None:
    """One non-blocking check of the analysis for `post_id`.

    Returns the analysis payload when ready, None while still
    processing (the endpoint 404s until the analysis exists). Raises
    AnalysisFailed for a terminal status=failed body, AnalyzeError for
    other HTTP errors; NotLoggedInError propagates from the client.
    """
    resp = client.get(ANALYSIS_PATH.format(post_id=post_id))
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        raise AnalyzeError(
            f"Fetching the analysis failed (HTTP {resp.status_code})."
        )
    body = _body(resp)
    analysis = body.get("analysis") or {}
    status = body.get("status") or (
        analysis.get("status") if isinstance(analysis, dict) else None
    )
    if status == "failed":
        raise AnalysisFailed(
            body.get("failure_reason")
            or (analysis.get("failure_reason") if isinstance(analysis, dict)
                else None)
            or "unknown"
        )
    return analysis


def poll_analysis(
    client: CloudClient,
    post_id: str,
    *,
    on_event: Callable[[dict], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    poll_initial_delay: float = POLL_INITIAL_DELAY,
    poll_max_delay: float = POLL_MAX_DELAY,
) -> dict:
    """Poll the analysis for `post_id` until ready (404 = still processing).

    Raises AnalysisTimeout when max_wait_seconds elapses while still
    pending; AnalysisFailed / AnalyzeError as in :func:`check_analysis`.
    """
    emit = on_event or (lambda d: None)
    delay = poll_initial_delay
    waited = 0.0
    emit({
        "event": "analysis_pending",
        "status": "processing",
        "post_id": post_id,
        "retry_after_seconds": delay,
    })
    while waited < max_wait_seconds:
        sleep(delay)
        waited += delay
        analysis = check_analysis(client, post_id)
        if analysis is None:
            delay = min(delay * _POLL_BACKOFF_FACTOR, poll_max_delay)
            emit({
                "event": "analysis_pending",
                "status": "processing",
                "post_id": post_id,
                "retry_after_seconds": delay,
            })
            continue
        return analysis
    raise AnalysisTimeout(
        f"Timed out after {int(waited)}s waiting for the analysis. The "
        f"draft ({post_id}) may still finish server-side — check later "
        f"with `showrunner analyze --id {post_id}`."
    )


def upload_and_analyze(
    client: CloudClient,
    video_path: Path,
    *,
    on_event: Callable[[dict], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    poll_initial_delay: float = POLL_INITIAL_DELAY,
    poll_max_delay: float = POLL_MAX_DELAY,
) -> dict:
    """Run the full upload → poll flow against the drafts endpoints.

    Returns the analysis payload (same shape as MCP `get_video_analysis`).
    Raises AnalysisFailed / AnalyzeError (both CloudError subclasses);
    NotLoggedInError propagates from the client. `sleep` paces both the
    upload's transient-failure retries and the analysis polling.
    """
    post_id = upload(client, video_path, on_event=on_event, sleep=sleep)
    return poll_analysis(
        client,
        post_id,
        on_event=on_event,
        sleep=sleep,
        max_wait_seconds=max_wait_seconds,
        poll_initial_delay=poll_initial_delay,
        poll_max_delay=poll_max_delay,
    )


def get_video_url(client: CloudClient, post_id: str) -> str:
    """Fetch the signed download URL for the stored video of `post_id`.

    ``GET /api/v1/drafts/{post_id}/video`` — defensive about the exact
    response shape (JSON url field, redirect Location, or a bare URL
    body).
    """
    resp = client.get(VIDEO_PATH.format(post_id=post_id))
    if resp.status_code == 404:
        raise AnalyzeError(
            f"No stored video found for {post_id} (HTTP 404) — check the "
            "id (`showrunner list --local`), or the upload may not have "
            "completed."
        )
    if resp.status_code in (301, 302, 303, 307, 308):
        location = resp.headers.get("Location")
        if location:
            return location
    if resp.status_code >= 400:
        raise AnalyzeError(
            f"Fetching the video URL failed (HTTP {resp.status_code})."
        )
    body = _body(resp)
    for key in ("url", "download_url", "signed_url", "video_url"):
        val = body.get(key)
        if isinstance(val, str) and val:
            return val
    text = (resp.text or "").strip().strip('"')
    if text.startswith(("http://", "https://")):
        return text
    raise AnalyzeError(
        "The server response did not include a video URL — the endpoint "
        "may have changed; try again with a newer showrunner."
    )


def download_video(
    client: CloudClient,
    post_id: str,
    dest: Path,
    *,
    download_transport=None,
) -> Path:
    """Download the stored video for `post_id` to `dest`.

    Two hops: the authenticated drafts endpoint mints a signed URL
    (:func:`get_video_url`), then the bytes are streamed from that URL
    (typically GCS — unauthenticated, redirects followed).
    `download_transport` is injectable for tests.
    """
    import httpx  # noqa: PLC0415 — optional dep, lazy import

    url = get_video_url(client, post_id)
    dest = Path(dest)
    with httpx.Client(
        transport=download_transport, follow_redirects=True, timeout=120.0
    ) as dl:
        with dl.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise AnalyzeError(
                    f"Downloading the video failed (HTTP {resp.status_code}) "
                    "— the signed URL may have expired; try again."
                )
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
    return dest


def list_videos(client: CloudClient, *, limit: int = 20) -> list[dict]:
    """Fetch the caller's uploaded drafts: ``GET /api/v1/drafts``.

    Pagination is server-side limit-only today (the server caps at
    100) — no client-side cursors (tracked in scrollmark/platform#15546).
    Raises :class:`ListUnauthorized` on 401/403 (expected under an OAuth
    session until the platform accepts OAuth tokens there). Defensive
    about the exact envelope: a bare list, or a dict wrapping one.
    """
    resp = client.get(DRAFTS_PATH, params={"limit": limit})
    if resp.status_code in (401, 403):
        raise ListUnauthorized(
            f"The server refused the video listing (HTTP {resp.status_code})."
        )
    if resp.status_code >= 400:
        raise AnalyzeError(
            f"Listing your videos failed (HTTP {resp.status_code})."
        )
    try:
        body = resp.json()
    except Exception:
        body = None
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]
    if isinstance(body, dict):
        for key in ("videos", "drafts", "items", "results", "posts"):
            rows = body.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    raise AnalyzeError(
        "Unexpected response shape from the video listing — the endpoint "
        "may have changed; try again with a newer showrunner."
    )


def generate_caption(client: CloudClient, post_id: str) -> str:
    """Generate a social caption for `post_id` server-side.

    ``POST /api/v1/drafts/{post_id}/generate-caption`` — generates anew
    on every call (results may differ between calls). Defensive about
    the exact response shape.
    """
    resp = client.post(CAPTION_PATH.format(post_id=post_id))
    if resp.status_code == 404:
        raise AnalyzeError(
            f"Caption generation unavailable for {post_id} (HTTP 404) — "
            "the id may be wrong, or the analysis may not be ready yet."
        )
    if resp.status_code >= 400:
        raise AnalyzeError(
            f"Generating the caption failed (HTTP {resp.status_code})."
        )
    body = _body(resp)
    for key in ("caption", "generated_caption", "text", "result"):
        val = body.get(key)
        if isinstance(val, str) and val:
            return val
    text = (resp.text or "").strip().strip('"')
    if text:
        return text
    raise AnalyzeError("The server returned no caption text.")


# ── human rendering ──────────────────────────────────────────────────


def _fmt_item(item) -> str:
    """Render one hook/scene entry (shape is server-defined; be defensive)."""
    if isinstance(item, dict):
        text = (
            item.get("text") or item.get("description") or item.get("summary")
            or item.get("hook") or item.get("title")
        )
        start = item.get("start_time", item.get("start", item.get("timestamp")))
        prefix = f"[{start}] " if start not in (None, "") else ""
        if text:
            return f"{prefix}{text}"
        return prefix + ", ".join(f"{k}: {v}" for k, v in item.items())
    return str(item)


def render_analysis(analysis: dict) -> str:
    """Human-readable summary: hook, scenes, themes, technical analysis."""
    lines: list[str] = []

    summary = analysis.get("executive_summary")
    if summary:
        lines += ["Summary", f"  {summary}", ""]

    hooks = analysis.get("hooks") or []
    if hooks:
        lines.append("Hook")
        lines += [f"  - {_fmt_item(h)}" for h in hooks]
        lines.append("")

    scenes = analysis.get("scenes") or []
    if scenes:
        lines.append(f"Scenes ({len(scenes)})")
        lines += [f"  {i}. {_fmt_item(s)}" for i, s in enumerate(scenes, 1)]
        lines.append("")

    themes = analysis.get("content_themes") or []
    if themes:
        lines += ["Themes", "  " + ", ".join(str(t) for t in themes), ""]

    technical = analysis.get("video_analysis")
    if technical:
        lines += ["Technical analysis", f"  {technical}", ""]

    suggested = analysis.get("suggested_hooks") or []
    if suggested:
        lines.append("Suggested hooks")
        lines += [f"  - {s}" for s in suggested]
        lines.append("")

    if not lines:
        lines = ["(analysis returned no renderable fields — see --json / --output "
                 "for the raw payload)"]
    return "\n".join(lines).rstrip()


def _segment_text(seg) -> str:
    if isinstance(seg, dict):
        return str(
            seg.get("text") or seg.get("overlay_text") or seg.get("content") or ""
        )
    return str(seg)


def _segment_span(seg) -> str:
    if not isinstance(seg, dict):
        return ""
    start = seg.get("start_time", seg.get("start"))
    end = seg.get("end_time", seg.get("end"))
    if start in (None, "") and end in (None, ""):
        return ""
    if end in (None, ""):
        return f"[{start}] "
    return f"[{start}-{end}] "


def transcript_segments(analysis: dict) -> list:
    """Time-coded speech segments from the analysis.

    Production analyses carry them at transcription.segments; fall back to the
    prompt-schema names (transcript_segments / transcript) and the summary's
    plain audio_transcript so a text-only analysis still yields one segment.
    """
    transcription = analysis.get("transcription") or {}
    segments = transcription.get("segments") or analysis.get("transcript_segments") or []
    if segments:
        return segments
    text = (
        transcription.get("text")
        or analysis.get("transcript")
        or (analysis.get("summary") or {}).get("audio_transcript")
    )
    return [{"text": text}] if text else []


def overlay_segments(analysis: dict) -> list:
    """On-screen text segments; production nests them under text_overlays.segments."""
    overlays = analysis.get("text_overlays")
    if isinstance(overlays, dict):
        segments = overlays.get("segments") or []
    elif isinstance(overlays, list):
        segments = overlays
    else:
        segments = []
    return segments or analysis.get("text_overlay_segments") or []


def render_transcript(analysis: dict) -> str:
    """The spoken script as plain text (one line per segment)."""
    lines = [t for t in (_segment_text(s).strip() for s in transcript_segments(analysis)) if t]
    if not lines:
        return "(no transcript in the analysis)"
    return "\n".join(lines)


def render_overlays(analysis: dict) -> str:
    """On-screen text overlays, time-coded when timing is available."""
    segments = overlay_segments(analysis)
    lines = [
        line for line in
        (f"{_segment_span(s)}{_segment_text(s)}".strip() for s in segments)
        if line
    ]
    if not lines:
        return "(no text overlays in the analysis)"
    return "\n".join(lines)


def render_scenes(analysis: dict) -> str:
    """Numbered scene breakdown."""
    scenes = analysis.get("scenes") or []
    if not scenes:
        return "(no scene breakdown in the analysis)"
    return "\n".join(f"{i}. {_fmt_item(s)}" for i, s in enumerate(scenes, 1))
