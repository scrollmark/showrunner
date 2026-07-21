"""Local ledger of cloud analysis uploads (``~/.showrunner/analyses.jsonl``).

Because ``showrunner analyze`` is async by default (upload now, fetch the
analysis later with ``showrunner analyze --id <id>``), the post_ids minted
by uploads need to live somewhere the user can find again. Every
successful upload appends one JSON line::

    {"post_id": ..., "file": ..., "sha256": ..., "size_bytes": ...,
     "uploaded_at": "2026-07-20T12:34:56+00:00", "server": ...,
     "upload_status": "uploaded"}

Since post_ids are minted client-side (UUIDv4, before any bytes move),
the CLI also records the attempt itself: an ``upload_status: "pending"``
line is appended before the upload starts and a ``"uploaded"`` line
after it succeeds. Duplicate lines for the same post_id are expected —
the LATEST line for a post_id wins on read — and an interrupted upload
leaves a lone "pending" line whose id the next attempt reuses
(:func:`find_pending_upload`), so retries never mint duplicate drafts.
Records without ``upload_status`` (written by older versions) count as
"uploaded".

Design notes:

- Append-only JSONL: concurrent uploads can append without coordination,
  and a partially-written line only corrupts itself.
- Created with mode 0600 (dir 0700), matching the credentials file —
  post_ids are not secrets, but the ledger reveals filenames/activity.
- Readers tolerate corrupt or foreign lines (skip, never raise) so a
  damaged ledger degrades to "some history missing", not a broken CLI.
- The sha256 recorded per upload powers a gentle duplicate warning when
  the same bytes are re-uploaded within ~24h.

Pure stdlib — importable without the ``[cloud]`` extra (``showrunner
list --local`` works offline and without httpx).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

#: Re-uploading identical bytes within this window triggers the
#: duplicate warning (the prior analysis is almost certainly still valid).
DUPLICATE_WINDOW_SECONDS = 24 * 3600


def default_ledger_path() -> Path:
    return Path.home() / ".showrunner" / "analyses.jsonl"


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Streaming sha256 of a file (videos can be large)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def record_upload(
    *,
    post_id: str,
    file: str | Path,
    sha256: str,
    size_bytes: int,
    server: str,
    upload_status: str = "uploaded",
    path: Path | None = None,
    now: float | None = None,
) -> dict:
    """Append one upload record to the ledger; return the record.

    `upload_status` is "uploaded" (default) for a completed upload or
    "pending" for an attempt recorded before the bytes move (so an
    interrupted upload can be retried with the same post_id). For
    "pending" records, ``uploaded_at`` is the attempt time.

    Never raises for ledger I/O problems — losing a history line must
    not fail an upload that already succeeded server-side.
    """
    entry = {
        "post_id": post_id,
        "file": str(file),
        "sha256": sha256,
        "size_bytes": size_bytes,
        "uploaded_at": datetime.fromtimestamp(
            now if now is not None else time.time(), tz=timezone.utc
        ).isoformat(timespec="seconds"),
        "server": server,
        "upload_status": upload_status,
    }
    ledger_path = path or default_ledger_path()
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            ledger_path.parent.chmod(stat.S_IRWXU)  # 0700
        except OSError:
            pass
        fd = os.open(
            ledger_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            stat.S_IRUSR | stat.S_IWUSR,  # 0600 from the start
        )
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        try:
            ledger_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # even if pre-existing
        except OSError:
            pass
    except OSError:
        pass
    return entry


def read_entries(path: Path | None = None) -> list[dict]:
    """All parseable ledger records, oldest first (file order).

    Corrupt/foreign lines are skipped; a missing ledger is an empty list.
    """
    ledger_path = path or default_ledger_path()
    try:
        text = ledger_path.read_text(encoding="utf-8")
    except OSError:
        return []
    entries: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict) and doc.get("post_id"):
            entries.append(doc)
    return entries


def upload_status(entry: dict) -> str:
    """The record's upload state; records predating the field count as
    "uploaded" (only completed uploads were recorded back then)."""
    status = entry.get("upload_status")
    return status if isinstance(status, str) and status else "uploaded"


def latest_entries(path: Path | None = None) -> list[dict]:
    """One record per post_id — the LATEST ledger line wins.

    Duplicate lines for the same post_id are expected (a "pending" line
    appended before the upload, an "uploaded" line after; interrupted
    runs may retry the same id). Order follows each id's first
    appearance (still oldest-first overall).
    """
    latest: dict[str, dict] = {}
    for entry in read_entries(path):
        latest[entry["post_id"]] = entry  # later line wins, position kept
    return list(latest.values())


def parse_uploaded_at(entry: dict) -> float | None:
    """The record's upload time as epoch seconds, or None when unparseable."""
    raw = entry.get("uploaded_at")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _find_newest(
    sha256: str,
    status: str,
    *,
    within_seconds: float,
    path: Path | None,
    now: float | None,
) -> dict | None:
    """Newest latest-wins record matching sha256 + upload status, if any."""
    now = now if now is not None else time.time()
    newest: dict | None = None
    newest_ts = -1.0
    for entry in latest_entries(path):
        if entry.get("sha256") != sha256 or upload_status(entry) != status:
            continue
        ts = parse_uploaded_at(entry)
        if ts is None or now - ts > within_seconds:
            continue
        if ts > newest_ts:
            newest, newest_ts = entry, ts
    return newest


def find_recent_duplicate(
    sha256: str,
    *,
    within_seconds: float = DUPLICATE_WINDOW_SECONDS,
    path: Path | None = None,
    now: float | None = None,
) -> dict | None:
    """Newest COMPLETED upload of the same sha256 inside the window, if any.

    Only "uploaded" records count — a lone "pending" record is an
    interrupted upload (see :func:`find_pending_upload`), not something
    the server has.
    """
    return _find_newest(
        sha256, "uploaded",
        within_seconds=within_seconds, path=path, now=now,
    )


def find_pending_upload(
    sha256: str,
    *,
    within_seconds: float = DUPLICATE_WINDOW_SECONDS,
    path: Path | None = None,
    now: float | None = None,
) -> dict | None:
    """Newest INTERRUPTED upload of the same sha256 inside the window.

    A record whose latest line is still "pending" means a previous
    attempt minted a post_id but never finished — retrying with that
    same id is idempotent server-side (client-minted UUIDs), so callers
    should reuse it instead of minting a fresh one.
    """
    return _find_newest(
        sha256, "pending",
        within_seconds=within_seconds, path=path, now=now,
    )
