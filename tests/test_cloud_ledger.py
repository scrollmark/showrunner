"""Local upload ledger: append/read round-trip, dedup, corruption tolerance."""

import json
import os
import stat
import time

from showrunner.cloud import ledger

SERVER = "https://api.example.test"


def _record(path, post_id="p-1", sha256="abc", now=None, **kw):
    defaults = dict(
        post_id=post_id, file="clip.mp4", sha256=sha256, size_bytes=100,
        server=SERVER, path=path,
    )
    defaults.update(kw)
    if now is not None:
        defaults["now"] = now
    return ledger.record_upload(**defaults)


def test_round_trip(tmp_path):
    path = tmp_path / "analyses.jsonl"
    entry = _record(path, now=1750000000.0)
    assert ledger.read_entries(path) == [entry]
    assert entry["uploaded_at"].startswith("2025-06-15")  # ISO, UTC
    assert entry["post_id"] == "p-1"
    assert entry["file"] == "clip.mp4"
    assert entry["sha256"] == "abc"
    assert entry["size_bytes"] == 100
    assert entry["server"] == SERVER


def test_append_only_multiple_records(tmp_path):
    path = tmp_path / "analyses.jsonl"
    _record(path, post_id="p-1")
    _record(path, post_id="p-2")
    assert [e["post_id"] for e in ledger.read_entries(path)] == ["p-1", "p-2"]
    # one JSON document per line
    assert len(path.read_text().strip().splitlines()) == 2


def test_file_and_dir_modes(tmp_path):
    path = tmp_path / "nested" / "analyses.jsonl"
    _record(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700


def test_missing_ledger_reads_empty(tmp_path):
    assert ledger.read_entries(tmp_path / "nope.jsonl") == []


def test_corrupt_lines_are_skipped(tmp_path):
    path = tmp_path / "analyses.jsonl"
    _record(path, post_id="ok-1")
    with open(path, "a", encoding="utf-8") as f:
        f.write("{truncated\n")
        f.write("\n")
        f.write('"just a string"\n')
        f.write(json.dumps({"no_post_id": True}) + "\n")
    _record(path, post_id="ok-2")
    assert [e["post_id"] for e in ledger.read_entries(path)] == ["ok-1", "ok-2"]


def test_record_upload_never_raises_on_io_error(tmp_path):
    # Point the ledger at an unwritable location: the entry is still
    # returned and no exception escapes (uploads must not fail on this).
    path = tmp_path / "dir-as-file"
    path.mkdir()
    entry = ledger.record_upload(
        post_id="p-1", file="clip.mp4", sha256="abc", size_bytes=1,
        server=SERVER, path=path,  # opening a directory fails
    )
    assert entry["post_id"] == "p-1"


def test_sha256_file(tmp_path):
    import hashlib

    f = tmp_path / "clip.mp4"
    f.write_bytes(b"some video bytes")
    assert ledger.sha256_file(f) == hashlib.sha256(b"some video bytes").hexdigest()


def test_find_recent_duplicate_within_window(tmp_path):
    path = tmp_path / "analyses.jsonl"
    now = time.time()
    _record(path, post_id="older", sha256="dup", now=now - 3600)
    _record(path, post_id="newer", sha256="dup", now=now - 60)
    _record(path, post_id="other", sha256="different", now=now - 30)
    hit = ledger.find_recent_duplicate("dup", path=path, now=now)
    assert hit["post_id"] == "newer"  # newest match wins


def test_find_recent_duplicate_outside_window(tmp_path):
    path = tmp_path / "analyses.jsonl"
    now = time.time()
    _record(path, post_id="ancient", sha256="dup", now=now - 3 * 86400)
    assert ledger.find_recent_duplicate("dup", path=path, now=now) is None


def test_find_recent_duplicate_ignores_bad_timestamps(tmp_path):
    path = tmp_path / "analyses.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"post_id": "x", "sha256": "dup",
                            "uploaded_at": "not-a-date"}) + "\n")
    assert ledger.find_recent_duplicate("dup", path=path) is None


def test_parse_uploaded_at_naive_treated_as_utc():
    ts = ledger.parse_uploaded_at({"uploaded_at": "2026-01-01T00:00:00"})
    tz_ts = ledger.parse_uploaded_at({"uploaded_at": "2026-01-01T00:00:00+00:00"})
    assert ts == tz_ts
