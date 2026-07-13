# Audio Craft

Music, mix, and loudness decisions. Sound is half the perceived quality of a
short video — a clean mix at the right loudness reads as professional before
a single frame is judged.

## Picking music

- The catalog is the user's own licensed library (`showrunner music list`);
  showrunner ships no tracks. If the catalog is empty, say so and continue
  without a bed — never source music from elsewhere on your own.
- Match energy to content, not topic: tutorial → low-stakes mid-tempo;
  hype/launch → driving, 120+ BPM; emotional story → sparse, slow. When the
  preset defines a music mood, `showrunner compose --music auto` picks
  deterministically — override with a track id only when the user asks or
  the auto pick clashes.
- BPM matters more than genre: motion is choreographed to the preset's
  rhythm grid, so a track whose BPM matches (or cleanly halves/doubles) the
  preset's `rhythm.bpm` makes every animation feel intentional.

## Beat grids

`showrunner music analyze <track> --json` returns bpm + a beat-time grid.
Use it whenever timing must lock to the music (carousel cuts, kinetic type
entrances, emphasis pulses). Snap event times to grid values — the check
enforces ±1 frame on workflows that gate it.

## Mix behavior (what the toolchain already does)

- Narrated workflows duck the bed under narration automatically (per-frame
  envelope computed from the actual WAVs) and fade it over a beat-aligned
  outro. Don't hand-animate music volume on top of it.
- Default bed volume comes from the preset (`music.volume`); nudge with
  `--music-volume` only when a track is inherently hot or quiet.

## Loudness

Master the final render before publishing:

```bash
showrunner audio master out/final.mp4 -o out/final-mastered.mp4
```

Default target is -14 LUFS integrated / -1.5 dBTP — the level short-form
platforms normalize to. Quieter uploads get turned up (noise and all);
hotter ones get squashed. One pass on the finished file is enough.
