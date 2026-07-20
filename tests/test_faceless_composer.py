from showrunner.formats.faceless_explainer.composer import generate_root_tsx
from showrunner.plan import Plan, Scene


def test_generate_root_tsx_basic():
    plan = Plan(
        title="Test", total_duration=15,
        scenes=[
            Scene(id="hook", duration=5, narration="N", visual="V", transition="fade"),
            Scene(id="main_point", duration=10, narration="N", visual="V", transition="slide-left"),
        ],
    )
    tsx = generate_root_tsx(plan, width=1080, height=1920, fps=30, has_audio=True)
    assert "import" in tsx
    assert "Hook" in tsx
    assert "MainPoint" in tsx
    assert "TransitionSeries" in tsx
    assert "linearTiming" in tsx
    # Second scene's `transition` determines the presentation between A and B.
    assert 'slide({ direction: "from-right" })' in tsx
    assert "Audio" in tsx
    assert 'id="main"' in tsx


def test_generate_root_tsx_no_audio():
    plan = Plan(title="Test", total_duration=5, scenes=[Scene(id="hook", duration=5, narration="N", visual="V")])
    tsx = generate_root_tsx(plan, width=1080, height=1920, fps=30, has_audio=False)
    assert "Hook" in tsx
    # No Audio elements rendered when has_audio=False
    assert "<Audio" not in tsx


def test_generate_root_tsx_with_captions():
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    tsx = generate_root_tsx(plan, width=1080, height=1920, fps=30, has_audio=True, captions=True)
    assert "CaptionOverlay" in tsx


def test_generate_root_tsx_with_watermark():
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    tsx = generate_root_tsx(plan, width=1080, height=1920, fps=30, has_audio=False, watermark="@mychannel")
    assert "@mychannel" in tsx


def test_generate_root_tsx_with_music():
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    tsx = generate_root_tsx(
        plan, width=1080, height=1920, fps=30, has_audio=False,
        music={"filename": "warm-editorial.mp3", "volume": 0.18, "track_id": "warm-01"},
    )
    assert 'staticFile("music/warm-editorial.mp3")' in tsx
    assert "volume={0.18}" in tsx


def test_generate_root_tsx_without_music_emits_no_music_audio():
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    tsx = generate_root_tsx(plan, width=1080, height=1920, fps=30, has_audio=False, music=None)
    assert 'staticFile("music/' not in tsx


def test_audio_frame_offsets_follow_compressed_timeline():
    """Audio tracks the transition-compressed visual timeline so
    narration stays in sync with scene visuals and doesn't trail past
    the last scene's visual end."""
    plan = Plan(
        title="Test", total_duration=20,
        scenes=[
            Scene(id="a", duration=5, narration="N", visual="V"),
            Scene(id="b", duration=5, narration="N", visual="V"),
            Scene(id="c", duration=10, narration="N", visual="V"),
        ],
    )
    tsx = generate_root_tsx(plan, width=1080, height=1920, fps=30, has_audio=True)
    # Default transition = 9 frames (no preset = 0.33s fallback @30fps).
    # Scene B's audio starts at 150 - 9 = 141; C at 141 + 150 - 9 = 282.
    assert "from={0}" in tsx
    assert "from={141}" in tsx
    assert "from={282}" in tsx


def test_visual_timeline_uses_transition_series():
    plan = Plan(
        title="Test", total_duration=15,
        scenes=[
            Scene(id="a", duration=5, narration="N", visual="V"),
            Scene(id="b", duration=5, narration="N", visual="V", transition="fade"),
            Scene(id="c", duration=5, narration="N", visual="V", transition="wipe"),
        ],
    )
    tsx = generate_root_tsx(plan, width=1080, height=1920, fps=30, has_audio=False)
    # Opening + closing tag for each of 3 scenes
    assert tsx.count("TransitionSeries.Sequence") == 6
    # Self-closing Transition element once per gap (2 gaps for 3 scenes)
    assert tsx.count("TransitionSeries.Transition") == 2
    assert "fade()" in tsx
    assert 'wipe({ direction: "from-right" })' in tsx


def test_captions_overlay_styled_from_preset():
    from showrunner.formats.faceless_explainer.composer import caption_style_from_preset
    from showrunner.styles.resolver import load_preset

    preset = load_preset("3b1b-dark")
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    tsx = generate_root_tsx(plan, width=1080, height=1920, fps=30, has_audio=True, captions=True, preset=preset)

    style = caption_style_from_preset(preset)
    assert style["font_family"] == "Inter"
    assert style["highlight_color"] == "#facc15"  # colors.accent
    assert style["text_color"] == "#ffffff"

    # Root.tsx consumes the generated caption pages and bakes in the preset styling.
    assert 'import { captionPages } from "./captions/captions.generated";' in tsx
    assert '"#facc15"' in tsx
    assert '"#ffffff"' in tsx
    assert 'fontFamily: "Inter"' in tsx
    assert "<CaptionOverlay />" in tsx


def test_no_captions_no_generated_import():
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=10, narration="N", visual="V")])
    tsx = generate_root_tsx(plan, width=1080, height=1920, fps=30, has_audio=True, captions=False)
    assert "captions.generated" not in tsx
    assert "CaptionOverlay" not in tsx


def test_compute_scene_start_frames_matches_compressed_timeline():
    from showrunner.formats.faceless_explainer.composer import compute_scene_start_frames

    plan = Plan(
        title="Test", total_duration=15,
        scenes=[
            Scene(id="a", duration=5, narration="N", visual="V"),
            Scene(id="b", duration=10, narration="N", visual="V"),
        ],
    )
    # No preset → legacy default of int(fps * 0.33) transition frames (9 at 30fps).
    offsets = compute_scene_start_frames(plan, None, 30)
    assert offsets["a"] == 0
    assert offsets["b"] == 5 * 30 - 9
