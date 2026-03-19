"""Kokoro local TTS provider (free, Apache 2.0)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from showrunner.providers.tts.base import AudioFile, TTSProvider

VOICES = [
    {"id": "af_heart", "name": "Heart (Female, American)", "description": "Default warm female voice"},
    {"id": "af_bella", "name": "Bella (Female, American)", "description": "Bright female voice"},
    {"id": "af_nicole", "name": "Nicole (Female, American)", "description": "Calm female voice"},
    {"id": "af_sarah", "name": "Sarah (Female, American)", "description": "Clear female voice"},
    {"id": "am_adam", "name": "Adam (Male, American)", "description": "Deep male voice"},
    {"id": "am_michael", "name": "Michael (Male, American)", "description": "Warm male voice"},
    {"id": "bf_emma", "name": "Emma (Female, British)", "description": "British female voice"},
    {"id": "bm_george", "name": "George (Male, British)", "description": "British male voice"},
]

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from kokoro import KPipeline
        _pipeline = KPipeline(lang_code="a")
    return _pipeline


class KokoroTTSProvider(TTSProvider):
    """Kokoro 82M — local, free TTS."""

    def synthesize(self, text: str, *, output_path: Path, voice: str = "af_heart", speed: float = 1.0) -> AudioFile:
        pipeline = _get_pipeline()
        sample_rate = 24000
        chunks = list(pipeline(text, voice=voice, speed=speed))
        if not chunks:
            raise RuntimeError(f"Kokoro returned no audio for: {text[:50]}...")
        audio_arrays = [chunk[2] for chunk in chunks if chunk[2] is not None]
        if not audio_arrays:
            raise RuntimeError(f"Kokoro returned empty audio for: {text[:50]}...")
        audio = np.concatenate(audio_arrays)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), audio, sample_rate)
        duration = len(audio) / sample_rate
        return AudioFile(path=output_path, duration=duration, sample_rate=sample_rate)

    def list_voices(self) -> list[dict[str, str]]:
        return list(VOICES)
