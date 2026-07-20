"""Caption timing sources + work_dir I/O.

Preference order (see `generate_scene_captions`):
1. TTS-provider word timings — exact alignment, zero extra cost.
2. Whisper transcription via `faster-whisper` (optional dep,
   `pip install showrunner[captions]`).
3. Proportional estimation from narration text and audio duration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from showrunner.captions.model import Caption
from showrunner.providers.tts.base import WordTiming


def captions_from_word_timings(timings: list[WordTiming]) -> list[Caption]:
    """Convert TTS/whisper word timings (seconds) to Caption objects (ms)."""
    captions: list[Caption] = []
    for t in timings:
        word = (t.word or "").strip()
        if not word:
            continue
        start_ms = int(round(t.start * 1000))
        end_ms = int(round(t.end * 1000))
        if end_ms < start_ms:
            end_ms = start_ms
        captions.append(Caption(text=word, start_ms=start_ms, end_ms=end_ms))
    return captions


def estimate_captions(text: str, duration: float) -> list[Caption]:
    """Distribute narration words across the audio duration.

    Each word's slice is proportional to its character length (+1 for the
    trailing space) — a rough but serviceable stand-in when neither TTS
    timings nor whisper are available.
    """
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    if not words or duration <= 0:
        return []
    total_ms = duration * 1000.0
    weights = [len(w) + 1 for w in words]
    total_weight = sum(weights)
    captions: list[Caption] = []
    cursor = 0.0
    for word, weight in zip(words, weights):
        span = total_ms * weight / total_weight
        start_ms = int(round(cursor))
        end_ms = int(round(cursor + span))
        captions.append(Caption(text=word, start_ms=start_ms, end_ms=end_ms))
        cursor += span
    # Snap the final word to the exact audio end.
    captions[-1].end_ms = int(round(total_ms))
    return captions


def transcribe_word_timings(
    audio_path: Path, *, model_size: str = "base"
) -> list[WordTiming] | None:
    """Transcribe a WAV with faster-whisper for word-level timestamps.

    Returns None when the optional `faster-whisper` dependency is not
    installed, or when transcription yields nothing — callers fall back
    to estimation.
    """
    try:
        from faster_whisper import WhisperModel  # optional: showrunner[captions]
    except ImportError:
        return None

    model = WhisperModel(model_size, compute_type="int8")
    segments, _info = model.transcribe(str(audio_path), word_timestamps=True)
    timings: list[WordTiming] = []
    for segment in segments:
        for w in getattr(segment, "words", None) or []:
            word = (w.word or "").strip()
            if word:
                timings.append(WordTiming(word=word, start=float(w.start), end=float(w.end)))
    return timings or None


def generate_scene_captions(*, narration: str, audio) -> list[Caption]:
    """Produce word-level captions for one scene's narration audio.

    `audio` is an `AudioFile` (or anything with `.path`, `.duration`, and
    optionally `.word_timings`).
    """
    timings = getattr(audio, "word_timings", None)
    if isinstance(timings, list) and timings:
        captions = captions_from_word_timings(timings)
        if captions:
            return captions

    audio_path = getattr(audio, "path", None)
    if audio_path is not None and Path(audio_path).exists():
        transcribed = transcribe_word_timings(Path(audio_path))
        if transcribed:
            captions = captions_from_word_timings(transcribed)
            if captions:
                return captions

    return estimate_captions(narration, float(getattr(audio, "duration", 0.0) or 0.0))


def write_scene_captions(captions_dir: Path, scene_id: str, captions: list[Caption]) -> Path:
    """Write `captions/{scene_id}.json` (the work_dir contract file)."""
    captions_dir = Path(captions_dir)
    captions_dir.mkdir(parents=True, exist_ok=True)
    target = captions_dir / f"{scene_id}.json"
    target.write_text(json.dumps([c.to_dict() for c in captions], indent=2), encoding="utf-8")
    return target


def load_all_captions(captions_dir: Path) -> dict[str, list[Caption]]:
    """Load every `captions/{scene_id}.json` in a work_dir. Missing dir → {}."""
    captions_dir = Path(captions_dir)
    if not captions_dir.is_dir():
        return {}
    result: dict[str, list[Caption]] = {}
    for path in sorted(captions_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, list):
            result[path.stem] = [Caption.from_dict(d) for d in data if isinstance(d, dict)]
    return result
