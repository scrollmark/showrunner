"""Tests for `showrunner tts` — narration synthesis into a project."""

import json
from pathlib import Path

from click.testing import CliRunner

from showrunner.cli.main import cli
from showrunner.project import ProjectManifest
from showrunner.providers.tts.base import AudioFile


class FakeTTS:
    def __init__(self, duration=3.0):
        self.duration = duration
        self.calls = []

    def synthesize(self, text, *, output_path, voice, speed=1.0):
        self.calls.append({"text": text, "voice": voice, "speed": speed})
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"RIFFfake")
        return AudioFile(path=Path(output_path), duration=self.duration)

    def list_voices(self):
        return []


def _project(tmp_path, scenes=None):
    project = tmp_path / "proj"
    (project / "public" / "audio").mkdir(parents=True)
    ProjectManifest(
        name="proj", workflow="explainer", runtime="remotion", style="3b1b-dark",
        voice="af_heart", speed=1.0,
    ).save(project)
    scenes = scenes or [
        {"id": "hook", "duration": 4, "narration": "Hello.", "visual": "v"},
        {"id": "body", "duration": 8, "narration": "World.", "visual": "v"},
    ]
    (project / "storyboard.json").write_text(json.dumps({
        "title": "T", "totalDuration": sum(s["duration"] for s in scenes),
        "scenes": scenes,
    }))
    return project


def test_tts_writes_wavs_and_narration_json(tmp_path, monkeypatch):
    fake = FakeTTS(duration=3.0)
    monkeypatch.setattr(
        "showrunner.providers.factory.create_tts", lambda name, cfg: fake
    )
    project = _project(tmp_path)
    result = CliRunner().invoke(cli, ["tts", str(project)])
    assert result.exit_code == 0, result.output

    assert (project / "public" / "audio" / "hook.wav").exists()
    narration = json.loads((project / "narration.json").read_text())
    assert narration["hook"]["duration"] == 3.0
    assert narration["hook"]["path"] == "public/audio/hook.wav"
    assert [c["voice"] for c in fake.calls] == ["af_heart", "af_heart"]


def test_tts_stretches_scene_when_audio_longer(tmp_path, monkeypatch):
    fake = FakeTTS(duration=9.4)  # longer than the 4s hook scene
    monkeypatch.setattr(
        "showrunner.providers.factory.create_tts", lambda name, cfg: fake
    )
    project = _project(tmp_path)
    result = CliRunner().invoke(cli, ["tts", str(project)])
    assert result.exit_code == 0, result.output

    sb = json.loads((project / "storyboard.json").read_text())
    hook = next(s for s in sb["scenes"] if s["id"] == "hook")
    assert hook["duration"] == 11  # ceil(9.4) + 1 breathing-room second
    assert sb["totalDuration"] == sum(s["duration"] for s in sb["scenes"])


def test_tts_requires_storyboard(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    ProjectManifest(
        name="proj", workflow="explainer", runtime="remotion", style="3b1b-dark"
    ).save(project)
    result = CliRunner().invoke(cli, ["tts", str(project)])
    assert result.exit_code != 0
    assert "storyboard.json" in result.output
