"""CLI: `showrunner analyze` + `showrunner create --analyze`."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

httpx = pytest.importorskip("httpx", reason="cloud extra (httpx) not installed")

from showrunner.cli.main import cli  # noqa: E402
from showrunner.cloud.credentials import CredentialStore, NotLoggedInError  # noqa: E402

ANALYSIS = {
    "executive_summary": "A tight explainer.",
    "hooks": [{"text": "What if cats could talk?"}],
    "scenes": [{"description": "Intro"}],
    "content_themes": ["cats"],
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


def _analyze_patch(analysis=None, side_effect=None, events=()):
    """Patch upload_and_analyze; optionally replay events into on_event."""

    def fake(client, video_path, *, on_event=None, **kwargs):
        if side_effect is not None:
            raise side_effect
        for ev in events:
            if on_event:
                on_event(ev)
        return analysis if analysis is not None else ANALYSIS

    mock = MagicMock(side_effect=fake)
    return patch("showrunner.cloud.analyze.upload_and_analyze", mock), mock


def _parse_ndjson(stdout: str) -> list[dict]:
    docs = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    assert all("event" in d for d in docs)
    return docs


# ── showrunner analyze ───────────────────────────────────────────────


def test_analyze_video_file_human(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    analyze_patch, mock = _analyze_patch()
    with analyze_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)], catch_exceptions=False)
    assert result.exit_code == 0
    assert "A tight explainer." in result.output
    assert "What if cats could talk?" in result.output
    assert mock.call_args.args[1] == video


def test_analyze_resolves_work_dir(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "final.mp4").write_bytes(b"x")
    (work / "showrunner.json").write_text(json.dumps({"output_path": "final.mp4"}))
    analyze_patch, mock = _analyze_patch()
    with analyze_patch:
        result = CliRunner().invoke(cli, ["analyze", str(work)], catch_exceptions=False)
    assert result.exit_code == 0
    assert mock.call_args.args[1] == work / "final.mp4"


def test_analyze_json_stream(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    events = [
        {"event": "upload_progress", "bytes_sent": 0, "total_bytes": 1, "pct": 0.0},
        {"event": "upload_progress", "bytes_sent": 1, "total_bytes": 1, "pct": 100.0},
        {"event": "analysis_pending", "status": "pending", "retry_after_seconds": 5},
    ]
    analyze_patch, _ = _analyze_patch(events=events)
    with analyze_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--json"], catch_exceptions=False
        )
    assert result.exit_code == 0
    docs = _parse_ndjson(result.output)
    assert [d["event"] for d in docs] == [
        "upload_progress", "upload_progress", "analysis_pending", "done",
    ]
    assert docs[-1]["analysis"] == ANALYSIS
    assert docs[-1]["video_path"] == str(video)


def test_analyze_output_saves_raw_json(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    out = tmp_path / "analysis.json"
    analyze_patch, _ = _analyze_patch()
    with analyze_patch:
        result = CliRunner().invoke(
            cli, ["analyze", str(video), "--output", str(out)], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert json.loads(out.read_text()) == ANALYSIS
    assert str(out) in result.output


def test_analyze_not_logged_in(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    analyze_patch, _ = _analyze_patch(side_effect=NotLoggedInError())
    with analyze_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)])
    assert result.exit_code == 1
    assert "showrunner login" in result.output


def test_analyze_server_rejection_json(tmp_path):
    from showrunner.cloud.analyze import AnalyzeError

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    rejection = AnalyzeError("Upload rate limit reached. Try again in ~60s.")
    analyze_patch, _ = _analyze_patch(side_effect=rejection)
    with analyze_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video), "--json"])
    assert result.exit_code == 1
    docs = _parse_ndjson(result.output)
    assert docs == [{
        "event": "error", "stage": "analyze", "message": str(rejection),
    }]


def test_analyze_failed_analysis_human(tmp_path):
    from showrunner.cloud.analyze import AnalysisFailed

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    analyze_patch, _ = _analyze_patch(side_effect=AnalysisFailed("corrupt_video"))
    with analyze_patch:
        result = CliRunner().invoke(cli, ["analyze", str(video)])
    assert result.exit_code == 1
    assert "corrupt_video" in result.output


def test_analyze_empty_work_dir_exit_2(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    result = CliRunner().invoke(cli, ["analyze", str(work)])
    assert result.exit_code == 2
    assert "Could not find a rendered video" in result.output


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


def _run_create_analyze(args, analyze_patch):
    """Run `create` with a fully mocked pipeline; the rendered mp4 exists."""
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
        with patch("showrunner.pipeline.get_registry",
                   return_value=_mock_registry(_mock_format())), \
             patch("showrunner.pipeline.Pipeline._create_providers",
                   return_value=providers), \
             analyze_patch:
            result = runner.invoke(cli, args, catch_exceptions=False)
    return result


def test_create_analyze_success_prints_analysis():
    analyze_patch, mock = _analyze_patch()
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve", "--analyze"], analyze_patch
    )
    assert result.exit_code == 0
    assert "Video rendered" in result.output
    assert "A tight explainer." in result.output
    assert mock.call_args.args[1] == Path("out/video.mp4")


def test_create_analyze_json_events_after_done():
    events = [
        {"event": "upload_progress", "bytes_sent": 3, "total_bytes": 3, "pct": 100.0},
        {"event": "analysis_pending", "status": "pending", "retry_after_seconds": 5},
    ]
    analyze_patch, _ = _analyze_patch(events=events)
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve", "--analyze", "--json"], analyze_patch
    )
    assert result.exit_code == 0
    names = [d["event"] for d in _parse_ndjson(result.stdout)]
    # the render's terminal `done` stays exactly where it always was;
    # analyze events append after it, ending in `analysis_done`.
    done_idx = names.index("done")
    assert names[done_idx + 1:] == [
        "upload_progress", "analysis_pending", "analysis_done",
    ]
    docs = _parse_ndjson(result.stdout)
    assert docs[-1]["analysis"] == ANALYSIS


def test_create_analyze_not_logged_in_never_breaks_render():
    analyze_patch, _ = _analyze_patch(side_effect=NotLoggedInError())
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve", "--analyze"], analyze_patch
    )
    # render succeeded and is reported; analyze failure exits nonzero
    assert "Video rendered" in result.output
    assert result.exit_code == 1
    assert "showrunner login" in result.output


def test_create_analyze_unexpected_error_never_breaks_render():
    analyze_patch, _ = _analyze_patch(side_effect=RuntimeError("boom"))
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve", "--analyze"], analyze_patch
    )
    assert "Video rendered" in result.output
    assert result.exit_code == 1
    assert "boom" in result.output


def test_create_analyze_json_error_event_after_done():
    analyze_patch, _ = _analyze_patch(side_effect=NotLoggedInError())
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve", "--analyze", "--json"], analyze_patch
    )
    assert result.exit_code == 1
    docs = _parse_ndjson(result.stdout)
    names = [d["event"] for d in docs]
    assert "done" in names  # the render still completed
    assert names[-1] == "error"
    assert "showrunner login" in docs[-1]["message"]


def test_create_without_analyze_unchanged():
    analyze_patch, mock = _analyze_patch()
    result = _run_create_analyze(
        ["create", "cats", "--auto-approve"], analyze_patch
    )
    assert result.exit_code == 0
    assert not mock.called
