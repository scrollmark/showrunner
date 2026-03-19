"""ElevenLabs cloud TTS provider."""

from __future__ import annotations

import wave
from pathlib import Path

from showrunner.providers.tts.base import AudioFile, TTSProvider


class ElevenLabsTTSProvider(TTSProvider):
    """ElevenLabs — high-quality cloud TTS."""

    def __init__(self, api_key: str | None = None, model: str = "eleven_multilingual_v2"):
        from elevenlabs import ElevenLabs

        self._client = ElevenLabs(api_key=api_key) if api_key else ElevenLabs()
        self._model = model

    def synthesize(self, text: str, *, output_path: Path, voice: str = "Rachel", speed: float = 1.0) -> AudioFile:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        audio_iter = self._client.text_to_speech.convert(text=text, voice_id=voice, model_id=self._model)
        with open(output_path, "wb") as f:
            for chunk in audio_iter:
                f.write(chunk)
        duration = _wav_duration(output_path)
        return AudioFile(path=output_path, duration=duration, sample_rate=24000)

    def list_voices(self) -> list[dict[str, str]]:
        return [
            {"id": "Rachel", "name": "Rachel", "description": "Default female voice"},
            {"id": "Adam", "name": "Adam", "description": "Default male voice"},
        ]


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / rate if rate > 0 else 0.0
