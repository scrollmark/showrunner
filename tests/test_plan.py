import json
from showrunner.plan import Plan, Scene


def test_scene_creation():
    scene = Scene(id="hook", duration=5, narration="Welcome.", visual="Title card", transition="fade")
    assert scene.id == "hook"
    assert scene.duration == 5
    assert scene.transition == "fade"


def test_plan_creation():
    scenes = [
        Scene(id="hook", duration=5, narration="Hook", visual="Visual"),
        Scene(id="main", duration=10, narration="Main", visual="Visual"),
    ]
    plan = Plan(title="Test Video", total_duration=15, scenes=scenes)
    assert plan.title == "Test Video"
    assert len(plan.scenes) == 2


def test_plan_to_dict_roundtrip():
    scenes = [Scene(id="hook", duration=5, narration="Hook", visual="Visual", transition="fade")]
    plan = Plan(title="Test", total_duration=5, scenes=scenes)
    d = plan.to_dict()
    restored = Plan.from_dict(d)
    assert restored.title == plan.title
    assert restored.scenes[0].id == "hook"


def test_plan_to_json_roundtrip():
    scenes = [Scene(id="hook", duration=5, narration="Hook", visual="Visual")]
    plan = Plan(title="Test", total_duration=5, scenes=scenes)
    json_str = plan.to_json()
    restored = Plan.from_json(json_str)
    assert restored.title == "Test"


def test_plan_from_dict_camel_case():
    d = {
        "title": "Test",
        "totalDuration": 10,
        "scenes": [{"id": "hook", "duration": 5, "narration": "N", "visual": "V", "transition": "fade"}],
    }
    plan = Plan.from_dict(d)
    assert plan.total_duration == 10
    assert plan.scenes[0].transition == "fade"


def test_scene_voice_defaults_to_none():
    scene = Scene(id="hook", duration=5, narration="Hi", visual="V")
    assert scene.voice is None


def test_scene_voice_omitted_from_dict_when_unset():
    """Existing plan JSON without `voice` must stay byte-stable."""
    scene = Scene(id="hook", duration=5, narration="Hi", visual="V")
    plan = Plan(title="Test", total_duration=5, scenes=[scene])
    assert "voice" not in plan.to_dict()["scenes"][0]


def test_scene_voice_roundtrips_through_dict_and_json():
    scene = Scene(id="a", duration=5, narration="Hi", visual="V", voice="am_adam")
    plan = Plan(title="Test", total_duration=5, scenes=[scene])

    d = plan.to_dict()
    assert d["scenes"][0]["voice"] == "am_adam"
    assert Plan.from_dict(d).scenes[0].voice == "am_adam"
    assert Plan.from_json(plan.to_json()).scenes[0].voice == "am_adam"


def test_scene_layers_defaults_to_none():
    scene = Scene(id="hook", duration=5, narration="Hi", visual="V")
    assert scene.layers is None


def test_scene_layers_omitted_from_dict_when_unset():
    """Existing plan JSON without `layers` must stay byte-stable."""
    scene = Scene(id="hook", duration=5, narration="Hi", visual="V")
    plan = Plan(title="Test", total_duration=5, scenes=[scene])
    assert "layers" not in plan.to_dict()["scenes"][0]


def test_scene_layers_roundtrips_through_dict_and_json():
    layers = [
        {"id": "base", "role": "base", "source": "a prompt"},
        {"id": "speaker", "role": "chromakey", "source": "file:///tmp/x.mp4", "rect": [0.5, 0.5, 0.5, 0.5]},
    ]
    scene = Scene(id="a", duration=5, narration="Hi", visual="V", layers=layers)
    plan = Plan(title="Test", total_duration=5, scenes=[scene])

    d = plan.to_dict()
    assert d["scenes"][0]["layers"] == layers
    assert Plan.from_dict(d).scenes[0].layers == layers
    assert Plan.from_json(plan.to_json()).scenes[0].layers == layers
