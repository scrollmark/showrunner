import pytest
from showrunner.providers.llm.base import LLMProvider
from showrunner.providers.tts.base import TTSProvider, AudioFile
from showrunner.providers.render.base import RenderProvider


def test_llm_provider_is_abstract():
    with pytest.raises(TypeError):
        LLMProvider()


def test_tts_provider_is_abstract():
    with pytest.raises(TypeError):
        TTSProvider()


def test_render_provider_is_abstract():
    with pytest.raises(TypeError):
        RenderProvider()


def test_audio_file_creation(tmp_path):
    path = tmp_path / "test.wav"
    path.write_bytes(b"fake")
    af = AudioFile(path=path, duration=3.5, sample_rate=24000)
    assert af.duration == 3.5
