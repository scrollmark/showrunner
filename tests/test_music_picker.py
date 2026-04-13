from showrunner.music.catalog import MusicCatalog, Track
from showrunner.music.picker import MusicPicker, PickRequest


def _cat(tmp_path, tracks):
    return MusicCatalog(directory=tmp_path, tracks=tracks)


def test_picker_returns_none_for_empty_catalog(tmp_path):
    picker = MusicPicker(_cat(tmp_path, []))
    assert picker.pick(PickRequest(moods=("editorial",), seed="x")) is None


def test_picker_determinism(tmp_path):
    cat = _cat(tmp_path, [
        Track(id=f"t{i}", path=f"t{i}.mp3", moods=["editorial"], bpm=92 + i)
        for i in range(10)
    ])
    picker = MusicPicker(cat)
    req = PickRequest(moods=("editorial",), seed="same-seed", preferred_bpm=92)
    first = picker.pick(req)
    second = picker.pick(req)
    assert first is not None
    assert first.id == second.id


def test_picker_seed_variance(tmp_path):
    cat = _cat(tmp_path, [
        Track(id=f"t{i}", path=f"t{i}.mp3", moods=["editorial"], bpm=92)
        for i in range(20)
    ])
    picker = MusicPicker(cat)
    ids = {
        picker.pick(PickRequest(moods=("editorial",), seed=f"seed-{i}")).id
        for i in range(40)
    }
    # Different seeds should land on at least 2 distinct tracks across 40 trials.
    assert len(ids) >= 2


def test_picker_prefers_mood_match_over_bpm(tmp_path):
    cat = _cat(tmp_path, [
        Track(id="wrong_mood_right_bpm", path="a", moods=["tense"], bpm=92),
        Track(id="right_mood_wrong_bpm", path="b", moods=["editorial"], bpm=160),
    ])
    picker = MusicPicker(cat)
    # Mood is double-weighted, so `editorial + wrong bpm` beats `tense + right bpm`.
    chosen = picker.pick(PickRequest(moods=("editorial",), preferred_bpm=92, seed="s"))
    assert chosen.id == "right_mood_wrong_bpm"


def test_picker_falls_back_when_no_mood_match(tmp_path):
    cat = _cat(tmp_path, [
        Track(id="a", path="a", moods=["tense"]),
        Track(id="b", path="b", moods=["cinematic"]),
    ])
    picker = MusicPicker(cat)
    # No `editorial` tracks exist; falls back to the full catalog.
    chosen = picker.pick(PickRequest(moods=("editorial",), seed="s"))
    assert chosen is not None


def test_picker_handles_missing_bpm_gracefully(tmp_path):
    cat = _cat(tmp_path, [
        Track(id="a", path="a", moods=["editorial"], bpm=None),
        Track(id="b", path="b", moods=["editorial"], bpm=92),
    ])
    picker = MusicPicker(cat)
    # Should not crash when a track has no bpm and the request does.
    chosen = picker.pick(PickRequest(moods=("editorial",), preferred_bpm=92, seed="s"))
    assert chosen is not None
