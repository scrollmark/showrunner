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
    assert (work_dir / "public" / "audio").is_dir()


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
