"""Resolve a music request ("auto" / "none" / track id) into a concrete track."""

from __future__ import annotations


def resolve_music_selection(
    *, music: str | None, seed: str, volume: float | None, preset: dict
) -> dict | None:
    """Turn a `--music` value into a concrete selection (or None).

    Values: "none" / None → no music. "auto" → mood-picked from the
    preset. Anything else → track id lookup.
    """
    from showrunner.music import MusicCatalog, MusicPicker

    if music in (None, "none"):
        return None
    catalog = MusicCatalog.load()
    if not catalog.tracks:
        # Graceful no-op when the user hasn't provisioned a catalog yet.
        return None

    if music == "auto":
        track = MusicPicker(catalog).pick_for_preset(preset, seed=seed)
    else:
        track = catalog.get(music)
        if track is None:
            raise ValueError(
                f"Music track '{music}' not in catalog. "
                "Run `showrunner music list` to see available tracks."
            )
    if track is None:
        return None
    preset_volume = (preset.get("music") or {}).get("volume", 0.2)
    return {
        "track": track,
        "audio_path": catalog.resolve_audio_path(track),
        "volume": volume if volume is not None else preset_volume,
    }
