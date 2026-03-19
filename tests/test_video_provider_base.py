import pytest
from showrunner.providers.video.base import VideoProvider


def test_video_provider_is_abstract():
    with pytest.raises(TypeError):
        VideoProvider()


def test_video_provider_has_generate_method():
    assert hasattr(VideoProvider, "generate")


def test_video_provider_has_poll_method():
    assert hasattr(VideoProvider, "poll")
