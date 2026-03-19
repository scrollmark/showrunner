"""Tests for Gemini (Veo) video provider."""

from unittest.mock import MagicMock
from pathlib import Path

from showrunner.providers.video.gemini import GeminiVideoProvider
from showrunner.providers.video.base import VideoProvider


def test_gemini_is_video_provider():
    assert issubclass(GeminiVideoProvider, VideoProvider)


def test_generate_submits_and_polls(tmp_path):
    mock_client = MagicMock()

    # Operation that completes immediately
    mock_operation = MagicMock()
    mock_operation.done = True
    mock_operation.name = "op_123"
    mock_video = MagicMock()
    mock_operation.response.generated_videos = [mock_video]
    mock_client.models.generate_videos.return_value = mock_operation

    provider = GeminiVideoProvider.__new__(GeminiVideoProvider)
    provider._api_key = "test_key"
    provider._model = "veo-3.1-generate-preview"
    provider._client = mock_client

    output = tmp_path / "clip.mp4"
    result = provider.generate("A cat running", duration=5, aspect_ratio="16:9", output_path=output)
    assert result == output
    mock_client.models.generate_videos.assert_called_once()
    mock_client.files.download.assert_called_once()
    mock_video.video.save.assert_called_once_with(str(output))


def test_poll_returns_processing():
    mock_client = MagicMock()

    mock_operation = MagicMock()
    mock_operation.done = False
    mock_client.operations.get.return_value = mock_operation

    provider = GeminiVideoProvider.__new__(GeminiVideoProvider)
    provider._api_key = "test_key"
    provider._client = mock_client

    status, result = provider.poll("op_123")
    assert status == "processing"
    assert result is None


def test_poll_completed():
    mock_client = MagicMock()

    mock_operation = MagicMock()
    mock_operation.done = True
    mock_operation.response.generated_videos = [MagicMock()]
    mock_client.operations.get.return_value = mock_operation

    provider = GeminiVideoProvider.__new__(GeminiVideoProvider)
    provider._api_key = "test_key"
    provider._client = mock_client

    status, result = provider.poll("op_123")
    assert status == "completed"
    assert result == "op_123"
