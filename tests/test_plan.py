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
