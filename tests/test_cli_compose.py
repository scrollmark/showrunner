"""Tests for `showrunner compose` — Root.tsx generation from project state."""

import json

from click.testing import CliRunner

from showrunner.cli.main import cli
from showrunner.project import ProjectManifest


def _project(tmp_path, with_narration=True):
    project = tmp_path / "proj"
    (project / "src").mkdir(parents=True)
    (project / "public" / "audio").mkdir(parents=True)
    ProjectManifest(
        name="proj", workflow="explainer", runtime="remotion", style="3b1b-dark",
        aspect_ratio="9:16",
    ).save(project)
    scenes = [
        {"id": "hook", "duration": 4, "narration": "a", "visual": "v", "transition": "fade"},
        {"id": "final_cta", "duration": 8, "narration": "b", "visual": "v",
         "transition": "slide-up"},
    ]
    (project / "storyboard.json").write_text(json.dumps({
        "title": "T", "totalDuration": 12, "scenes": scenes,
    }))
    if with_narration:
        narration = {}
        for s in scenes:
            (project / "public" / "audio" / f"{s['id']}.wav").write_bytes(b"RIFF")
            narration[s["id"]] = {
                "duration": 3.0, "path": f"public/audio/{s['id']}.wav",
            }
        (project / "narration.json").write_text(json.dumps(narration))
    return project


def test_compose_writes_root_tsx(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWRUNNER_MUSIC_DIR", str(tmp_path / "no-catalog"))
    project = _project(tmp_path)
    result = CliRunner().invoke(cli, ["compose", str(project), "--music", "none"])
    assert result.exit_code == 0, result.output

    root = (project / "src" / "Root.tsx").read_text()
    assert 'import Hook from "./scenes/Hook"' in root
    assert 'import FinalCta from "./scenes/FinalCta"' in root
    assert 'staticFile("audio/hook.wav")' in root
    assert "TransitionSeries" in root
    assert "width={1080}" in root and "height={1920}" in root


def test_compose_with_watermark(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWRUNNER_MUSIC_DIR", str(tmp_path / "no-catalog"))
    project = _project(tmp_path)
    result = CliRunner().invoke(
        cli, ["compose", str(project), "--music", "none", "--watermark", "@myhandle"]
    )
    assert result.exit_code == 0, result.output
    assert "@myhandle" in (project / "src" / "Root.tsx").read_text()


def test_compose_requires_narration(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWRUNNER_MUSIC_DIR", str(tmp_path / "no-catalog"))
    project = _project(tmp_path, with_narration=False)
    result = CliRunner().invoke(cli, ["compose", str(project)])
    assert result.exit_code != 0
    assert "tts" in result.output
