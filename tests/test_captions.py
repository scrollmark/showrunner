"""Word-level caption generation tests. All transcription is mocked."""

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from showrunner.captions import (
    Caption,
    captions_from_word_timings,
    estimate_captions,
    generate_scene_captions,
    group_into_pages,
    load_all_captions,
    transcribe_word_timings,
    write_scene_captions,
)
from showrunner.captions.ass import _ass_color, _ass_time, generate_ass
from showrunner.providers.tts.base import AudioFile, WordTiming


# --- Caption model ---


def test_caption_to_dict_camelcase():
    cap = Caption(text="hello", start_ms=100, end_ms=400)
    assert cap.to_dict() == {
        "text": "hello",
        "startMs": 100,
        "endMs": 400,
        "timestampMs": 250,  # midpoint when not set
    }


def test_caption_from_dict_accepts_camel_and_snake():
    camel = Caption.from_dict({"text": "a", "startMs": 10, "endMs": 20, "timestampMs": 15})
    snake = Caption.from_dict({"text": "a", "start_ms": 10, "end_ms": 20})
    assert camel.start_ms == snake.start_ms == 10
    assert camel.timestamp_ms == 15
    assert snake.timestamp_ms is None


# --- Timing sources ---


def test_captions_from_word_timings():
    timings = [
        WordTiming(word=" Hello ", start=0.1, end=0.4),
        WordTiming(word="world", start=0.5, end=0.9),
        WordTiming(word="   ", start=1.0, end=1.1),  # whitespace dropped
    ]
    caps = captions_from_word_timings(timings)
    assert [c.text for c in caps] == ["Hello", "world"]
    assert caps[0].start_ms == 100
    assert caps[0].end_ms == 400
    assert caps[1].start_ms == 500


def test_estimate_captions_covers_duration():
    caps = estimate_captions("one two three four", 4.0)
    assert len(caps) == 4
    assert caps[0].start_ms == 0
    assert caps[-1].end_ms == 4000
    # Monotonic, contiguous
    for prev, nxt in zip(caps, caps[1:]):
        assert prev.end_ms == nxt.start_ms
        assert prev.start_ms < prev.end_ms


def test_estimate_captions_empty():
    assert estimate_captions("", 5.0) == []
    assert estimate_captions("hi", 0.0) == []


def test_transcribe_returns_none_without_faster_whisper(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import → ImportError
    assert transcribe_word_timings("/nonexistent.wav") is None


def _install_fake_whisper(monkeypatch, words):
    module = types.ModuleType("faster_whisper")

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, path, word_timestamps=True):
            segment = SimpleNamespace(words=[SimpleNamespace(**w) for w in words])
            return [segment], SimpleNamespace()

    module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)


def test_transcribe_with_mocked_whisper(monkeypatch, tmp_path):
    _install_fake_whisper(
        monkeypatch,
        [
            {"word": " Hello", "start": 0.0, "end": 0.3},
            {"word": " world", "start": 0.3, "end": 0.7},
        ],
    )
    timings = transcribe_word_timings(tmp_path / "a.wav")
    assert [t.word for t in timings] == ["Hello", "world"]
    assert timings[1].end == 0.7


# --- Source preference in generate_scene_captions ---


def test_generate_scene_captions_prefers_tts_timings(tmp_path):
    audio = AudioFile(
        path=tmp_path / "s.wav",
        duration=1.0,
        word_timings=[WordTiming(word="exact", start=0.2, end=0.6)],
    )
    caps = generate_scene_captions(narration="exact", audio=audio)
    assert len(caps) == 1
    assert (caps[0].start_ms, caps[0].end_ms) == (200, 600)


def test_generate_scene_captions_whisper_fallback(monkeypatch, tmp_path):
    wav = tmp_path / "s.wav"
    wav.write_bytes(b"fake")
    _install_fake_whisper(monkeypatch, [{"word": "whispered", "start": 0.1, "end": 0.5}])
    audio = AudioFile(path=wav, duration=1.0, word_timings=None)
    caps = generate_scene_captions(narration="something else entirely", audio=audio)
    assert [c.text for c in caps] == ["whispered"]


def test_generate_scene_captions_estimates_when_nothing_available(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    wav = tmp_path / "s.wav"
    wav.write_bytes(b"fake")
    audio = AudioFile(path=wav, duration=2.0, word_timings=None)
    caps = generate_scene_captions(narration="hello there world", audio=audio)
    assert [c.text for c in caps] == ["hello", "there", "world"]
    assert caps[-1].end_ms == 2000


def test_generate_scene_captions_ignores_mock_word_timings(monkeypatch, tmp_path):
    # MagicMock audio (as used by existing tests) must not crash — a
    # MagicMock word_timings attribute is truthy but not a list.
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    audio = MagicMock(duration=1.0, path=tmp_path / "missing.wav")
    caps = generate_scene_captions(narration="ok", audio=audio)
    assert [c.text for c in caps] == ["ok"]


# --- work_dir contract I/O ---


def test_write_and_load_scene_captions(tmp_path):
    captions_dir = tmp_path / "captions"
    caps = [Caption(text="hi", start_ms=0, end_ms=300)]
    target = write_scene_captions(captions_dir, "hook", caps)
    assert target == captions_dir / "hook.json"
    data = json.loads(target.read_text())
    assert data == [{"text": "hi", "startMs": 0, "endMs": 300, "timestampMs": 150}]

    loaded = load_all_captions(captions_dir)
    assert list(loaded) == ["hook"]
    assert loaded["hook"][0].end_ms == 300


def test_load_all_captions_missing_dir(tmp_path):
    assert load_all_captions(tmp_path / "nope") == {}


# --- TikTok-style page grouping ---


def _word(text, start, end):
    return Caption(text=text, start_ms=start, end_ms=end)


def test_group_into_pages_max_words():
    caps = [_word(f"w{i}", i * 100, i * 100 + 90) for i in range(6)]
    pages = group_into_pages(caps, max_words=4)
    assert [len(p.tokens) for p in pages] == [4, 2]
    assert pages[0].start_ms == 0
    assert pages[0].end_ms == 390
    assert pages[1].tokens[0].text == "w4"


def test_group_into_pages_splits_on_gap():
    caps = [_word("a", 0, 200), _word("b", 1500, 1700)]  # 1300ms silence
    pages = group_into_pages(caps, max_gap_ms=600)
    assert len(pages) == 2


def test_group_into_pages_applies_offset():
    caps = [_word("a", 0, 200)]
    pages = group_into_pages(caps, offset_ms=5000)
    assert pages[0].start_ms == 5000
    assert pages[0].tokens[0].from_ms == 5000
    assert pages[0].tokens[0].to_ms == 5200


# --- ASS generation ---


def test_ass_color_conversion():
    assert _ass_color("#facc15") == "&H0015CCFA"
    assert _ass_color("bogus") == "&H00FFFFFF"


def test_ass_time_format():
    assert _ass_time(0) == "0:00:00.00"
    assert _ass_time(61230) == "0:01:01.23"


def test_generate_ass_karaoke():
    caps = [_word("Hello", 0, 300), _word("world", 300, 700)]
    pages = group_into_pages(caps)
    ass = generate_ass(
        pages,
        font_family="Fraunces",
        text_color="#ffffff",
        highlight_color="#facc15",
    )
    assert "Fraunces" in ass
    assert "&H0015CCFA" in ass  # highlight as PrimaryColour
    assert "{\\k30}Hello" in ass
    assert "{\\k40}world" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:00.70,Caption" in ass


def test_generate_ass_covers_leading_silence():
    caps = [_word("late", 500, 800)]
    pages = group_into_pages(caps)
    # Page starts at the word, so no gap tag needed — but with an offset
    # page the karaoke cursor must stay aligned.
    ass = generate_ass(pages)
    assert "{\\k30}late" in ass
