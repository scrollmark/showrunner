"""ASS subtitle generation for FFmpeg burn-in (ai-video format).

One Dialogue line per caption page, with `\\k` karaoke tags so the
currently-spoken word flips from the text color (SecondaryColour) to the
highlight color (PrimaryColour) — the same word-highlight behavior the
Remotion overlay provides for faceless-explainer.
"""

from __future__ import annotations

from showrunner.captions.pages import CaptionPage

_HEADER = """[Script Info]
Title: Showrunner captions
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font_family},{font_size},{highlight_color},{text_color},{outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_color(hex_color: str) -> str:
    """'#RRGGBB' → ASS '&H00BBGGRR' (BGR, leading alpha)."""
    value = (hex_color or "").lstrip("#")
    if len(value) != 6:
        value = "ffffff"
    r, g, b = value[0:2], value[2:4], value[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ass_time(ms: int) -> str:
    """Milliseconds → 'h:mm:ss.cc'."""
    ms = max(int(ms), 0)
    cs = round(ms / 10)
    s, cs = divmod(cs, 100)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def generate_ass(
    pages: list[CaptionPage],
    *,
    width: int = 1920,
    height: int = 1080,
    font_family: str = "Inter",
    font_size: int = 56,
    text_color: str = "#ffffff",
    highlight_color: str = "#facc15",
    outline_color: str = "#000000",
) -> str:
    """Render caption pages as an ASS document with karaoke word highlight."""
    lines = [
        _HEADER.format(
            width=width,
            height=height,
            font_family=font_family,
            font_size=font_size,
            # Karaoke fills SecondaryColour → PrimaryColour as words are "sung".
            highlight_color=_ass_color(highlight_color),
            text_color=_ass_color(text_color),
            outline_color=_ass_color(outline_color),
            margin_v=int(height * 0.12),
        )
    ]

    for page in pages:
        if not page.tokens:
            continue
        parts: list[str] = []
        cursor = page.start_ms
        for token in page.tokens:
            # Cover any silence before the word inside the same k-tag so
            # the highlight lands exactly on the word's start.
            gap_cs = max(round((token.from_ms - cursor) / 10), 0)
            if gap_cs:
                parts.append(f"{{\\k{gap_cs}}}")
            dur_cs = max(round((token.to_ms - token.from_ms) / 10), 1)
            parts.append(f"{{\\k{dur_cs}}}{_escape_text(token.text)} ")
            cursor = max(token.to_ms, cursor)
        lines.append(
            f"Dialogue: 0,{_ass_time(page.start_ms)},{_ass_time(page.end_ms)},"
            f"Caption,,0,0,0,,{''.join(parts).rstrip()}"
        )

    return "\n".join(lines) + "\n"
