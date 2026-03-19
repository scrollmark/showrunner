from unittest.mock import MagicMock, patch

from showrunner.pipeline import Pipeline, _slugify
from showrunner.plan import Plan


def test_pipeline_init():
    pipeline = Pipeline(format_name="faceless-explainer")
    assert pipeline.format_name == "faceless-explainer"


def test_slugify():
    assert _slugify("Why Do Cats Purr?") == "why-do-cats-purr"
    assert _slugify("Hello World!") == "hello-world"


def test_pipeline_dry_run():
    with patch("showrunner.pipeline.get_registry") as mock_reg_fn:
        mock_fmt = MagicMock()
        mock_fmt.plan.return_value = Plan(title="Test", total_duration=10, scenes=[])
        mock_reg = MagicMock()
        mock_reg.get.return_value = mock_fmt
        mock_reg_fn.return_value = mock_reg

        pipeline = Pipeline(format_name="faceless-explainer")
        result = pipeline.run("Test topic", dry_run=True)

        assert isinstance(result, Plan)
        assert result.title == "Test"
        mock_fmt.plan.assert_called_once()


def test_create_providers_anthropic():
    pipeline = Pipeline()
    providers = pipeline._create_providers("anthropic", "kokoro", "remotion", {})
    assert "llm" in providers
    assert "tts" in providers
    assert "render" in providers


def test_create_providers_unknown_llm():
    pipeline = Pipeline()
    import pytest

    with pytest.raises(ValueError, match="Unknown LLM"):
        pipeline._create_providers("unknown", "kokoro", "remotion", {})
