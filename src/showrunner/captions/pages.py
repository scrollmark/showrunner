"""TikTok-style word grouping — captions → short multi-word pages.

Mirrors what `createTikTokStyleCaptions()` does in `@remotion/captions`:
words are chunked into pages of a few words each; the on-screen component
shows one page at a time and highlights the currently-spoken word.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from showrunner.captions.model import Caption


@dataclass
class CaptionToken:
    """One word inside a page, with absolute (composition) times."""

    text: str
    from_ms: int
    to_ms: int

    def to_dict(self) -> dict:
        return {"text": self.text, "fromMs": self.from_ms, "toMs": self.to_ms}


@dataclass
class CaptionPage:
    """A group of words shown together."""

    start_ms: int
    end_ms: int
    tokens: list[CaptionToken] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "tokens": [t.to_dict() for t in self.tokens],
        }


def group_into_pages(
    captions: list[Caption],
    *,
    offset_ms: int = 0,
    max_words: int = 4,
    max_duration_ms: int = 1800,
    max_gap_ms: int = 600,
) -> list[CaptionPage]:
    """Group word captions into TikTok-style pages.

    A new page starts when the current one is full (`max_words`), has run
    long (`max_duration_ms`), or a silence gap larger than `max_gap_ms`
    separates two words. `offset_ms` shifts all times onto the composition
    timeline (scene start offset).
    """
    pages: list[CaptionPage] = []
    current: CaptionPage | None = None

    for cap in captions:
        from_ms = cap.start_ms + offset_ms
        to_ms = max(cap.end_ms + offset_ms, from_ms)
        needs_new_page = (
            current is None
            or len(current.tokens) >= max_words
            or (to_ms - current.start_ms) > max_duration_ms
            or (from_ms - current.tokens[-1].to_ms) > max_gap_ms
        )
        if needs_new_page:
            if current is not None:
                pages.append(current)
            current = CaptionPage(start_ms=from_ms, end_ms=to_ms)
        current.tokens.append(CaptionToken(text=cap.text, from_ms=from_ms, to_ms=to_ms))
        current.end_ms = to_ms

    if current is not None:
        pages.append(current)
    return pages


def pages_to_dicts(pages: list[CaptionPage]) -> list[dict]:
    return [p.to_dict() for p in pages]
