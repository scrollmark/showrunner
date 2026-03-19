"""Integration test — full pipeline with mocked providers."""

from unittest.mock import MagicMock, patch
from pathlib import Path

from showrunner.pipeline import Pipeline
from showrunner.plan import Plan, Scene


def test_full_pipeline_dry_run():
    """Dry run returns a Plan without rendering."""
    with patch("showrunner.pipeline.get_registry") as mock_reg_fn:
        mock_fmt = MagicMock()
        mock_fmt.name = "faceless-explainer"
        mock_fmt.required_providers = ["llm", "tts", "render"]
        mock_fmt.plan.return_value = Plan(
            title="Test Video", total_duration=15,
            scenes=[
                Scene(id="hook", duration=5, narration="Hello", visual="Title"),
                Scene(id="main", duration=10, narration="World", visual="Content"),
            ],
        )
        mock_reg = MagicMock()
        mock_reg.get.return_value = mock_fmt
        mock_reg_fn.return_value = mock_reg

        pipeline = Pipeline(format_name="faceless-explainer")
        result = pipeline.run("Test topic", dry_run=True)

        assert isinstance(result, Plan)
        assert result.title == "Test Video"
        assert len(result.scenes) == 2
        mock_fmt.plan.assert_called_once()
        mock_fmt.generate_assets.assert_not_called()


def test_pipeline_create_providers_all_types():
    """Test that all provider types can be instantiated."""
    pipeline = Pipeline()

    # Anthropic + Kokoro + Remotion (defaults)
    providers = pipeline._create_providers("anthropic", "kokoro", "remotion", {})
    assert "llm" in providers
    assert "tts" in providers
    assert "render" in providers

    # OpenAI variant
    providers2 = pipeline._create_providers("openai", "kokoro", "remotion", {})
    assert "llm" in providers2


def test_plan_json_roundtrip_complex():
    """Complex plan serialization roundtrip."""
    plan = Plan(
        title="Why Cats Purr: The Science",
        total_duration=60,
        scenes=[
            Scene(id="hook_question", duration=5, narration="Ever wondered why cats purr?", visual="Cat with sound waves emanating", transition="fade"),
            Scene(id="science_explained", duration=15, narration="It turns out cats have a special organ...", visual="Anatomy diagram", transition="slide-left"),
            Scene(id="key_insight", duration=10, narration="But here's the surprising part...", visual="Bar chart comparison", transition="zoom-in"),
            Scene(id="practical_tip", duration=10, narration="Next time your cat purrs...", visual="Person with cat illustration", transition="slide-up"),
            Scene(id="final_cta", duration=5, narration="Follow for more animal science!", visual="Subscribe animation", transition="fade"),
        ],
    )

    # Roundtrip through JSON
    json_str = plan.to_json()
    restored = Plan.from_json(json_str)
    assert restored.title == plan.title
    assert len(restored.scenes) == 5
    assert restored.scenes[2].transition == "zoom-in"
    assert restored.total_duration == 60

    # Roundtrip through dict (camelCase)
    d = plan.to_dict()
    assert d["totalDuration"] == 60
    assert d["scenes"][0]["id"] == "hook_question"
    restored2 = Plan.from_dict(d)
    assert restored2.title == plan.title
