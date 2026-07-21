"""Local ledger of cloud analysis uploads (``~/.showrunner/analyses.jsonl``).

Because ``showrunner analyze`` is async by default (upload now, fetch the
analysis later with ``showrunner analyze --id <id>``), the post_ids minted
by uploads need to live somewhere the user can find again. Every
successful upload appends one JSON line::

    {"post_id": ..., "file": ..., "sha256": ..., "size_bytes": ...,
     "uploaded_at": "2026-07-20T12:34:56+00:00", "server": ...}

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
    path: Path | None = None,
    now: float | None = None,
) -> dict:
    """Append one upload record to the ledger; return the record.

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


def find_recent_duplicate(
    sha256: str,
    *,
    within_seconds: float = DUPLICATE_WINDOW_SECONDS,
    path: Path | None = None,
    now: float | None = None,
) -> dict | None:
    """Newest ledger record with the same sha256 inside the window, if any."""
    now = now if now is not None else time.time()
    newest: dict | None = None
    newest_ts = -1.0
    for entry in read_entries(path):
        if entry.get("sha256") != sha256:
            continue
        ts = parse_uploaded_at(entry)
        if ts is None or now - ts > within_seconds:
            continue
        if ts > newest_ts:
            newest, newest_ts = entry, ts
    return newest
