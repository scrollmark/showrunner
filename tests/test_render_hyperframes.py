"""Tests for the HyperFrames render runtime (pinned npx CLI wrapper)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from showrunner.providers.render.hyperframes import (
    HYPERFRAMES_VERSION,
    HyperframesRenderProvider,
)


def test_setup_writes_contract_skeleton(tmp_path):
    provider = HyperframesRenderProvider()
    provider.setup(tmp_path, width=1080, height=1920, duration=30)

    html = (tmp_path / "index.html").read_text()
    assert 'data-composition-id="main"' in html
    assert 'data-duration="30"' in html
    assert 'data-width="1080"' in html
    assert 'data-height="1920"' in html
    assert 'window.__timelines["main"]' in html
    assert "gsap.timeline({ paused: true })" in html
    assert (tmp_path / "assets" / "audio").is_dir()


def test_setup_does_not_clobber_existing_composition(tmp_path):
    (tmp_path / "index.html").write_text("<!-- authored -->")
    HyperframesRenderProvider().setup(tmp_path, width=1080, height=1920, duration=30)
    assert (tmp_path / "index.html").read_text() == "<!-- authored -->"


def test_render_invokes_pinned_npx(tmp_path):
    provider = HyperframesRenderProvider()
    out = tmp_path / "out.mp4"
    with patch("showrunner.providers.render.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
        result = provider.render(work_dir=tmp_path, output_path=out)
    assert result == out
    argv = run.call_args.args[0]
    assert argv[:3] == ["npx", "-y", f"hyperframes@{HYPERFRAMES_VERSION}"]
    assert "render" in argv
    assert str(out) in argv
    assert run.call_args.kwargs["cwd"] == str(tmp_path)


def test_render_failure_raises_with_stderr(tmp_path):
    provider = HyperframesRenderProvider()
    with patch("showrunner.providers.render.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=1, stdout="", stderr="boom")):
        with pytest.raises(RuntimeError, match="boom"):
            provider.render(work_dir=tmp_path, output_path=tmp_path / "o.mp4")


def test_check_parses_passing_envelope(tmp_path):
    provider = HyperframesRenderProvider()
    envelope = {"ok": True, "errors": [], "warnings": []}
    with patch("showrunner.providers.render.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=0, stdout=json.dumps(envelope), stderr="")):
        ok, findings = provider.check(tmp_path)
    assert ok is True
    assert findings == []


def test_check_parses_failing_envelope(tmp_path):
    provider = HyperframesRenderProvider()
    envelope = {"ok": False, "errors": [{"message": "console error on load"}]}
    with patch("showrunner.providers.render.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=1, stdout=json.dumps(envelope), stderr="")):
        ok, findings = provider.check(tmp_path)
    assert ok is False
    assert findings and "console error" in findings[0]


def test_check_parses_sectioned_envelope(tmp_path):
    """Real CLI envelope: findings nested under sections like lint/layout,
    each with severity + message + fixHint."""
    provider = HyperframesRenderProvider()
    envelope = {
        "ok": False,
        "strict": False,
        "lint": {
            "ok": False,
            "errorCount": 1,
            "warningCount": 1,
            "findings": [
                {"code": "media_missing_id", "severity": "error",
                 "message": "<audio> has data-start but no id attribute.",
                 "fixHint": "Add a unique id attribute."},
                {"code": "timeline_track_too_dense", "severity": "warning",
                 "message": "Track 0 has 8 timed elements."},
            ],
        },
    }
    with patch("showrunner.providers.render.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=1, stdout=json.dumps(envelope), stderr="")):
        ok, findings = provider.check(tmp_path)
    assert ok is False
    # errors surface with their fix hint; warnings don't fail the gate alone
    assert any("media_missing_id" in f and "id attribute" in f for f in findings)
    assert not any("track_too_dense" in f for f in findings)


def test_check_handles_non_json_output(tmp_path):
    provider = HyperframesRenderProvider()
    with patch("showrunner.providers.render.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=1, stdout="npx blew up", stderr="")):
        ok, findings = provider.check(tmp_path)
    assert ok is False
    assert findings


def test_preview_uses_popen(tmp_path):
    provider = HyperframesRenderProvider()
    with patch("showrunner.providers.render.hyperframes.subprocess.Popen") as popen:
        provider.preview(tmp_path)
    argv = popen.call_args.args[0]
    assert "preview" in argv


def test_missing_node_gives_friendly_error(tmp_path):
    provider = HyperframesRenderProvider()
    with patch("showrunner.providers.render.hyperframes.subprocess.run",
               side_effect=FileNotFoundError("npx")):
        with pytest.raises(RuntimeError, match="Node"):
            provider.render(work_dir=tmp_path, output_path=Path("o.mp4"))
