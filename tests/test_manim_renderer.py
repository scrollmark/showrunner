# tests/test_manim_renderer.py
"""Renderer tests use a stubbed `manim` invocation — no real Manim/LaTeX."""

import subprocess
from unittest.mock import patch

import pytest

from showrunner.formats.manim_explainer.renderer import (
    manim_available,
    render_scene,
)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_render_scene_success_moves_output(tmp_path):
    scene_file = tmp_path / "scenes" / "hook.py"
    scene_file.parent.mkdir()
    scene_file.write_text("from manim import *")
    media_dir = tmp_path / "media"
    output_path = tmp_path / "clips" / "hook.mp4"

    def fake_run(cmd, **kwargs):
        # Simulate manim writing into its nested media tree.
        produced = media_dir / "videos" / "hook" / "1920p30" / "hook.mp4"
        produced.parent.mkdir(parents=True, exist_ok=True)
        produced.write_bytes(b"fake mp4")
        return _completed(0)

    with patch("showrunner.formats.manim_explainer.renderer.subprocess.run", side_effect=fake_run) as mock_run:
        ok, error = render_scene(
            scene_file, "Hook", output_path,
            media_dir=media_dir, resolution=(1080, 1920),
        )

    assert ok is True
    assert error == ""
    assert output_path.exists()
    cmd = mock_run.call_args.args[0]
    assert cmd[:2] == ["manim", "render"]
    assert "Hook" == cmd[-1]
    assert str(scene_file) == cmd[-2]
    assert "1080,1920" in cmd  # resolution passed through
    assert "-qm" in cmd  # medium quality default


def test_render_scene_failure_returns_traceback(tmp_path):
    scene_file = tmp_path / "hook.py"
    scene_file.write_text("broken")

    with patch(
        "showrunner.formats.manim_explainer.renderer.subprocess.run",
        return_value=_completed(1, stderr="NameError: name 'Circle2' is not defined"),
    ):
        ok, error = render_scene(
            scene_file, "Hook", tmp_path / "hook.mp4", media_dir=tmp_path / "media",
        )

    assert ok is False
    assert "NameError" in error


def test_render_scene_success_but_no_output_is_failure(tmp_path):
    scene_file = tmp_path / "hook.py"
    scene_file.write_text("from manim import *")

    with patch(
        "showrunner.formats.manim_explainer.renderer.subprocess.run",
        return_value=_completed(0),
    ):
        ok, error = render_scene(
            scene_file, "Hook", tmp_path / "hook.mp4", media_dir=tmp_path / "media",
        )

    assert ok is False
    assert "no" in error and "hook.mp4" in error


def test_render_scene_missing_manim_raises_with_install_hint(tmp_path):
    scene_file = tmp_path / "hook.py"
    scene_file.write_text("from manim import *")

    with patch(
        "showrunner.formats.manim_explainer.renderer.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        with pytest.raises(RuntimeError, match=r"showrunner\[manim\]"):
            render_scene(
                scene_file, "Hook", tmp_path / "hook.mp4", media_dir=tmp_path / "media",
            )


def test_render_scene_timeout_is_soft_failure(tmp_path):
    scene_file = tmp_path / "hook.py"
    scene_file.write_text("from manim import *")

    with patch(
        "showrunner.formats.manim_explainer.renderer.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="manim", timeout=600),
    ):
        ok, error = render_scene(
            scene_file, "Hook", tmp_path / "hook.mp4", media_dir=tmp_path / "media",
        )

    assert ok is False
    assert "timed out" in error


def test_manim_available_checks_path():
    with patch("showrunner.formats.manim_explainer.renderer.shutil.which", return_value=None):
        assert manim_available() is False
    with patch("showrunner.formats.manim_explainer.renderer.shutil.which", return_value="/usr/bin/manim"):
        assert manim_available() is True
