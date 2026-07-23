# tests/test_video_minimax.py
from unittest.mock import MagicMock, patch

from showrunner.providers.video.base import VideoProvider
from showrunner.providers.video.minimax import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_RESOLUTION,
    MinimaxVideoProvider,
    quantize_duration,
)


def _bare_provider() -> MinimaxVideoProvider:
    provider = MinimaxVideoProvider.__new__(MinimaxVideoProvider)
    provider._api_key = "test_key"
    provider._model = DEFAULT_MODEL
    provider._resolution = DEFAULT_RESOLUTION
    provider._base_url = DEFAULT_BASE_URL
    return provider


def test_minimax_is_video_provider():
    assert issubclass(MinimaxVideoProvider, VideoProvider)


def test_defaults_target_hailuo_on_current_host():
    provider = MinimaxVideoProvider(api_key="k")
    assert provider._model == "MiniMax-Hailuo-02"
    assert provider._resolution == "1080P"
    assert provider._base_url == "https://api.minimax.io/v1"


def test_quantize_duration_maps_to_api_lengths():
    # Hailuo generates 6s or 10s clips only; compose trims back down.
    assert quantize_duration(3) == 6
    assert quantize_duration(5) == 6
    assert quantize_duration(6) == 6
    assert quantize_duration(7) == 10
    assert quantize_duration(10) == 10
    assert quantize_duration(30) == 10  # capped at the API max


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

    provider = _bare_provider()

    output = tmp_path / "clip.mp4"
    result = provider.generate("A cat running", duration=5, aspect_ratio="16:9", output_path=output)
    assert result == output

    # The submit payload carries model + quantized duration + resolution —
    # a 5s scene request becomes a 6s Hailuo clip (compose trims it back).
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload == {
        "model": DEFAULT_MODEL,
        "prompt": "A cat running",
        "duration": 6,
        "resolution": DEFAULT_RESOLUTION,
    }
    # Usage accounts the seconds actually generated (and billed), not requested.
    assert provider.get_usage()["video_seconds"] == 6.0


@patch("showrunner.providers.video.minimax.httpx")
def test_poll_returns_status(mock_httpx):
    mock_client = MagicMock()
    mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)

    resp = MagicMock()
    resp.json.return_value = {"status": "Processing"}
    resp.raise_for_status = MagicMock()
    mock_client.get.return_value = resp

    provider = _bare_provider()

    status, url = provider.poll("task_123")
    assert status == "processing"
    assert url is None
