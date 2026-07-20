"""Word-level caption generation (TikTok-style).

Produces `captions/{scene_id}.json` files inside the work_dir using the
`Caption[]` shape from `@remotion/captions`:

    [{"text": "word", "startMs": 0, "endMs": 240, "timestampMs": 120}, ...]

Timing sources, in preference order:
1. TTS-provider word timings (`AudioFile.word_timings`) — exact, free.
2. Local whisper transcription (`faster-whisper`, optional dep) — accurate.
3. Proportional estimation from narration text + audio duration — always works.
"""

from showrunner.captions.model import Caption
from showrunner.captions.generate import (
    captions_from_word_timings,
    estimate_captions,
    generate_scene_captions,
    load_all_captions,
    transcribe_word_timings,
    write_scene_captions,
)
from showrunner.captions.pages import CaptionPage, CaptionToken, group_into_pages, pages_to_dicts

__all__ = [
    "Caption",
    "CaptionPage",
    "CaptionToken",
    "captions_from_word_timings",
    "estimate_captions",
    "generate_scene_captions",
    "group_into_pages",
    "load_all_captions",
    "pages_to_dicts",
    "transcribe_word_timings",
    "write_scene_captions",
]
