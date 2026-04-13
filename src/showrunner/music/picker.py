"""Deterministic mood + bpm-weighted picker over the user's music catalog.

Given a preset, produce a stable choice of track so the same video (same
topic, same preset, same seed) gets the same music across re-runs. A
seed parameter lets callers regenerate variety on demand.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from showrunner.music.catalog import MusicCatalog, Track


@dataclass(frozen=True)
class PickRequest:
    """Inputs to the picker. Deliberately small and serializable."""
    moods: tuple[str, ...]
    preferred_bpm: float | None = None
    seed: str = ""   # caller-chosen; typically video topic slug


# Tuning: the picker first scores every candidate, then samples from the
# top `SHORTLIST_FRACTION` with a deterministic RNG keyed on the seed.
# This balances "always pick the best match" (boring, one track per mood)
# against "total random" (unpredictable quality).
SHORTLIST_FRACTION = 0.25
SHORTLIST_MIN = 3


class MusicPicker:
    """Score tracks against a request, sample deterministically."""

    def __init__(self, catalog: MusicCatalog):
        self.catalog = catalog

    def pick(self, request: PickRequest) -> Track | None:
        """Return the chosen track, or None if the catalog can't satisfy
        the request at all (empty / no mood overlap)."""
        candidates = self.catalog.filter_by_moods(list(request.moods))
        if not candidates and request.moods:
            # Fall back to the full catalog if the mood filter is too strict.
            candidates = list(self.catalog.tracks)
        if not candidates:
            return None

        scored = sorted(
            candidates,
            key=lambda t: self._score(t, request),
            reverse=True,
        )
        shortlist_size = max(SHORTLIST_MIN, int(len(scored) * SHORTLIST_FRACTION))
        shortlist = scored[:shortlist_size]

        rng = self._rng_for_seed(request.seed)
        return rng.choice(shortlist)

    # ── scoring ──────────────────────────────────────────────────────────

    def _score(self, track: Track, request: PickRequest) -> float:
        mood_score = self._mood_overlap(track, request.moods)
        bpm_score = self._bpm_closeness(track.bpm, request.preferred_bpm)
        # Mood overlap is double-weighted — it's the primary selector.
        return 2.0 * mood_score + bpm_score

    @staticmethod
    def _mood_overlap(track: Track, wanted: tuple[str, ...]) -> float:
        if not wanted:
            return 0.0
        overlap = len(set(track.moods) & set(wanted))
        return overlap / len(wanted)

    @staticmethod
    def _bpm_closeness(track_bpm: float | None, wanted: float | None) -> float:
        if track_bpm is None or wanted is None:
            return 0.0
        diff = abs(track_bpm - wanted)
        # Perfect match = 1.0; 20 bpm off = 0.0. Linear in between.
        return max(0.0, 1.0 - diff / 20.0)

    @staticmethod
    def _rng_for_seed(seed: str) -> random.Random:
        # hashing is just to normalize arbitrary seed strings into ints
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        return random.Random(int.from_bytes(digest[:8], "big"))
