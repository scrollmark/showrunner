from showrunner.feedback import Feedback


def test_feedback_text_only():
    fb = Feedback(level="plan", text="Make the hook punchier")
    assert fb.level == "plan"
    assert fb.text == "Make the hook punchier"
    assert fb.scene_id is None


def test_feedback_scene_specific():
    fb = Feedback(level="asset", scene_id="hook", text="More animation")
    assert fb.scene_id == "hook"


def test_feedback_with_edits():
    fb = Feedback(level="plan", edits={"scenes": [{"id": "hook", "duration": 8}]})
    assert fb.edits is not None
