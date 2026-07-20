"""Upload a local video for cloud analysis via the drafts endpoints.

Endpoint contract (server counterpart: the platform drafts bridge —
authoritative, do not change unilaterally):

1. ``POST /api/v1/drafts/upload`` — multipart form upload, field name
   ``file`` (filename + content type set). Supported extensions:
   .mp4 .mov .m4v .avi .mkv .webm. Success is ``201 {post_id, user_id}``.
   Failures: 400 (unsupported type), 401/403 (missing the
   ``analysis:upload`` scope), 429 (rate limited — retry later).
2. Poll ``GET /api/v1/drafts/{post_id}/analysis``. **404 means the
   analysis is still processing — keep polling** (backoff starts ~5s,
   caps ~15s; overall timeout configurable, default 10 min). Done:
   ``200 {post_id, user_id, analysis: {...}}``. A 200 body carrying
   ``status: "failed"`` is terminal, with ``failure_reason``.
3. After success, ``GET /api/v1/drafts/{post_id}/video`` returns a
   signed download URL for the stored video (not called here).

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
from pathlib import Path
from typing import Callable

from showrunner.cloud.client import CloudClient
from showrunner.cloud.credentials import CloudError

UPLOAD_PATH = "/api/v1/drafts/upload"
ANALYSIS_PATH = "/api/v1/drafts/{post_id}/analysis"

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


class AnalyzeError(CloudError):
    """The analyze flow failed with a non-retryable client/server error."""


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
    NotLoggedInError propagates from the client.
    """
    emit = on_event or (lambda d: None)
    video_path = Path(video_path)
    check_supported_type(video_path)
    size = video_path.stat().st_size
    if size <= 0:
        raise AnalyzeError(f"{video_path} is empty — nothing to upload.")
    content_type = guess_content_type(video_path)

    # 1. multipart upload (authenticated, straight to the API)
    emit({
        "event": "upload_progress",
        "bytes_sent": 0,
        "total_bytes": size,
        "pct": 0.0,
    })
    with open(video_path, "rb") as f:
        reader = _ProgressReader(f, size, emit)
        resp = client.post(
            UPLOAD_PATH,
            files={"file": (video_path.name, reader, content_type)},
        )
    if resp.status_code != 201:
        raise _upload_error(resp)
    post_id = _body(resp).get("post_id")
    if not post_id:
        raise AnalyzeError(
            "The server accepted the upload but returned no post_id — "
            "cannot poll for the analysis. Try `showrunner analyze` again."
        )

    # 2. poll — 404 from THIS endpoint means "still processing"
    delay = poll_initial_delay
    waited = 0.0
    poll_path = ANALYSIS_PATH.format(post_id=post_id)
    emit({
        "event": "analysis_pending",
        "status": "processing",
        "post_id": post_id,
        "retry_after_seconds": delay,
    })
    while waited < max_wait_seconds:
        sleep(delay)
        waited += delay
        resp = client.get(poll_path)
        if resp.status_code == 404:
            delay = min(delay * _POLL_BACKOFF_FACTOR, poll_max_delay)
            emit({
                "event": "analysis_pending",
                "status": "processing",
                "post_id": post_id,
                "retry_after_seconds": delay,
            })
            continue
        if resp.status_code >= 400:
            raise AnalyzeError(
                f"Polling the analysis failed (HTTP {resp.status_code})."
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
    raise AnalyzeError(
        f"Timed out after {int(waited)}s waiting for the analysis. The "
        f"draft ({post_id}) may still finish server-side — try "
        "`showrunner analyze` again later."
    )


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
