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
    assert "Sequence" in tsx
    assert "TransitionWrapper" in tsx
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


def test_frame_calculations():
    plan = Plan(
        title="Test", total_duration=20,
        scenes=[
            Scene(id="a", duration=5, narration="N", visual="V"),
            Scene(id="b", duration=5, narration="N", visual="V"),
            Scene(id="c", duration=10, narration="N", visual="V"),
        ],
    )
    tsx = generate_root_tsx(plan, width=1080, height=1920, fps=30, has_audio=False)
    # Scene A: from=0, 150 frames
    # Scene B: from=140 (150-10 overlap), 150 frames
    # Scene C: from=280, 300 frames
    assert "from={0}" in tsx
    assert "from={140}" in tsx
    assert "from={280}" in tsx
