"""Music catalog — a user-owned YAML index of their licensed tracks.

Showrunner does not ship or bundle any music. The catalog lives in the
user's own filesystem (default `~/.showrunner/music/catalog.yaml`) and
holds pointers to tracks *they* provisioned under *their* licenses.
Each catalog entry records the license string so the user has a paper
trail if they ever need to prove provenance.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml


CATALOG_VERSION = 1

# Known mood vocabulary. Not exhaustive — users can invent their own and
# reference them from presets — but serves as a soft hint for consistency.
SUGGESTED_MOODS = (
    "editorial", "lifestyle", "contemplative", "energetic", "cinematic",
    "corporate", "ambient", "playful", "tense", "warm", "dark",
    "uplifting", "mellow", "aggressive", "gentle",
)


@dataclass
class Track:
    """One entry in a user's music catalog.

    `path` is resolved relative to the catalog directory when the catalog
    is loaded, so catalogs are portable between machines that share the
    same directory layout.
    """
    id: str
    path: str                 # relative to the catalog's directory; resolved to absolute on load
    moods: list[str] = field(default_factory=list)
    bpm: float | None = None
    key: str | None = None    # e.g. "C", "Am", "F#"
    duration_seconds: float | None = None
    license: str | None = None
    source: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        # Drop empty/None fields for a clean YAML serialization.
        return {k: v for k, v in data.items() if v not in (None, [], "")}


@dataclass
class MusicCatalog:
    """A collection of tracks + the directory they live in.

    The directory is the anchor: `track.path` is always resolved relative
    to it, so moving the whole directory preserves validity.
    """
    directory: Path
    tracks: list[Track] = field(default_factory=list)
    version: int = CATALOG_VERSION

    @property
    def catalog_file(self) -> Path:
        return self.directory / "catalog.yaml"

    @classmethod
    def default_directory(cls) -> Path:
        """Resolve the catalog directory from env var or the XDG-style default.

        Precedence: `$SHOWRUNNER_MUSIC_DIR` env var; else `~/.showrunner/music`.
        """
        env = os.environ.get("SHOWRUNNER_MUSIC_DIR")
        if env:
            return Path(env).expanduser().resolve()
        return Path.home() / ".showrunner" / "music"

    @classmethod
    def load(cls, directory: Path | None = None) -> "MusicCatalog":
        """Load the catalog from disk. Returns an empty catalog if the
        catalog file doesn't exist yet."""
        directory = Path(directory) if directory else cls.default_directory()
        directory = directory.expanduser().resolve()
        catalog_file = directory / "catalog.yaml"
        if not catalog_file.exists():
            return cls(directory=directory, tracks=[])
        data = yaml.safe_load(catalog_file.read_text(encoding="utf-8")) or {}
        version = int(data.get("version", CATALOG_VERSION))
        if version > CATALOG_VERSION:
            raise ValueError(
                f"Catalog version {version} is newer than this showrunner "
                f"release (supports up to {CATALOG_VERSION}). Upgrade showrunner."
            )
        tracks = [Track(**raw) for raw in data.get("tracks", [])]
        return cls(directory=directory, tracks=tracks, version=version)

    def save(self) -> Path:
        """Write the catalog to disk, creating the directory if missing."""
        self.directory.mkdir(parents=True, exist_ok=True)
        body = {
            "version": self.version,
            "tracks": [t.to_dict() for t in self.tracks],
        }
        self.catalog_file.write_text(
            yaml.safe_dump(body, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return self.catalog_file

    def add(self, track: Track) -> None:
        """Add a track. Raises ValueError if the id already exists."""
        if any(t.id == track.id for t in self.tracks):
            raise ValueError(f"Catalog already contains a track with id '{track.id}'")
        self.tracks.append(track)

    def remove(self, track_id: str) -> bool:
        """Remove the track with the given id. Returns True if something
        was removed."""
        before = len(self.tracks)
        self.tracks = [t for t in self.tracks if t.id != track_id]
        return len(self.tracks) < before

    def get(self, track_id: str) -> Track | None:
        return next((t for t in self.tracks if t.id == track_id), None)

    def filter_by_moods(self, moods: list[str]) -> list[Track]:
        if not moods:
            return list(self.tracks)
        wanted = set(moods)
        return [t for t in self.tracks if wanted & set(t.moods)]

    def resolve_audio_path(self, track: Track) -> Path:
        """Absolute path to a track's audio file."""
        p = Path(track.path)
        return p if p.is_absolute() else (self.directory / p).resolve()
