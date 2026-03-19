# tests/test_video_minimax.py
import json
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

from showrunner.providers.video.minimax import MinimaxVideoProvider
from showrunner.providers.video.base import VideoProvider


def test_minimax_is_video_provider():
    assert issubclass(MinimaxVideoProvider, VideoProvider)


@patch("showrunner.providers.video.minimax.httpx")
def test_generate_submits_and_polls(mock_httpx, tmp_path):
    mock_client = MagicMock()
    mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)

    # Submit response
    submit_resp = MagicMock()
    submit_resp.json.return_value = {"task_id": "task_123"}
    submit_resp.raise_for_status = MagicMock()

    # Poll response — completed
    poll_resp = MagicMock()
    poll_resp.json.return_value = {
        "status": "Success",
        "file_id": "file_456",
    }
    poll_resp.raise_for_status = MagicMock()

    # Download response
    download_resp = MagicMock()
    download_resp.json.return_value = {
        "file": {"download_url": "https://example.com/video.mp4"},
    }
    download_resp.raise_for_status = MagicMock()

    # Stream download
    stream_ctx = MagicMock()
    stream_resp = MagicMock()
    stream_resp.iter_bytes = MagicMock(return_value=[b"fake_video_data"])
    stream_ctx.__enter__ = MagicMock(return_value=stream_resp)
    stream_ctx.__exit__ = MagicMock(return_value=False)
    mock_client.stream.return_value = stream_ctx

    mock_client.post.side_effect = [submit_resp]
    mock_client.get.side_effect = [poll_resp, download_resp]

    provider = MinimaxVideoProvider.__new__(MinimaxVideoProvider)
    provider._api_key = "test_key"
    provider._model = "video-01-live2d"
    provider._base_url = "https://api.minimaxi.chat/v1"

    output = tmp_path / "clip.mp4"
    result = provider.generate("A cat running", duration=5, aspect_ratio="16:9", output_path=output)
    assert result == output


@patch("showrunner.providers.video.minimax.httpx")
def test_poll_returns_status(mock_httpx):
    mock_client = MagicMock()
    mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)

    resp = MagicMock()
    resp.json.return_value = {"status": "Processing"}
    resp.raise_for_status = MagicMock()
    mock_client.get.return_value = resp

    provider = MinimaxVideoProvider.__new__(MinimaxVideoProvider)
    provider._api_key = "test_key"
    provider._base_url = "https://api.minimaxi.chat/v1"

    status, url = provider.poll("task_123")
    assert status == "processing"
    assert url is None
