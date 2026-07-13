"""Tests for the carousel-reel workflow's music/beat-alignment check."""

import json

from showrunner.checks import CHECKS, CheckContext
from showrunner.project import ProjectManifest
from showrunner.workflows import WorkflowSpec


def test_carousel_reel_workflow_spec():
    spec = WorkflowSpec.load("carousel-reel")
    assert spec.runtime == "hyperframes"
    stage_names = [s.name for s in spec.stages]
    assert stage_names == ["storyboard", "music", "composition", "render"]
    assert spec.stages[1].check == "music"
    assert spec.stages[2].check == "hyperframes"


def _ctx(tmp_path, music=None, index_html=None):
    project = tmp_path / "v"
    (project / "assets" / "audio").mkdir(parents=True)
    manifest = ProjectManifest(
        name="v", workflow="carousel-reel", runtime="hyperframes", style="3b1b-dark",
    )
    manifest.save(project)
    if music is not None:
        (project / "music.json").write_text(json.dumps(music))
    if index_html is not None:
        (project / "index.html").write_text(index_html)
    return CheckContext(
        project_dir=project, manifest=manifest,
        spec=WorkflowSpec.load("carousel-reel"), storyboard={"scenes": []},
    )


def _music(tmp_path_project_relative_track="assets/audio/bed.wav"):
    return {
        "track": tmp_path_project_relative_track,
        "bpm": 120.0,
        "beats": [round(i * 0.5, 4) for i in range(40)],
        "volume": 0.8,
    }


def test_music_check_requires_music_json(tmp_path):
    ctx = _ctx(tmp_path)
    findings = CHECKS["music"](ctx)
    assert any(f.code == "missing-music" for f in findings)


def test_music_check_requires_track_file(tmp_path):
    ctx = _ctx(tmp_path, music=_music())
    findings = CHECKS["music"](ctx)
    assert any(f.code == "missing-track" for f in findings)


def test_music_check_passes_with_aligned_clips(tmp_path):
    html = '''<div data-composition-id="main" data-duration="10">
      <div class="clip" data-start="0" data-duration="2"></div>
      <div class="clip" data-start="2.0" data-duration="2"></div>
      <div class="clip" data-start="4.5" data-duration="2"></div>
    </div>'''
    ctx = _ctx(tmp_path, music=_music(), index_html=html)
    (ctx.project_dir / "assets" / "audio" / "bed.wav").write_bytes(b"RIFF")
    findings = CHECKS["music"](ctx)
    assert findings == []


def test_music_check_flags_offbeat_clip(tmp_path):
    html = '''<div data-composition-id="main" data-duration="10">
      <div class="clip" data-start="0" data-duration="2"></div>
      <div class="clip" data-start="2.27" data-duration="2"></div>
    </div>'''
    ctx = _ctx(tmp_path, music=_music(), index_html=html)
    (ctx.project_dir / "assets" / "audio" / "bed.wav").write_bytes(b"RIFF")
    findings = CHECKS["music"](ctx)
    assert any(f.code == "beat-misaligned" and "2.27" in f.message for f in findings)


def test_music_check_skips_alignment_before_composition_exists(tmp_path):
    ctx = _ctx(tmp_path, music=_music())
    (ctx.project_dir / "assets" / "audio" / "bed.wav").write_bytes(b"RIFF")
    findings = CHECKS["music"](ctx)
    assert findings == []
