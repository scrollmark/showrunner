# tests/test_pipeline_ai_video.py
from unittest.mock import patch, MagicMock
from showrunner.pipeline import Pipeline
from showrunner.plan import Plan


def test_create_providers_with_video_and_ffmpeg():
    pipeline = Pipeline()
    providers = pipeline._create_providers(
        llm_name="anthropic",
        tts_name="kokoro",
        render_name="ffmpeg",
        provider_config={"minimax": {"api_key": "test"}},
        video_name="minimax",
    )
    assert "llm" in providers
    assert "tts" in providers
    assert "render" in providers
    assert "video" in providers


def test_pipeline_dry_run_ai_video():
    with patch("showrunner.pipeline.get_registry") as mock_reg_fn:
        mock_fmt = MagicMock()
        mock_fmt.preferred_render_provider = "ffmpeg"
        mock_fmt.requires_video_provider = True
        mock_fmt.plan.return_value = Plan(title="AI Test", total_duration=10, scenes=[])
        mock_reg = MagicMock()
        mock_reg.get.return_value = mock_fmt
        mock_reg_fn.return_value = mock_reg

        pipeline = Pipeline(format_name="ai-video")
        result = pipeline.run("Ocean mysteries", dry_run=True)
        assert isinstance(result, Plan)
        assert result.title == "AI Test"
