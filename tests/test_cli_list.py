"""CLI: `showrunner list` — remote drafts listing + --local ledger view."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

httpx = pytest.importorskip("httpx", reason="cloud extra (httpx) not installed")

from showrunner.cli.main import cli  # noqa: E402
from showrunner.cloud import ledger  # noqa: E402
from showrunner.cloud.credentials import (  # noqa: E402
    Credentials,
    CredentialStore,
    NotLoggedInError,
)

SERVER = "https://api.gpt.social"  # the built-in default


@pytest.fixture(autouse=True)
def isolated_creds(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "showrunner.cloud.credentials.default_credentials_path",
        lambda: tmp_path / "credentials.json",
    )
    monkeypatch.setattr(CredentialStore, "_keyring", lambda self: None)
    monkeypatch.delenv("SHOWRUNNER_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def ledger_path(tmp_path, monkeypatch):
    path = tmp_path / "analyses.jsonl"
    monkeypatch.setattr(
        "showrunner.cloud.ledger.default_ledger_path", lambda: path
    )
    return path


def _save_creds(method="firebase"):
    CredentialStore().save(Credentials(
        server_url=SERVER, access_token="at-1", refresh_token="rt-1",
        expires_at=time.time() + 3600, method=method,
    ))


def _rows_patch(rows=None, side_effect=None):
    mock = MagicMock(return_value=rows if rows is not None else [],
                     side_effect=side_effect)
    return patch("showrunner.cloud.analyze.list_videos", mock), mock


def _iso(seconds_ago: float) -> str:
    from datetime import datetime, timedelta, timezone

    return (
        datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    ).isoformat(timespec="seconds")


def _rows():
    return [
        {"post_id": "p-new", "filename": "cats.mp4",
         "created_at": _iso(60), "analysis_status": "completed"},
        {"post_id": "p-mid", "title": "Dogs explainer",
         "created_at": _iso(7200), "status": "processing"},
        {"post_id": "p-old", "created_at": _iso(3 * 86400)},
    ]


ROWS = _rows()


# ── remote (default) ─────────────────────────────────────────────────


def test_list_remote_renders_rows():
    _save_creds()
    rows_patch, mock = _rows_patch(_rows())
    with rows_patch:
        result = CliRunner().invoke(cli, ["list"], catch_exceptions=False)
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert "p-new" in lines[0] and "cats.mp4" in lines[0] and "done" in lines[0]
    assert "p-mid" in lines[1] and "Dogs explainer" in lines[1]
    assert "pending" in lines[1] and "2h ago" in lines[1]
    assert "p-old" in lines[2] and "3d ago" in lines[2]
    assert lines[2].rstrip().endswith("-")  # unknown status → "-"
    assert mock.call_args.kwargs["limit"] == 20  # the default


def test_list_remote_json_emits_raw_records():
    _save_creds()
    rows_patch, _ = _rows_patch(ROWS)
    with rows_patch:
        result = CliRunner().invoke(cli, ["list", "--json"], catch_exceptions=False)
    doc = json.loads(result.stdout)
    assert doc == {"videos": ROWS}


def test_list_remote_limit_passthrough():
    _save_creds()
    rows_patch, mock = _rows_patch([])
    with rows_patch:
        CliRunner().invoke(cli, ["list", "--limit", "50"], catch_exceptions=False)
    assert mock.call_args.kwargs["limit"] == 50


def test_list_remote_status_filter_client_side():
    _save_creds()
    rows_patch, _ = _rows_patch(ROWS)
    with rows_patch:
        result = CliRunner().invoke(
            cli, ["list", "--status", "done", "--json"], catch_exceptions=False
        )
    doc = json.loads(result.stdout)
    assert [r["post_id"] for r in doc["videos"]] == ["p-new"]


def test_list_remote_empty():
    _save_creds()
    rows_patch, _ = _rows_patch([])
    with rows_patch:
        result = CliRunner().invoke(cli, ["list"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "No uploaded videos" in result.output


def test_list_unauthorized_under_oauth_prints_hint():
    from showrunner.cloud.analyze import ListUnauthorized

    _save_creds(method="oauth")
    rows_patch, _ = _rows_patch(
        side_effect=ListUnauthorized("The server refused the video listing (HTTP 403).")
    )
    with rows_patch:
        result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 1
    assert "--with-password" in result.output
    assert "scrollmark/platform#15546" in result.output


def test_list_unauthorized_under_firebase_no_oauth_hint():
    from showrunner.cloud.analyze import ListUnauthorized

    _save_creds(method="firebase")
    rows_patch, _ = _rows_patch(
        side_effect=ListUnauthorized("The server refused the video listing (HTTP 403).")
    )
    with rows_patch:
        result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 1
    assert "scrollmark/platform#15546" not in result.output
    assert "analysis:read" in result.output


def test_list_unauthorized_json():
    from showrunner.cloud.analyze import ListUnauthorized

    _save_creds(method="oauth")
    rows_patch, _ = _rows_patch(side_effect=ListUnauthorized("HTTP 403"))
    with rows_patch:
        result = CliRunner().invoke(cli, ["list", "--json"])
    assert result.exit_code == 1
    doc = json.loads(result.output)
    assert doc["error"] == "unauthorized"
    assert "--with-password" in doc["message"]


def test_list_not_logged_in():
    rows_patch, _ = _rows_patch(side_effect=NotLoggedInError())
    with rows_patch:
        result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 1
    assert "showrunner login" in result.output


# ── --local (ledger view) ────────────────────────────────────────────


def test_list_local_empty_ledger():
    result = CliRunner().invoke(cli, ["list", "--local"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "No recorded uploads" in result.output


def test_list_local_newest_first(ledger_path):
    now = time.time()
    ledger.record_upload(post_id="old-1", file="a.mp4", sha256="s1",
                         size_bytes=1, server=SERVER, path=ledger_path,
                         now=now - 7200)
    ledger.record_upload(post_id="new-1", file="b.mp4", sha256="s2",
                         size_bytes=2, server=SERVER, path=ledger_path,
                         now=now - 60)
    result = CliRunner().invoke(cli, ["list", "--local"], catch_exceptions=False)
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert "new-1" in lines[0] and "1m ago" in lines[0]
    assert "old-1" in lines[1] and "2h ago" in lines[1]
    assert "a.mp4" in lines[1]


def test_list_local_shows_unknown_status_as_dash(ledger_path):
    ledger.record_upload(post_id="p-1", file="a.mp4", sha256="s1",
                         size_bytes=1, server=SERVER, path=ledger_path)
    result = CliRunner().invoke(cli, ["list", "--local"], catch_exceptions=False)
    assert "-  a.mp4" in result.output.splitlines()[0]


def test_list_local_json_emits_records(ledger_path):
    ledger.record_upload(post_id="p-1", file="a.mp4", sha256="s1",
                         size_bytes=1, server=SERVER, path=ledger_path)
    result = CliRunner().invoke(cli, ["list", "--local", "--json"],
                                catch_exceptions=False)
    doc = json.loads(result.stdout)
    assert len(doc["analyses"]) == 1
    assert doc["analyses"][0]["post_id"] == "p-1"
    assert doc["analyses"][0]["sha256"] == "s1"


def test_list_local_respects_limit(ledger_path):
    now = time.time()
    for i in range(5):
        ledger.record_upload(post_id=f"p-{i}", file=f"{i}.mp4", sha256=f"s{i}",
                             size_bytes=i, server=SERVER, path=ledger_path,
                             now=now - i * 60)
    result = CliRunner().invoke(cli, ["list", "--local", "--limit", "2"],
                                catch_exceptions=False)
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) == 2
    assert "p-0" in lines[0]  # newest


def test_list_local_status_filter_never_matches(ledger_path):
    """Ledger rows carry no analysis status — --status filters them out."""
    ledger.record_upload(post_id="p-1", file="a.mp4", sha256="s1",
                         size_bytes=1, server=SERVER, path=ledger_path)
    result = CliRunner().invoke(cli, ["list", "--local", "--status", "done"],
                                catch_exceptions=False)
    assert result.exit_code == 0
    assert "p-1" not in result.output


def test_list_local_tolerates_corrupt_ledger_lines(ledger_path):
    ledger.record_upload(post_id="ok-1", file="a.mp4", sha256="s1",
                         size_bytes=1, server=SERVER, path=ledger_path)
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write("{corrupt json\n")
        f.write("[1, 2, 3]\n")
    result = CliRunner().invoke(cli, ["list", "--local"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "ok-1" in result.output


def test_list_local_works_logged_out(ledger_path):
    """--local never talks to the server — no credentials needed."""
    ledger.record_upload(post_id="p-1", file="a.mp4", sha256="s1",
                         size_bytes=1, server=SERVER, path=ledger_path)
    rows_patch, mock = _rows_patch()
    with rows_patch:
        result = CliRunner().invoke(cli, ["list", "--local"], catch_exceptions=False)
    assert result.exit_code == 0
    assert not mock.called
