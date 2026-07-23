# tests/test_ffmpeg_compose.py
"""Filtergraph-construction tests for the composite format's FFmpeg layer (E4).

Every filtergraph string here was hand-verified against a real ffmpeg
build (ffmpeg-full, libass/libfontconfig enabled) before being encoded
as an assertion — see the PR description for the manual verification
commands and pixel-level checks (chromakey transparency, hstack split
position, image-overlay duration bounding).
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from showrunner.providers.render.ffmpeg_compose import (
    build_overlay_filtergraph,
    build_stack_filtergraph,
    composite_scene,
)


# --- build_overlay_filtergraph -----------------------------------------------


def test_overlay_filtergraph_base_only():
    filter_complex, out_label = build_overlay_filtergraph(
        [{"id": "base", "role": "base"}], width=640, height=360,
    )
    assert filter_complex == (
        "[0:v]scale=640:360:force_original_aspect_ratio=increase,crop=640:360,setsar=1[base0]"
    )
    assert out_label == "base0"


def test_overlay_filtergraph_with_chromakey_layer():
    layers = [
        {"id": "base", "role": "base"},
        {"id": "speaker", "role": "chromakey", "rect": [0.5, 0.5, 0.5, 0.5], "key_color": "0x00FF00"},
    ]
    filter_complex, out_label = build_overlay_filtergraph(layers, width=1000, height=1000)
    assert filter_complex == (
        "[0:v]scale=1000:1000:force_original_aspect_ratio=increase,crop=1000:1000,setsar=1[base0];"
        "[1:v]chromakey=0x00FF00:0.1:0.2,scale=500:500[ov1];"
        "[base0][ov1]overlay=x=500:y=500[comp1]"
    )
    assert out_label == "comp1"


def test_overlay_filtergraph_with_pip_layer_default_rect():
    layers = [{"id": "base", "role": "base"}, {"id": "corner", "role": "pip"}]
    filter_complex, _ = build_overlay_filtergraph(layers, width=800, height=600)
    # No rect given → defaults to the full canvas.
    assert "[1:v]scale=800:600[ov1]" in filter_complex
    assert "overlay=x=0:y=0" in filter_complex


def test_overlay_filtergraph_with_image_layer_uses_same_overlay_path():
    layers = [
        {"id": "base", "role": "base"},
        {"id": "card", "role": "image", "rect": [0.1, 0.1, 0.5, 0.3]},
    ]
    filter_complex, _ = build_overlay_filtergraph(layers, width=1000, height=1000)
    assert "[1:v]scale=500:300[ov1]" in filter_complex
    assert "overlay=x=100:y=100" in filter_complex
    assert "chromakey" not in filter_complex


def test_overlay_filtergraph_stacks_multiple_layers_in_order():
    layers = [
        {"id": "base", "role": "base"},
        {"id": "a", "role": "pip", "rect": [0, 0, 0.5, 0.5]},
        {"id": "b", "role": "pip", "rect": [0.5, 0.5, 0.5, 0.5]},
    ]
    filter_complex, out_label = build_overlay_filtergraph(layers, width=1000, height=1000)
    assert "[base0][ov1]overlay=x=0:y=0[comp1]" in filter_complex
    assert "[comp1][ov2]overlay=x=500:y=500[comp2]" in filter_complex
    assert out_label == "comp2"


def test_overlay_filtergraph_requires_base_first():
    with pytest.raises(ValueError, match="base layer"):
        build_overlay_filtergraph([{"id": "a", "role": "pip"}], width=100, height=100)


def test_overlay_filtergraph_rejects_stack_role_mixed_in():
    with pytest.raises(ValueError, match="hstack"):
        build_overlay_filtergraph(
            [{"id": "base", "role": "base"}, {"id": "a", "role": "hstack"}],
            width=100, height=100,
        )


# --- build_stack_filtergraph --------------------------------------------------


def test_hstack_filtergraph_two_layers_with_labels():
    layers = [
        {"id": "left", "role": "hstack", "label": "@user1"},
        {"id": "right", "role": "hstack", "label": "@user2"},
    ]
    filter_complex, out_label = build_stack_filtergraph(layers, width=1000, height=800, direction="hstack")
    assert "[0:v]scale=500:800:force_original_aspect_ratio=increase,crop=500:800" in filter_complex
    assert "drawtext=font=Sans:text='@user1'" in filter_complex
    assert "drawtext=font=Sans:text='@user2'" in filter_complex
    assert "[seg0][seg1]hstack=inputs=2[stacked]" in filter_complex
    assert out_label == "stacked"


def test_vstack_filtergraph_splits_height_not_width():
    layers = [{"id": "top", "role": "vstack"}, {"id": "bottom", "role": "vstack"}]
    filter_complex, _ = build_stack_filtergraph(layers, width=1000, height=800, direction="vstack")
    assert "scale=1000:400:force_original_aspect_ratio=increase,crop=1000:400" in filter_complex
    assert "[seg0][seg1]vstack=inputs=2[stacked]" in filter_complex


def test_stack_filtergraph_no_label_omits_drawtext():
    layers = [{"id": "left", "role": "hstack"}, {"id": "right", "role": "hstack"}]
    filter_complex, _ = build_stack_filtergraph(layers, width=1000, height=800, direction="hstack")
    assert "drawtext" not in filter_complex


def test_stack_filtergraph_escapes_special_characters_in_label():
    layers = [
        {"id": "left", "role": "hstack", "label": "it's 5:00"},
        {"id": "right", "role": "hstack"},
    ]
    filter_complex, _ = build_stack_filtergraph(layers, width=1000, height=800, direction="hstack")
    assert "text='it\\'s 5\\:00'" in filter_complex


def test_stack_filtergraph_supports_three_or_more_layers():
    layers = [{"id": f"c{i}", "role": "hstack"} for i in range(3)]
    filter_complex, _ = build_stack_filtergraph(layers, width=900, height=600, direction="hstack")
    assert "scale=300:600" in filter_complex
    assert "[seg0][seg1][seg2]hstack=inputs=3[stacked]" in filter_complex


def test_stack_filtergraph_requires_at_least_two_layers():
    with pytest.raises(ValueError, match="at least 2"):
        build_stack_filtergraph([{"id": "a", "role": "hstack"}], width=100, height=100, direction="hstack")


def test_stack_filtergraph_rejects_bad_direction():
    with pytest.raises(ValueError, match="hstack.*vstack"):
        build_stack_filtergraph(
            [{"id": "a", "role": "hstack"}, {"id": "b", "role": "hstack"}],
            width=100, height=100, direction="diagonal",
        )


# --- composite_scene -----------------------------------------------------


def _fake_run_writes_output(calls):
    def fake_run(cmd, capture_output, text):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"composited")
        return MagicMock(returncode=0, stderr="")
    return fake_run


def test_composite_scene_overlay_mode_builds_expected_command(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", _fake_run_writes_output(calls))

    base = tmp_path / "base.mp4"
    overlay = tmp_path / "overlay.mp4"
    base.write_bytes(b"b")
    overlay.write_bytes(b"o")
    layer_specs = [
        {"id": "base", "role": "base"},
        {"id": "speaker", "role": "chromakey", "rect": [0.5, 0.5, 0.5, 0.5]},
    ]
    output = tmp_path / "out" / "scene.mp4"

    result = composite_scene(
        [base, overlay], layer_specs,
        output_path=output, width=640, height=360, duration=5.0,
    )

    assert result == output
    assert output.exists()
    (cmd,) = calls
    assert cmd[:5] == ["ffmpeg", "-y", "-i", str(base), "-i"]
    assert str(overlay) in cmd
    assert "-loop" not in cmd  # no image-role layer here
    assert cmd[cmd.index("-t") + 1] == "5.0"
    assert cmd[-1] == str(output)


def test_composite_scene_loops_image_role_inputs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", _fake_run_writes_output(calls))

    base = tmp_path / "base.mp4"
    card = tmp_path / "card.png"
    base.write_bytes(b"b")
    card.write_bytes(b"c")
    layer_specs = [{"id": "base", "role": "base"}, {"id": "card", "role": "image"}]

    composite_scene(
        [base, card], layer_specs,
        output_path=tmp_path / "scene.mp4", width=640, height=360, duration=3.0,
    )

    (cmd,) = calls
    # -loop 1 appears immediately before the image input, not the base input.
    card_idx = cmd.index(str(card))
    assert cmd[card_idx - 3] == "-loop"
    assert cmd[card_idx - 2] == "1"
    assert cmd[card_idx - 1] == "-i"
    base_idx = cmd.index(str(base))
    assert cmd[base_idx - 1] == "-i"  # no -loop before the base


def test_composite_scene_stack_mode(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", _fake_run_writes_output(calls))

    left = tmp_path / "left.mp4"
    right = tmp_path / "right.mp4"
    left.write_bytes(b"l")
    right.write_bytes(b"r")
    layer_specs = [
        {"id": "left", "role": "hstack", "label": "@a"},
        {"id": "right", "role": "hstack", "label": "@b"},
    ]

    composite_scene(
        [left, right], layer_specs,
        output_path=tmp_path / "scene.mp4", width=1000, height=800, duration=5.0,
    )
    (cmd,) = calls
    filter_complex = cmd[cmd.index("-filter_complex") + 1]
    assert "hstack=inputs=2" in filter_complex


def test_composite_scene_rejects_mixed_stack_and_overlay_roles(tmp_path):
    layer_specs = [{"id": "base", "role": "base"}, {"id": "a", "role": "hstack"}]
    with pytest.raises(ValueError, match="not both"):
        composite_scene(
            [tmp_path / "a.mp4", tmp_path / "b.mp4"], layer_specs,
            output_path=tmp_path / "out.mp4", width=100, height=100, duration=1.0,
        )


def test_composite_scene_raises_with_ffmpeg_stderr_on_failure(tmp_path, monkeypatch):
    def fake_run(cmd, capture_output, text):
        return MagicMock(returncode=1, stderr="ffmpeg exploded")
    monkeypatch.setattr("subprocess.run", fake_run)

    layer_specs = [{"id": "base", "role": "base"}]
    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        composite_scene(
            [tmp_path / "a.mp4"], layer_specs,
            output_path=tmp_path / "out.mp4", width=100, height=100, duration=1.0,
        )
