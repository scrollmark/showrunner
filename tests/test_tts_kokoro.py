from unittest.mock import MagicMock, patch
import numpy as np

from showrunner.providers.tts.kokoro import KokoroTTSProvider, VOICES
from showrunner.providers.tts.base import TTSProvider


def test_kokoro_is_tts_provider():
    assert issubclass(KokoroTTSProvider, TTSProvider)


def test_list_voices():
    provider = KokoroTTSProvider.__new__(KokoroTTSProvider)
    voices = provider.list_voices()
    assert len(voices) == 8
    assert any(v["id"] == "af_heart" for v in voices)


@patch("showrunner.providers.tts.kokoro._get_pipeline")
def test_synthesize(mock_get_pipeline, tmp_path):
    mock_pipeline = MagicMock()
    mock_get_pipeline.return_value = mock_pipeline
    sample_rate = 24000
    fake_audio = np.zeros(int(sample_rate * 2.0), dtype=np.float32)
    mock_pipeline.return_value = [(None, None, fake_audio)]

    provider = KokoroTTSProvider.__new__(KokoroTTSProvider)
    output_path = tmp_path / "test.wav"
    result = provider.synthesize("Hello world", output_path=output_path, voice="af_heart")
    assert result.path == output_path
    assert output_path.exists()
    assert abs(result.duration - 2.0) < 0.1
