"""Tests for the OTIO exporter."""

from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.plan import Plan, Scene

otio = pytest.importorskip("opentimelineio")
from showrunner.exporters import otio as otio_exporter  # noqa: E402


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00")


def _stub_ai_video_workdir(tmp_path: Path, plan: Plan) -> Path:
    for s in plan.scenes:
        _touch(tmp_path / "clips" / f"{s.id}.mp4")
        _touch(tmp_path / "audio" / f"{s.id}.wav")
    return tmp_path


def _make_plan() -> Plan:
    return Plan(
        title="My Video",
        total_duration=10,
        scenes=[
            Scene(id="hook", duration=4, narration="hi", visual="logo", transition="fade"),
            Scene(id="body", duration=6, narration="ok", visual="chart", transition="cut"),
        ],
    )


def test_plan_to_timeline_builds_expected_structure(tmp_path):
    plan = _make_plan()
    _stub_ai_video_workdir(tmp_path, plan)

    tl = otio_exporter.plan_to_timeline(plan, tmp_path, format_name="ai-video", fps=30)

    assert tl.name == "My Video"
    assert tl.metadata["showrunner"]["format"] == "ai-video"
    assert len(tl.tracks) == 2

    video_track, audio_track = tl.tracks[0], tl.tracks[1]
    assert video_track.kind == otio.schema.TrackKind.Video
    assert audio_track.kind == otio.schema.TrackKind.Audio

    video_clips = [c for c in video_track if isinstance(c, otio.schema.Clip)]
    assert [c.name for c in video_clips] == ["hook", "body"]
    assert video_clips[0].duration().value == 4 * 30
    assert video_clips[1].duration().value == 6 * 30

    # Per-clip narration metadata round-trips
    assert video_clips[0].metadata["showrunner"]["narration"] == "hi"


def test_plan_to_timeline_emits_transition_for_fade(tmp_path):
    plan = _make_plan()
    _stub_ai_video_workdir(tmp_path, plan)
    # Force a fade on the second scene so a Transition is emitted between them.
    plan.scenes[1].transition = "fade"

    tl = otio_exporter.plan_to_timeline(plan, tmp_path, format_name="ai-video", fps=30)
    transitions = [
        c for c in tl.tracks[0] if isinstance(c, otio.schema.Transition)
    ]
    assert len(transitions) == 1


def test_plan_to_timeline_skips_transition_on_cut(tmp_path):
    plan = _make_plan()
    _stub_ai_video_workdir(tmp_path, plan)
    # Both transitions are "cut"/first-scene → no Transition objects.
    plan.scenes[0].transition = "cut"
    plan.scenes[1].transition = "cut"

    tl = otio_exporter.plan_to_timeline(plan, tmp_path, format_name="ai-video", fps=30)
    transitions = [c for c in tl.tracks[0] if isinstance(c, otio.schema.Transition)]
    assert transitions == []


def test_plan_to_timeline_raises_on_missing_asset(tmp_path):
    plan = _make_plan()
    # Don't create any assets.
    with pytest.raises(FileNotFoundError):
        otio_exporter.plan_to_timeline(plan, tmp_path, format_name="ai-video")


def test_export_writes_otio_file_and_round_trips(tmp_path):
    plan = _make_plan()
    _stub_ai_video_workdir(tmp_path, plan)
    (tmp_path / "plan.json").write_text(plan.to_json(), encoding="utf-8")
    (tmp_path / "showrunner.json").write_text(
        '{"format": "ai-video", "aspect_ratio": "9:16"}', encoding="utf-8"
    )
    out = tmp_path / "timeline.otio"

    otio_exporter.export(tmp_path, out)

    assert out.exists()
    tl = otio.adapters.read_from_file(str(out))
    assert tl.name == "My Video"
    assert len([c for c in tl.tracks[0] if isinstance(c, otio.schema.Clip)]) == 2


def test_unknown_format_rejected(tmp_path):
    plan = _make_plan()
    with pytest.raises(ValueError):
        otio_exporter.plan_to_timeline(plan, tmp_path, format_name="bogus")
