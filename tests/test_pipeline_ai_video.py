# tests/test_pipeline_ai_video.py
from unittest.mock import patch, MagicMock
from showrunner.pipeline import Pipeline
from showrunner.plan import Plan, Scene


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


def test_no_audio_still_calls_generate_assets_for_video_provider_formats(tmp_path):
    """E5: a format that requires a video provider (ai-video) still needs
    generate_assets() to run its clips under --no-audio — only formats with
    no external video provider (nothing to generate without audio) get the
    cheap stub. Regression guard for the plain `if not no_audio` short-
    circuit that used to skip clip generation entirely."""
    plan = Plan(
        title="ASMR", total_duration=5,
        scenes=[Scene(id="tap", duration=5, narration="", visual="Macro tapping")],
    )
    mock_fmt = MagicMock()
    mock_fmt.preferred_render_provider = "ffmpeg"
    mock_fmt.requires_video_provider = True
    mock_fmt.generate_assets.return_value = {"clips": {}, "durations": {}, "has_audio": False}

    mock_reg = MagicMock()
    mock_reg.get.return_value = mock_fmt
    out = tmp_path / "out.mp4"
    render = MagicMock()
    render.render.return_value = out

    with patch("showrunner.pipeline.get_registry", return_value=mock_reg), \
         patch.object(Pipeline, "_create_providers",
                      return_value={"llm": MagicMock(), "tts": MagicMock(), "render": render}), \
         patch.object(Pipeline, "_resolve_music", return_value=None):
        pipeline = Pipeline(format_name="ai-video")
        result = pipeline.run("Ocean mysteries", plan=plan, no_audio=True, output_path=out)

    assert result == out
    mock_fmt.generate_assets.assert_called_once()
