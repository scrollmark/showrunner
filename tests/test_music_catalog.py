from pathlib import Path

import pytest

from showrunner.music.catalog import MusicCatalog, Track


def _make_catalog(tmp_path: Path, tracks: list[Track] | None = None) -> MusicCatalog:
    cat = MusicCatalog(directory=tmp_path, tracks=tracks or [])
    return cat


def test_empty_catalog_is_ok(tmp_path):
    cat = MusicCatalog.load(tmp_path)
    assert cat.tracks == []
    assert cat.directory == tmp_path.resolve()


def test_save_then_load_roundtrip(tmp_path):
    original = _make_catalog(tmp_path, [
        Track(id="warm-01", path="tracks/warm-01.mp3",
              moods=["editorial", "contemplative"], bpm=92, license="artlist"),
        Track(id="tense-01", path="tracks/tense-01.mp3",
              moods=["tense", "cinematic"], bpm=128),
    ])
    original.save()
    reloaded = MusicCatalog.load(tmp_path)
    assert len(reloaded.tracks) == 2
    assert reloaded.get("warm-01").bpm == 92
    assert reloaded.get("warm-01").moods == ["editorial", "contemplative"]


def test_add_duplicate_id_raises(tmp_path):
    cat = _make_catalog(tmp_path, [Track(id="a", path="x")])
    with pytest.raises(ValueError):
        cat.add(Track(id="a", path="y"))


def test_remove_returns_true_when_something_removed(tmp_path):
    cat = _make_catalog(tmp_path, [Track(id="a", path="x")])
    assert cat.remove("a") is True
    assert cat.remove("a") is False


def test_filter_by_moods_intersects(tmp_path):
    cat = _make_catalog(tmp_path, [
        Track(id="a", path="a", moods=["editorial", "warm"]),
        Track(id="b", path="b", moods=["tense"]),
        Track(id="c", path="c", moods=["editorial"]),
    ])
    results = {t.id for t in cat.filter_by_moods(["editorial"])}
    assert results == {"a", "c"}


def test_filter_by_moods_empty_returns_all(tmp_path):
    cat = _make_catalog(tmp_path, [Track(id="a", path="a"), Track(id="b", path="b")])
    assert len(cat.filter_by_moods([])) == 2


def test_resolve_audio_path_relative(tmp_path):
    cat = _make_catalog(tmp_path, [Track(id="a", path="tracks/a.mp3")])
    resolved = cat.resolve_audio_path(cat.tracks[0])
    assert resolved == (tmp_path / "tracks" / "a.mp3").resolve()


def test_resolve_audio_path_absolute_preserved(tmp_path):
    abs_path = tmp_path / "elsewhere" / "a.mp3"
    cat = _make_catalog(tmp_path, [Track(id="a", path=str(abs_path))])
    assert cat.resolve_audio_path(cat.tracks[0]) == abs_path


def test_default_directory_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWRUNNER_MUSIC_DIR", str(tmp_path))
    assert MusicCatalog.default_directory() == tmp_path.resolve()


def test_load_rejects_future_version(tmp_path):
    (tmp_path / "catalog.yaml").write_text("version: 99\ntracks: []\n")
    with pytest.raises(ValueError, match="newer"):
        MusicCatalog.load(tmp_path)
