"""CLI: flag-driven `showrunner analyze` (PATH xor --id) + `create --analyze`."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

httpx = pytest.importorskip("httpx", reason="cloud extra (httpx) not installed")

from showrunner.cli.main import cli  # noqa: E402
from showrunner.cloud import ledger  # noqa: E402
from showrunner.cloud.credentials import CredentialStore, NotLoggedInError  # noqa: E402

POST_ID = "8f2c1f9e-0000-4000-8000-000000000001"
SERVER = "https://api.gpt.social"  # the built-in default

ANALYSIS = {
    "executive_summary": "A tight explainer.",
    "hooks": [{"text": "What if cats could talk?"}],
    "scenes": [{"description": "Intro"}],
    "content_themes": ["cats"],
    "transcript_segments": [
        {"text": "Cats are great.", "start_time": 0.0, "end_time": 2.0},
        {"text": "Here is why.", "start_time": 2.0, "end_time": 4.0},
    ],
    "text_overlay_segments": [
        {"text": "CATS!", "start_time": 0.5, "end_time": 1.5},
    ],
}


@pytest.fixture(autouse=True)
def isolated_creds(tmp_path, monkeypatch):
    """Never touch the real keyring/home credentials from CLI tests."""
    monkeypatch.setattr(
        "showrunner.cloud.credentials.default_credentials_path",
        lambda: tmp_path / "credentials.json",
    )
    monkeypatch.setattr(CredentialStore, "_keyring", lambda self: None)
    monkeypatch.delenv("SHOWRUNNER_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def ledger_path(tmp_path, monkeypatch):
    """Route the upload ledger to a tmp file (never ~/.showrunner)."""
    path = tmp_path / "analyses.jsonl"
    monkeypatch.setattr(
        "showrunner.cloud.ledger.default_ledger_path", lambda: path
    )
    return path


@pytest.fixture(autouse=True)
def deterministic_minted_id(monkeypatch):
    """The CLI mints upload UUIDs client-side — pin them to POST_ID."""
    import uuid

    monkeypatch.setattr(
        "showrunner.cli.main.uuid4", lambda: uuid.UUID(POST_ID)
    )


def _upload_patch(default_post_id=POST_ID, side_effect=None, events=()):
    """Patch analyze.upload; optionally replay events into on_event.

    Mirrors the real contract: the returned id is the client-minted
    post_id the CLI passes in (`default_post_id` when absent).
    """

    def fake(client, video_path, *, post_id=None, on_event=None, **kwargs):
        if side_effect is not None:
            raise side_effect
        for ev in events:
            if on_event:
                on_event(ev)
        return post_id or default_post_id

    mock = MagicMock(side_effect=fake)
    return patch("showrunner.cloud.analyze.upload", mock), mock


def _poll_patch(analysis=None, side_effect=None):
    def fake(client, post_id, *, on_event=None, **kwargs):
        if side_effect is not None:
            raise side_effect
        return analysis if analysis is not None else ANALYSIS

    mock = MagicMock(side_effect=fake)
    return patch("showrunner.cloud.analyze.poll_analysis", mock), mock


def _check_patch(analysis="__default__", side_effect=None):
    result = ANALYSIS if analysis == "__default__" else analysis
    mock = MagicMock(return_value=result, side_effect=side_effect)
    return patch("showrunner.cloud.analyze.check_analysis", mock), mock


def _parse_ndjson(stdout: str) -> list[dict]:
    docs = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    assert all("event" in d for d in docs)
    return docs


def _video(tmp_path, name="clip.mp4", data=b"x"):
    video = tmp_path / name
    video.write_bytes(data)
    return video


# ── source-axis validation: exactly one of PATH xor --id ────────────


def test_analyze_no_source_is_usage_error():
    result = CliRunner().invoke(cli, ["analyze"])
    assert result.exit_code == 2
    assert "exactly one source" in result.output


def test_analyze_path_plus_id_is_usage_error(tmp_path):
    video = _video(tmp_path)
    result = CliRunner().invoke(cli, ["analyze", str(video), "--id", POST_ID])
    assert result.exit_code == 2
    assert "exactly one source" in result.output


# ── PATH source: async upload (the default) ──────────────────────────


def test_analyze_async_prints_bare_post_id(tmp_path):
    video = _video(tmp_path)
    upload_patch, mock = _upload_patch()
    poll_patch, poll_mock = _poll_patch()
    with upload_patch, poll_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)], catch_exceptions=False)
    assert result.exit_code == 0
    # QUIET DEFAULT: stdout is exactly the id + newline (clean redirect),
    # and no status chatter appears anywhere without --verbose.
    assert result.stdout == POST_ID + "\n"
    assert result.stderr == ""
    assert mock.call_args.args[1] == video
    assert mock.call_args.kwargs["post_id"] == POST_ID  # CLI-minted UUID
    assert not poll_mock.called  # async: never polls


def test_analyze_verbose_chatter_on_stderr_only(tmp_path):
    video = _video(tmp_path)
    events = [
        {"event": "upload_progress", "bytes_sent": 1, "total_bytes": 1,
         "pct": 100.0},
    ]
    upload_patch, _ = _upload_patch(events=events)
    with upload_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--verbose"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert result.stdout == POST_ID + "\n"  # stdout stays pure
    assert "Analyzing" in result.stderr
    assert "Uploading" in result.stderr
    assert "analyze --id" in result.stderr  # the fetch-later hint


def test_analyze_verbose_retry_line_on_stderr(tmp_path):
    video = _video(tmp_path)
    events = [
        {"event": "upload_retry", "post_id": POST_ID, "attempt": 2,
         "max_attempts": 3, "reason": "HTTP 503", "retry_after_seconds": 1.0},
    ]
    upload_patch, _ = _upload_patch(events=events)
    with upload_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--verbose"], catch_exceptions=False
        )
    assert result.stdout == POST_ID + "\n"
    assert "retrying with the same id (attempt 2/3)" in result.stderr


def test_analyze_default_swallows_progress_events(tmp_path):
    """Progress events produce NO output in default (quiet) human mode."""
    video = _video(tmp_path)
    events = [
        {"event": "upload_progress", "bytes_sent": 1, "total_bytes": 1,
         "pct": 100.0},
        {"event": "upload_retry", "post_id": POST_ID, "attempt": 2,
         "max_attempts": 3, "reason": "HTTP 503", "retry_after_seconds": 1.0},
    ]
    upload_patch, _ = _upload_patch(events=events)
    with upload_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video)], catch_exceptions=False
        )
    assert result.stdout == POST_ID + "\n"
    assert result.stderr == ""


def test_analyze_async_appends_ledger(tmp_path, ledger_path):
    video = _video(tmp_path, data=b"unique-bytes")
    upload_patch, _ = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)], catch_exceptions=False)
    assert result.exit_code == 0
    # Two lines, same client-minted id: the attempt ("pending", written
    # before the bytes move) and the completed upload ("uploaded").
    entries = ledger.read_entries(ledger_path)
    assert [e["upload_status"] for e in entries] == ["pending", "uploaded"]
    assert {e["post_id"] for e in entries} == {POST_ID}
    entry = entries[-1]
    assert entry["file"] == str(video)
    assert entry["sha256"] == ledger.sha256_file(video)
    assert entry["size_bytes"] == len(b"unique-bytes")
    assert entry["server"] == SERVER
    assert "uploaded_at" in entry
    # latest-wins view collapses the pair to the completed record
    latest = ledger.latest_entries(ledger_path)
    assert len(latest) == 1
    assert latest[0]["upload_status"] == "uploaded"


def test_analyze_async_json_submitted_event(tmp_path):
    video = _video(tmp_path)
    events = [
        {"event": "upload_progress", "bytes_sent": 0, "total_bytes": 1, "pct": 0.0},
        {"event": "upload_progress", "bytes_sent": 1, "total_bytes": 1, "pct": 100.0},
    ]
    upload_patch, _ = _upload_patch(events=events)
    with upload_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--json"], catch_exceptions=False
        )
    assert result.exit_code == 0
    docs = _parse_ndjson(result.stdout)
    assert [d["event"] for d in docs] == [
        "upload_progress", "upload_progress", "submitted",
    ]
    assert docs[-1]["post_id"] == POST_ID
    assert docs[-1]["video_path"] == str(video)
    assert docs[-1]["deduped"] is False  # a real upload, not a reuse


def test_analyze_resolves_work_dir(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "final.mp4").write_bytes(b"x")
    (work / "showrunner.json").write_text(json.dumps({"output_path": "final.mp4"}))
    upload_patch, mock = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(cli, ["analyze", str(work)], catch_exceptions=False)
    assert result.exit_code == 0
    assert mock.call_args.args[1] == work / "final.mp4"


def test_analyze_duplicate_warning_human(tmp_path, ledger_path):
    video = _video(tmp_path, data=b"same-bytes")
    ledger.record_upload(
        post_id="prior-1", file="old.mp4", sha256=ledger.sha256_file(video),
        size_bytes=10, server=SERVER, path=ledger_path,
    )
    upload_patch, mock = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)], catch_exceptions=False)
    assert result.exit_code == 0
    assert "prior-1" in result.stderr  # gentle warning with the prior id
    assert mock.called  # ...but the upload still proceeds
    assert result.stdout.strip() == POST_ID


def test_analyze_duplicate_warning_json_event(tmp_path, ledger_path):
    video = _video(tmp_path, data=b"same-bytes")
    ledger.record_upload(
        post_id="prior-1", file="old.mp4", sha256=ledger.sha256_file(video),
        size_bytes=10, server=SERVER, path=ledger_path,
    )
    upload_patch, _ = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--json"], catch_exceptions=False
        )
    docs = _parse_ndjson(result.stdout)
    dup = [d for d in docs if d["event"] == "duplicate_warning"]
    assert len(dup) == 1
    assert dup[0]["prior_post_id"] == "prior-1"
    assert docs[-1]["event"] == "submitted"


def test_analyze_old_duplicate_not_warned(tmp_path, ledger_path):
    """An identical upload older than the ~24h window stays quiet."""
    import time

    video = _video(tmp_path, data=b"same-bytes")
    ledger.record_upload(
        post_id="prior-1", file="old.mp4", sha256=ledger.sha256_file(video),
        size_bytes=10, server=SERVER, path=ledger_path,
        now=time.time() - 3 * 86400,
    )
    upload_patch, _ = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)], catch_exceptions=False)
    assert "prior-1" not in result.stderr


def test_analyze_duplicate_warn_message_on_stderr_by_default(tmp_path, ledger_path):
    """The dedup warning matters — stderr even without --verbose."""
    video = _video(tmp_path, data=b"same-bytes")
    ledger.record_upload(
        post_id="prior-1", file="old.mp4", sha256=ledger.sha256_file(video),
        size_bytes=10, server=SERVER, path=ledger_path,
    )
    upload_patch, _ = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)], catch_exceptions=False)
    assert result.stdout == POST_ID + "\n"  # payload stays pure
    assert "prior-1" in result.stderr


# ── --if-duplicate {warn,reuse,fail} ─────────────────────────────────


PRIOR_ID = "11111111-2222-4333-8444-555555555555"


def _prior_upload(ledger_path, video, post_id=PRIOR_ID, **kw):
    return ledger.record_upload(
        post_id=post_id, file="old.mp4", sha256=ledger.sha256_file(video),
        size_bytes=10, server=SERVER, path=ledger_path, **kw,
    )


def test_if_duplicate_reuse_prints_prior_id_without_uploading(
    tmp_path, ledger_path
):
    video = _video(tmp_path, data=b"same-bytes")
    _prior_upload(ledger_path, video)
    upload_patch, mock = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--if-duplicate", "reuse"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert result.stdout == PRIOR_ID + "\n"  # the prior id, stdout-pure
    assert "Reusing prior upload" in result.stderr
    assert not mock.called  # NO upload request issued
    # and nothing new in the ledger
    assert [e["post_id"] for e in ledger.read_entries(ledger_path)] == [PRIOR_ID]


def test_if_duplicate_reuse_json_emits_prior_record_deduped(
    tmp_path, ledger_path
):
    video = _video(tmp_path, data=b"same-bytes")
    prior = _prior_upload(ledger_path, video)
    upload_patch, mock = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--if-duplicate", "reuse", "--json"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    docs = _parse_ndjson(result.stdout)
    assert len(docs) == 1  # no upload events — nothing was uploaded
    doc = docs[0]
    assert doc["event"] == "submitted"
    assert doc["deduped"] is True
    assert doc["post_id"] == PRIOR_ID
    assert doc["uploaded_at"] == prior["uploaded_at"]  # the prior record
    assert doc["video_path"] == str(video)
    assert not mock.called


def test_if_duplicate_fail_refuses_with_exit_3(tmp_path, ledger_path):
    video = _video(tmp_path, data=b"same-bytes")
    _prior_upload(ledger_path, video)
    upload_patch, mock = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--if-duplicate", "fail"]
        )
    assert result.exit_code == 3
    assert result.stdout == ""  # nothing on stdout
    assert PRIOR_ID in result.stderr
    assert not mock.called  # NO upload request issued


def test_if_duplicate_fail_json_error_event(tmp_path, ledger_path):
    video = _video(tmp_path, data=b"same-bytes")
    _prior_upload(ledger_path, video)
    upload_patch, mock = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--if-duplicate", "fail", "--json"]
        )
    assert result.exit_code == 3
    docs = _parse_ndjson(result.stdout)
    assert docs[-1]["event"] == "error"
    assert docs[-1]["stage"] == "analyze"
    assert PRIOR_ID in docs[-1]["message"]
    assert not mock.called


def test_if_duplicate_modes_ignore_pending_only_records(tmp_path, ledger_path):
    """A lone interrupted attempt is not a duplicate — reuse must not
    return an id the server never finished receiving."""
    video = _video(tmp_path, data=b"same-bytes")
    _prior_upload(ledger_path, video, upload_status="pending")
    upload_patch, mock = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--if-duplicate", "reuse"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert mock.called  # not deduped: the upload proceeds (resuming the id)
    assert result.stdout == PRIOR_ID + "\n"  # the resumed pending id


def test_if_duplicate_rejects_unknown_mode(tmp_path):
    video = _video(tmp_path)
    result = CliRunner().invoke(
        cli, ["analyze", str(video), "--if-duplicate", "bogus"]
    )
    assert result.exit_code == 2


# ── interrupted uploads resume the same client-minted id ─────────────


def test_analyze_resumes_pending_upload_id(tmp_path, ledger_path):
    video = _video(tmp_path, data=b"same-bytes")
    _prior_upload(ledger_path, video, upload_status="pending")
    upload_patch, mock = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)], catch_exceptions=False)
    assert result.exit_code == 0
    # the interrupted attempt's UUID is reused, not a fresh mint
    assert mock.call_args.kwargs["post_id"] == PRIOR_ID
    assert result.stdout == PRIOR_ID + "\n"
    assert "Resuming interrupted upload" in result.stderr  # not verbose-gated
    latest = ledger.latest_entries(ledger_path)
    assert len(latest) == 1
    assert latest[0]["post_id"] == PRIOR_ID
    assert latest[0]["upload_status"] == "uploaded"


def test_analyze_resume_json_event(tmp_path, ledger_path):
    video = _video(tmp_path, data=b"same-bytes")
    _prior_upload(ledger_path, video, upload_status="pending")
    upload_patch, _ = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--json"], catch_exceptions=False
        )
    docs = _parse_ndjson(result.stdout)
    assert [d["event"] for d in docs] == ["upload_resume", "submitted"]
    assert docs[0]["post_id"] == PRIOR_ID
    assert docs[-1]["post_id"] == PRIOR_ID
    assert docs[-1]["deduped"] is False  # a real upload happened


def test_analyze_pending_record_with_invalid_uuid_mints_fresh(
    tmp_path, ledger_path
):
    video = _video(tmp_path, data=b"same-bytes")
    _prior_upload(ledger_path, video, post_id="not-a-uuid",
                  upload_status="pending")
    upload_patch, mock = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)], catch_exceptions=False)
    assert result.exit_code == 0
    assert mock.call_args.kwargs["post_id"] == POST_ID  # freshly minted
    assert result.stdout == POST_ID + "\n"


def test_analyze_completed_upload_not_resumed(tmp_path, ledger_path):
    """Only pending (interrupted) ids are resumed; a completed upload
    mints fresh (after the duplicate warning)."""
    video = _video(tmp_path, data=b"same-bytes")
    _prior_upload(ledger_path, video)  # uploaded
    upload_patch, mock = _upload_patch()
    with upload_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)], catch_exceptions=False)
    assert result.exit_code == 0
    assert mock.call_args.kwargs["post_id"] == POST_ID  # fresh mint
    assert "Resuming" not in result.stderr


def test_analyze_not_logged_in(tmp_path):
    video = _video(tmp_path)
    upload_patch, _ = _upload_patch(side_effect=NotLoggedInError())
    with upload_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)])
    assert result.exit_code == 1
    assert "showrunner login" in result.output


def test_analyze_server_rejection_json(tmp_path):
    from showrunner.cloud.analyze import AnalyzeError

    video = _video(tmp_path)
    rejection = AnalyzeError("Upload rate limit reached. Try again in ~60s.")
    upload_patch, _ = _upload_patch(side_effect=rejection)
    with upload_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video), "--json"])
    assert result.exit_code == 1
    docs = _parse_ndjson(result.stdout)
    assert docs[-1] == {
        "event": "error", "stage": "analyze", "message": str(rejection),
    }


def test_analyze_empty_work_dir_exit_2(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    result = CliRunner().invoke(cli, ["analyze", str(work)])
    assert result.exit_code == 2
    assert "Could not find a rendered video" in result.output


def test_analyze_artifact_flag_without_sync_is_usage_error(tmp_path):
    video = _video(tmp_path)
    result = CliRunner().invoke(cli, ["analyze", str(video), "--full"])
    assert result.exit_code == 2
    assert "--sync" in result.output


def test_analyze_output_without_sync_is_usage_error(tmp_path):
    video = _video(tmp_path)
    result = CliRunner().invoke(cli, ["analyze", str(video), "--output", "x.json"])
    assert result.exit_code == 2
    assert "--sync" in result.output


# ── PATH source: --sync ──────────────────────────────────────────────


def test_analyze_sync_default_stdout_is_payload_only(tmp_path):
    """--sync default mode: stdout is exactly the artifact content —
    no leading blank line, no 'Analyzing…' banner, no progress lines."""
    video = _video(tmp_path)
    upload_patch, _ = _upload_patch()
    poll_patch, _ = _poll_patch()
    with upload_patch, poll_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--sync"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert result.stdout.startswith("Summary")
    assert result.stderr == ""


def test_analyze_sync_polls_and_prints_report(tmp_path):
    video = _video(tmp_path)
    upload_patch, _ = _upload_patch()
    poll_patch, poll_mock = _poll_patch()
    with upload_patch, poll_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--sync"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert "A tight explainer." in result.output  # default --report
    assert poll_mock.call_args.args[1] == POST_ID
    assert poll_mock.call_args.kwargs["max_wait_seconds"] == 600.0


def test_analyze_sync_honors_timeout(tmp_path):
    video = _video(tmp_path)
    upload_patch, _ = _upload_patch()
    poll_patch, poll_mock = _poll_patch()
    with upload_patch, poll_patch:
        CliRunner().invoke(
            cli, ["analyze", str(video), "--sync", "--timeout", "42"],
            catch_exceptions=False,
        )
    assert poll_mock.call_args.kwargs["max_wait_seconds"] == 42.0


def test_analyze_sync_json_done_event_with_artifacts(tmp_path):
    video = _video(tmp_path)
    upload_patch, _ = _upload_patch()
    poll_patch, _ = _poll_patch()
    with upload_patch, poll_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--sync", "--json"], catch_exceptions=False
        )
    docs = _parse_ndjson(result.stdout)
    done = docs[-1]
    assert done["event"] == "done"
    assert done["post_id"] == POST_ID
    assert done["status"] == "ready"
    assert "A tight explainer." in done["report"]
    assert done["analysis"] == ANALYSIS  # kept for the additive contract


def test_analyze_sync_artifact_flags(tmp_path):
    video = _video(tmp_path)
    upload_patch, _ = _upload_patch()
    poll_patch, _ = _poll_patch()
    with upload_patch, poll_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--sync", "--transcript", "--json"],
            catch_exceptions=False,
        )
    done = _parse_ndjson(result.stdout)[-1]
    assert done["transcript"] == ANALYSIS["transcript_segments"]
    assert "report" not in done


def test_analyze_sync_output_writes_result(tmp_path):
    video = _video(tmp_path)
    out = tmp_path / "analysis.txt"
    upload_patch, _ = _upload_patch()
    poll_patch, _ = _poll_patch()
    with upload_patch, poll_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--sync", "--output", str(out)],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert "A tight explainer." in out.read_text()


# ── --id source: single check, artifacts ─────────────────────────────


def test_id_ready_prints_report_by_default():
    check_patch, mock = _check_patch()
    with check_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert "A tight explainer." in result.output
    assert mock.call_args.args[1] == POST_ID


def test_id_ready_json_single_object():
    check_patch, _ = _check_patch()
    with check_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--json"], catch_exceptions=False
        )
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["post_id"] == POST_ID
    assert doc["status"] == "ready"
    assert "A tight explainer." in doc["report"]


def test_id_pending_exits_2():
    check_patch, _ = _check_patch(analysis=None)
    with check_patch:
        result = CliRunner().invoke(cli, ["analyze", "--id", POST_ID])
    assert result.exit_code == 2
    assert "not ready" in result.stderr
    assert result.stdout == ""


def test_id_pending_json_exits_2():
    check_patch, _ = _check_patch(analysis=None)
    with check_patch:
        result = CliRunner().invoke(cli, ["analyze", "--id", POST_ID, "--json"])
    assert result.exit_code == 2
    doc = json.loads(result.stdout)
    assert doc == {"post_id": POST_ID, "status": "pending"}


def test_id_failed_exits_1_with_reason():
    from showrunner.cloud.analyze import AnalysisFailed

    check_patch, _ = _check_patch(side_effect=AnalysisFailed("corrupt_video"))
    with check_patch:
        result = CliRunner().invoke(cli, ["analyze", "--id", POST_ID])
    assert result.exit_code == 1
    assert "corrupt_video" in result.stderr


def test_id_failed_json_shape():
    from showrunner.cloud.analyze import AnalysisFailed

    check_patch, _ = _check_patch(side_effect=AnalysisFailed("corrupt_video"))
    with check_patch:
        result = CliRunner().invoke(cli, ["analyze", "--id", POST_ID, "--json"])
    assert result.exit_code == 1
    doc = json.loads(result.stdout)
    assert doc["status"] == "failed"
    assert doc["post_id"] == POST_ID
    assert doc["failure_reason"] == "corrupt_video"


def test_id_not_logged_in_exits_1():
    check_patch, _ = _check_patch(side_effect=NotLoggedInError())
    with check_patch:
        result = CliRunner().invoke(cli, ["analyze", "--id", POST_ID])
    assert result.exit_code == 1
    assert "showrunner login" in result.stderr


def test_id_sync_polls_until_ready():
    check_patch, _ = _check_patch(analysis=None)  # first check: pending
    poll_patch, poll_mock = _poll_patch()
    with check_patch, poll_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--sync", "--timeout", "120"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert "A tight explainer." in result.output
    assert poll_mock.call_args.kwargs["max_wait_seconds"] == 120.0


def test_id_sync_ready_immediately_skips_polling():
    check_patch, _ = _check_patch()
    poll_patch, poll_mock = _poll_patch()
    with check_patch, poll_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--sync"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert not poll_mock.called


def test_id_sync_timeout_exits_2():
    from showrunner.cloud.analyze import AnalysisTimeout

    check_patch, _ = _check_patch(analysis=None)
    poll_patch, _ = _poll_patch(side_effect=AnalysisTimeout("Timed out after 600s"))
    with check_patch, poll_patch:
        result = CliRunner().invoke(cli, ["analyze", "--id", POST_ID, "--sync"])
    assert result.exit_code == 2
    assert "Timed out" in result.stderr


def test_id_output_writes_result(tmp_path):
    out = tmp_path / "analysis.txt"
    check_patch, _ = _check_patch()
    with check_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--output", str(out)],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert "A tight explainer." in out.read_text()


def test_id_output_json_writes_object(tmp_path):
    out = tmp_path / "analysis.json"
    check_patch, _ = _check_patch()
    with check_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--full", "--output", str(out),
                  "--json"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    saved = json.loads(out.read_text())
    assert saved["full"] == ANALYSIS
    assert saved["post_id"] == POST_ID


# ── artifact flags ───────────────────────────────────────────────────


def test_id_full_json():
    check_patch, _ = _check_patch()
    with check_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--full", "--json"],
            catch_exceptions=False,
        )
    doc = json.loads(result.stdout)
    assert doc["full"] == ANALYSIS
    assert "report" not in doc  # only requested artifacts


def test_id_transcript_human_is_plain_text():
    check_patch, _ = _check_patch()
    with check_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--transcript"], catch_exceptions=False
        )
    assert result.exit_code == 0
    # stdout purity: exactly the artifact content, redirect-safe
    assert result.stdout == "Cats are great.\nHere is why.\n"
    assert result.stderr == ""


def test_id_transcript_json_is_time_coded_segments():
    check_patch, _ = _check_patch()
    with check_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--transcript", "--json"],
            catch_exceptions=False,
        )
    doc = json.loads(result.stdout)
    assert doc["transcript"] == ANALYSIS["transcript_segments"]


def test_id_overlays():
    check_patch, _ = _check_patch()
    with check_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--overlays"], catch_exceptions=False
        )
    assert "[0.5-1.5] CATS!" in result.stdout


def test_id_scenes():
    check_patch, _ = _check_patch()
    with check_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--scenes"], catch_exceptions=False
        )
    assert "1. Intro" in result.stdout


def test_id_multiple_artifacts_human_titled_sections():
    check_patch, _ = _check_patch()
    with check_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--report", "--transcript"],
            catch_exceptions=False,
        )
    assert "Report\n------" in result.stdout
    assert "Transcript\n----------" in result.stdout
    assert "Cats are great." in result.stdout


def test_id_multiple_artifacts_json_one_object():
    check_patch, _ = _check_patch()
    with check_patch:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--report", "--transcript",
                  "--scenes", "--json"],
            catch_exceptions=False,
        )
    doc = json.loads(result.stdout)
    assert set(doc) == {"post_id", "status", "report", "transcript", "scenes"}


def test_id_caption_calls_generate_endpoint():
    check_patch, _ = _check_patch()
    with check_patch, patch(
        "showrunner.cloud.analyze.generate_caption",
        return_value="Cats! 🐱 #cats",
    ) as mock:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--caption"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert "Cats!" in result.stdout
    assert mock.call_args.args[1] == POST_ID


def test_id_caption_json():
    check_patch, _ = _check_patch()
    with check_patch, patch(
        "showrunner.cloud.analyze.generate_caption", return_value="A caption",
    ):
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--caption", "--json"],
            catch_exceptions=False,
        )
    doc = json.loads(result.stdout)
    assert doc["caption"] == "A caption"


def test_id_video_url_prints_bare_url():
    url = "https://cdn.example.test/signed/clip.mp4?sig=abc"
    check_patch, _ = _check_patch()
    with check_patch, patch(
        "showrunner.cloud.analyze.get_video_url", return_value=url
    ) as mock:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--video-url"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert result.stdout.strip() == url
    assert mock.call_args.args[1] == POST_ID


def test_id_video_url_json():
    url = "https://cdn.example.test/signed/clip.mp4?sig=abc"
    check_patch, _ = _check_patch()
    with check_patch, patch(
        "showrunner.cloud.analyze.get_video_url", return_value=url
    ):
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--video-url", "--json"],
            catch_exceptions=False,
        )
    doc = json.loads(result.stdout)
    assert doc["video_url"] == url
    assert doc["post_id"] == POST_ID


def test_id_video_downloads_to_explicit_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    check_patch, _ = _check_patch()
    with check_patch, patch(
        "showrunner.cloud.analyze.download_video",
        side_effect=lambda client, post_id, dest, **kw: dest,
    ) as mock:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--video", "saved.mp4"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert mock.call_args.args[2] == Path("saved.mp4")
    assert "saved.mp4" in result.stdout


def test_id_video_default_name_from_ledger(tmp_path, ledger_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ledger.record_upload(
        post_id=POST_ID, file="/somewhere/original-name.mp4", sha256="s",
        size_bytes=1, server=SERVER, path=ledger_path,
    )
    check_patch, _ = _check_patch()
    with check_patch, patch(
        "showrunner.cloud.analyze.download_video",
        side_effect=lambda client, post_id, dest, **kw: dest,
    ) as mock:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--video"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert mock.call_args.args[2] == Path("original-name.mp4")


def test_id_video_default_name_without_ledger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    check_patch, _ = _check_patch()
    with check_patch, patch(
        "showrunner.cloud.analyze.download_video",
        side_effect=lambda client, post_id, dest, **kw: dest,
    ) as mock:
        result = CliRunner().invoke(
            cli, ["analyze", "--id", POST_ID, "--video"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert mock.call_args.args[2] == Path(f"{POST_ID}.mp4")


def test_id_video_url_error_exits_1():
    from showrunner.cloud.analyze import AnalyzeError

    check_patch, _ = _check_patch()
    with check_patch, patch(
        "showrunner.cloud.analyze.get_video_url",
        side_effect=AnalyzeError("No stored video found"),
    ):
        result = CliRunner().invoke(cli, ["analyze", "--id", POST_ID, "--video-url"])
    assert result.exit_code == 1
    assert "No stored video" in result.stderr


# ── create --analyze ─────────────────────────────────────────────────


def _plan():
    from showrunner.plan import Plan, Scene

    return Plan(
        title="Test Video", total_duration=10,
        scenes=[Scene(id="intro", duration=10, narration="Hi", visual="Card")],
    )


def _mock_registry(fmt):
    registry = MagicMock()
    registry.get.return_value = fmt
    registry.list.return_value = ["faceless-explainer"]
    return registry


def _mock_format():
    fmt = MagicMock()
    fmt.preferred_render_provider = "remotion"
    fmt.requires_video_provider = False
    fmt.plan.return_value = _plan()
    fmt.generate_assets.return_value = {
        "has_audio": True, "durations": {}, "width": 1080, "height": 1920,
    }
    return fmt


def _run_create_analyze(args, *patches):
    """Run `create` with a fully mocked pipeline; the rendered mp4 exists."""
    from contextlib import ExitStack

    output = Path("out/video.mp4")
    render = MagicMock()

    def do_render(work_dir, output_path):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp4")
        return output

    render.render.side_effect = do_render
    providers = {"llm": MagicMock(), "tts": MagicMock(), "render": render}
    runner = CliRunner()
    with runner.isolated_filesystem():
        with ExitStack() as stack:
            stack.enter_context(patch(
                "showrunner.pipeline.get_registry",
                return_value=_mock_registry(_mock_format()),
            ))
            stack.enter_context(patch(
                "showrunner.pipeline.Pipeline._create_providers",
                return_value=providers,
            ))
            for p in patches:
                stack.enter_context(p)
            result = runner.invoke(cli, args, catch_exceptions=False)
    return result


def test_create_analyze_submits_and_prints_post_id():
    upload_patch, mock = _upload_patch()
    poll_patch, poll_mock = _poll_patch()
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve", "--analyze"], upload_patch, poll_patch
    )
    assert result.exit_code == 0
    assert "Video rendered" in result.output
    assert f"Analysis submitted: {POST_ID}" in result.output
    assert "analyze --id" in result.output
    assert mock.call_args.args[1] == Path("out/video.mp4")
    assert not poll_mock.called  # NEVER polls


def test_create_analyze_appends_ledger(ledger_path):
    upload_patch, _ = _upload_patch()
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve", "--analyze"], upload_patch
    )
    assert result.exit_code == 0
    # attempt line + completed line, same minted id; latest wins on read
    entries = ledger.read_entries(ledger_path)
    assert [e["upload_status"] for e in entries] == ["pending", "uploaded"]
    assert {e["post_id"] for e in entries} == {POST_ID}
    latest = ledger.latest_entries(ledger_path)
    assert len(latest) == 1
    assert latest[0]["post_id"] == POST_ID


def test_create_analyze_json_submitted_after_done():
    events = [
        {"event": "upload_progress", "bytes_sent": 3, "total_bytes": 3, "pct": 100.0},
    ]
    upload_patch, _ = _upload_patch(events=events)
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve", "--analyze", "--json"], upload_patch
    )
    assert result.exit_code == 0
    names = [d["event"] for d in _parse_ndjson(result.stdout)]
    # the render's terminal `done` stays exactly where it always was;
    # analyze events append after it, ending in `submitted`.
    done_idx = names.index("done")
    assert names[done_idx + 1:] == ["upload_progress", "submitted"]
    docs = _parse_ndjson(result.stdout)
    assert docs[-1]["post_id"] == POST_ID


def test_create_analyze_not_logged_in_never_breaks_render():
    upload_patch, _ = _upload_patch(side_effect=NotLoggedInError())
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve", "--analyze"], upload_patch
    )
    # render succeeded and is reported; analyze failure exits nonzero
    assert "Video rendered" in result.output
    assert result.exit_code == 1
    assert "showrunner login" in result.output


def test_create_analyze_unexpected_error_never_breaks_render():
    upload_patch, _ = _upload_patch(side_effect=RuntimeError("boom"))
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve", "--analyze"], upload_patch
    )
    assert "Video rendered" in result.output
    assert result.exit_code == 1
    assert "boom" in result.output


def test_create_analyze_json_error_event_after_done():
    upload_patch, _ = _upload_patch(side_effect=NotLoggedInError())
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve", "--analyze", "--json"], upload_patch
    )
    assert result.exit_code == 1
    docs = _parse_ndjson(result.stdout)
    names = [d["event"] for d in docs]
    assert "done" in names  # the render still completed
    assert names[-1] == "error"
    assert "showrunner login" in docs[-1]["message"]


def test_create_without_analyze_unchanged():
    upload_patch, mock = _upload_patch()
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve"], upload_patch
    )
    assert result.exit_code == 0
    assert not mock.called
