import io
import wave
from unittest.mock import MagicMock, patch
from showrunner.providers.tts.elevenlabs import ElevenLabsTTSProvider
from showrunner.providers.tts.base import TTSProvider


def test_elevenlabs_is_tts_provider():
    assert issubclass(ElevenLabsTTSProvider, TTSProvider)


def test_synthesize(tmp_path):
    mock_client = MagicMock()

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(b"\x00\x00" * 24000)
    wav_bytes = buf.getvalue()
    mock_client.text_to_speech.convert.return_value = iter([wav_bytes])

    provider = ElevenLabsTTSProvider.__new__(ElevenLabsTTSProvider)
    provider._client = mock_client
    provider._model = "eleven_multilingual_v2"

    output_path = tmp_path / "test.wav"
    result = provider.synthesize("Hello", output_path=output_path, voice="Rachel")
    assert result.path == output_path
    assert output_path.exists()
