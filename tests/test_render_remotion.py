import json
from unittest.mock import patch, MagicMock
from showrunner.providers.render.remotion import RemotionRenderProvider
from showrunner.providers.render.base import RenderProvider


def test_remotion_is_render_provider():
    assert issubclass(RemotionRenderProvider, RenderProvider)


@patch("showrunner.providers.render.remotion.subprocess")
def test_setup_creates_project(mock_subprocess, tmp_path):
    mock_subprocess.run.return_value = MagicMock(returncode=0)
    provider = RemotionRenderProvider()
    work_dir = tmp_path / "work"
    provider.setup(work_dir)
    assert (work_dir / "package.json").exists()
    assert (work_dir / "tsconfig.json").exists()
    assert (work_dir / "src" / "index.ts").exists()
    assert (work_dir / "src" / "scenes").is_dir()
    assert (work_dir / "src" / "tokens" / "schema.ts").exists()
    assert (work_dir / "src" / "tokens" / "easing.ts").exists()
    assert (work_dir / "src" / "tokens" / "typography.ts").exists()
    assert (work_dir / "src" / "tokens" / "index.ts").exists()
    assert (work_dir / "src" / "motion" / "useEnter.ts").exists()
    assert (work_dir / "src" / "motion" / "useExit.ts").exists()
    assert (work_dir / "src" / "motion" / "usePulse.ts").exists()
    assert (work_dir / "src" / "motion" / "useBeatSync.ts").exists()
    assert (work_dir / "src" / "motion" / "index.ts").exists()
    assert (work_dir / "public" / "audio").is_dir()


def test_write_preset_tokens_emits_typed_ts(tmp_path):
    provider = RemotionRenderProvider()
    preset = {
        "name": "bold-neon",
        "description": "x",
        "colors": {"background": "#000", "primary": "#fff", "secondary": "#888",
                   "accent": "#ff0", "text": "#fff", "textMuted": "#aaa"},
        "typography": {},
        "spacing": {"xs": 8, "sm": 16, "md": 32, "lg": 60, "xl": 120},
        "rhythm": {"bpm": 140, "beatsPerScene": 8, "transitionBeats": 0.5, "fps": 30},
        "motion": {"enterCurve": "out-expo", "exitCurve": "in-expo",
                   "pulseCurve": "overshoot", "transitionCurve": "in-out-expo"},
    }
    out = provider.write_preset_tokens(tmp_path, preset)
    assert out.exists()
    body = out.read_text()
    assert "export const preset: Preset" in body
    assert '"bold-neon"' in body
    assert '"bpm": 140' in body


@patch("showrunner.providers.render.remotion.subprocess")
def test_render_calls_remotion(mock_subprocess, tmp_path):
    mock_subprocess.run.return_value = MagicMock(returncode=0)
    provider = RemotionRenderProvider()
    output = tmp_path / "out.mp4"
    result = provider.render(work_dir=tmp_path, output_path=output)
    assert result == output
    mock_subprocess.run.assert_called_once()


@patch("showrunner.providers.render.remotion.subprocess")
def test_render_raises_on_failure(mock_subprocess, tmp_path):
    mock_subprocess.run.return_value = MagicMock(returncode=1, stderr="Error")
    provider = RemotionRenderProvider()
    import pytest
    with pytest.raises(RuntimeError, match="Remotion render failed"):
        provider.render(work_dir=tmp_path, output_path=tmp_path / "out.mp4")
