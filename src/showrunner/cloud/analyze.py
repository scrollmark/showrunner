"""Upload a local video for cloud analysis.

Endpoint contract (server counterpart: the platform upload-endpoints
issue — authoritative, do not change unilaterally):

1. ``POST /api/v1/analysis/uploads`` body ``{filename, size_bytes,
   content_type}`` → ``{upload_id, upload_url, expires_in_seconds}``.
   Refusals are soft envelopes: ``{"reason": "quota_exceeded" |
   "file_too_large" | "unsupported_content_type", ...limits}``.
2. Resumable PUT of the video bytes to the signed GCS ``upload_url``
   (chunked ``Content-Range`` uploads, 308 for intermediate chunks;
   resume on transient failure by querying the committed offset).
3. ``POST /api/v1/analysis/uploads/{upload_id}/complete`` →
   ``{upload_id, status: "pending", retry_after_seconds}``.
4. Poll ``GET /api/v1/analysis/uploads/{upload_id}`` honoring
   ``retry_after_seconds`` — ``pending``/``analyzing`` is expected, not
   an error. Done: ``{status: "done", analysis: {...}}`` (same shape as
   the MCP ``get_video_analysis`` result). Failed: ``{status:
   "failed", reason, retryable}``.

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

UPLOADS_PATH = "/api/v1/analysis/uploads"

#: 8 MiB chunks — a GCS-recommended multiple of 256 KiB.
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024

#: MIME allowlist mirror (server-enforced; used for the declared type).
CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}

#: Give up polling after this long (analysis normally takes ~30-60s).
DEFAULT_MAX_WAIT_SECONDS = 1800
_MAX_POLLS = 600

_UPLOAD_MAX_RETRIES = 5


class AnalyzeError(CloudError):
    """The analyze flow failed with a non-retryable client/server error."""


class SoftRefusal(AnalyzeError):
    """The server declined the upload up-front (quota, size, MIME type)."""

    def __init__(self, reason: str, envelope: dict):
        self.reason = reason
        self.envelope = envelope
        super().__init__(refusal_message(reason, envelope))


class AnalysisFailed(AnalyzeError):
    """The server accepted the upload but analysis failed."""

    def __init__(self, reason: str, retryable: bool):
        self.reason = reason
        self.retryable = retryable
        msg = f"Analysis failed: {reason}."
        msg += (
            " This looks transient — try `showrunner analyze` again."
            if retryable
            else " Retrying with the same file is unlikely to help."
        )
        super().__init__(msg)


def refusal_message(reason: str, envelope: dict) -> str:
    """Actionable human message for a soft-refusal envelope."""
    if reason == "file_too_large":
        limit = envelope.get("max_size_bytes")
        hint = (
            f" The server accepts up to {limit / 1024 / 1024:.0f} MB;"
            " trim or re-encode the video (e.g. `ffmpeg -i in.mp4 -crf 28 out.mp4`)."
            if limit
            else " Trim or re-encode the video to reduce its size."
        )
        return "The video is too large to upload." + hint
    if reason == "quota_exceeded":
        retry = envelope.get("retry_after_seconds")
        hint = (
            f" Try again in ~{int(retry) // 60 or 1} min."
            if retry
            else " Try again later."
        )
        return "Upload quota exceeded." + hint
    if reason == "unsupported_content_type":
        allowed = envelope.get("allowed_content_types") or sorted(
            set(CONTENT_TYPES.values())
        )
        return (
            "Unsupported video type."
            f" Supported: {', '.join(allowed)} — convert with"
            " `ffmpeg -i input -c copy output.mp4` (or re-encode)."
        )
    return f"The server declined the upload: {reason}."


# ── input resolution ─────────────────────────────────────────────────


def guess_content_type(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "video/mp4")


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


# ── resumable upload ─────────────────────────────────────────────────


def _committed_offset(resp) -> int | None:
    """Next byte offset from a 308 response's ``Range: bytes=0-N`` header."""
    rng = resp.headers.get("Range") or resp.headers.get("range")
    if not rng or "-" not in rng:
        return None
    try:
        return int(rng.split("-")[-1]) + 1
    except ValueError:
        return None


def _query_offset(client, upload_url: str, size: int) -> int | None:
    """Ask the upload session how many bytes it has committed."""
    try:
        resp = client.put(
            upload_url,
            headers={"Content-Range": f"bytes */{size}", "Content-Length": "0"},
        )
    except Exception:
        return None
    if resp.status_code in (200, 201):
        return size
    if resp.status_code == 308:
        return _committed_offset(resp) or 0
    return None


def resumable_put(
    upload_url: str,
    video_path: Path,
    size: int,
    content_type: str,
    *,
    on_event: Callable[[dict], None] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    sleep: Callable[[float], None] = time.sleep,
    transport=None,
) -> None:
    """Chunked PUT to the signed resumable URL, resuming on transient failure.

    Emits ``upload_progress`` events after every committed chunk.
    """
    import httpx  # noqa: PLC0415 — optional dep, lazy import

    emit = on_event or (lambda d: None)

    def progress(sent: int) -> None:
        emit({
            "event": "upload_progress",
            "bytes_sent": sent,
            "total_bytes": size,
            "pct": round(100.0 * sent / size, 1) if size else 100.0,
        })

    if size <= 0:
        raise AnalyzeError(f"{video_path} is empty — nothing to upload.")

    progress(0)
    retries = 0
    offset = 0
    with httpx.Client(transport=transport, timeout=120.0) as up:
        with open(video_path, "rb") as f:
            while offset < size:
                f.seek(offset)
                chunk = f.read(chunk_size)
                end = offset + len(chunk) - 1
                headers = {
                    "Content-Range": f"bytes {offset}-{end}/{size}",
                    "Content-Type": content_type,
                }
                try:
                    resp = up.put(upload_url, content=chunk, headers=headers)
                except httpx.TransportError:
                    resp = None

                if resp is not None and resp.status_code in (200, 201):
                    progress(size)
                    return
                if resp is not None and resp.status_code == 308:
                    committed = _committed_offset(resp)
                    offset = committed if committed is not None else end + 1
                    retries = 0
                    progress(offset)
                    continue
                if resp is None or resp.status_code >= 500:
                    # Transient: back off, ask the session where it left off.
                    retries += 1
                    if retries > _UPLOAD_MAX_RETRIES:
                        raise AnalyzeError(
                            f"Upload failed after {_UPLOAD_MAX_RETRIES} retries "
                            "on a transient error. Check your connection and "
                            "re-run `showrunner analyze` — a new upload will "
                            "be created."
                        )
                    sleep(min(2 ** retries, 30))
                    queried = _query_offset(up, upload_url, size)
                    if queried is not None:
                        if queried >= size:
                            progress(size)
                            return
                        offset = queried
                    continue
                raise AnalyzeError(
                    f"Upload rejected by the storage server (HTTP "
                    f"{resp.status_code}). The signed URL may have expired "
                    "(they last ~15 min) — re-run `showrunner analyze`."
                )
    # Every byte 308-committed but no final 200 — treat as complete.
    progress(size)


# ── the flow ─────────────────────────────────────────────────────────


def _body(resp) -> dict:
    try:
        parsed = resp.json()
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def upload_and_analyze(
    client: CloudClient,
    video_path: Path,
    *,
    on_event: Callable[[dict], None] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    sleep: Callable[[float], None] = time.sleep,
    upload_transport=None,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
) -> dict:
    """Run the full create → upload → complete → poll flow.

    Returns the analysis payload (same shape as MCP `get_video_analysis`).
    Raises SoftRefusal / AnalysisFailed / AnalyzeError (all CloudError
    subclasses); NotLoggedInError propagates from the client.
    """
    emit = on_event or (lambda d: None)
    video_path = Path(video_path)
    size = video_path.stat().st_size
    content_type = guess_content_type(video_path)

    # 1. create the upload
    resp = client.post(UPLOADS_PATH, json={
        "filename": video_path.name,
        "size_bytes": size,
        "content_type": content_type,
    })
    body = _body(resp)
    if "reason" in body and "upload_id" not in body:
        raise SoftRefusal(body["reason"], body)
    if resp.status_code >= 400:
        raise AnalyzeError(f"Creating the upload failed (HTTP {resp.status_code}).")
    upload_id = body["upload_id"]
    upload_url = body["upload_url"]

    # 2. resumable PUT of the bytes (signed URL — unauthenticated client)
    resumable_put(
        upload_url, video_path, size, content_type,
        on_event=emit, chunk_size=chunk_size, sleep=sleep,
        transport=upload_transport,
    )

    # 3. complete
    resp = client.post(f"{UPLOADS_PATH}/{upload_id}/complete")
    body = _body(resp)
    if "reason" in body and resp.status_code >= 400:
        raise SoftRefusal(body["reason"], body)
    if resp.status_code >= 400:
        raise AnalyzeError(f"Completing the upload failed (HTTP {resp.status_code}).")

    status = body.get("status", "pending")
    retry_after = float(body.get("retry_after_seconds", 5) or 5)
    emit({
        "event": "analysis_pending",
        "status": status,
        "retry_after_seconds": retry_after,
    })

    # 4. poll, honoring retry_after_seconds ("pending" is expected)
    waited = 0.0
    for _ in range(_MAX_POLLS):
        sleep(retry_after)
        waited += retry_after
        resp = client.get(f"{UPLOADS_PATH}/{upload_id}")
        body = _body(resp)
        status = body.get("status")
        if status == "done":
            return body.get("analysis") or {}
        if status == "failed":
            raise AnalysisFailed(
                body.get("reason", "unknown"), bool(body.get("retryable"))
            )
        if resp.status_code >= 400:
            raise AnalyzeError(
                f"Polling the analysis failed (HTTP {resp.status_code})."
            )
        retry_after = float(body.get("retry_after_seconds", retry_after) or 5)
        emit({
            "event": "analysis_pending",
            "status": status or "pending",
            "retry_after_seconds": retry_after,
        })
        if waited >= max_wait_seconds:
            break
    raise AnalyzeError(
        f"Timed out after {int(waited)}s waiting for the analysis. The "
        f"upload ({upload_id}) may still finish server-side — try "
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
