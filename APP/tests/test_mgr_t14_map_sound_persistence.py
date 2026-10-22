"""Saved maps keep the owner-drawn sound and connected resonant media (review finding 4).

Without the persistence fix, the sound and resonant_media facts authored in the
map editor vanish on save/convert, so ordinary air, barriers and connected media
never reach the engine.
"""
import pytest

from combat.tabletop import TabletopError, TabletopMapStore, normalize_map, to_battlefield
from combat.resonance import normalize_media


def _doc(**extra):
    return {'map_id': 'sound-persist', 'display_name': 'Sound persistence',
            'width_squares': 20, 'height_squares': 14, **extra}


def test_saved_map_keeps_sound_and_resonant_media(tmp_path):
    media = normalize_media([{'id': 'walkway', 'material': 'solid', 'cells': [{'x': 2, 'y': 3, 'z': 0}]}], 20, 14)
    store = TabletopMapStore(tmp_path / 'maps')
    store.save(_doc(sound={'ambient': 'air', 'boundaries': []}, resonant_media=media))
    saved = store.get('sound-persist')
    assert saved['sound']['ambient'] == 'air'
    assert saved['resonant_media'] == media
    battlefield = to_battlefield(saved)
    assert battlefield['sound']['ambient'] == 'air'
    assert battlefield['resonant_media'] == media


def test_soundproof_boundary_survives_conversion(tmp_path):
    sound = {'ambient': 'air', 'boundaries': [{'kind': 'soundproof', 'name': 'Soundproof wall', 'cells': [[4, 6]]}]}
    battlefield = to_battlefield(normalize_map(_doc(sound=sound)))
    assert battlefield['sound']['boundaries'][0]['cells'] == [[4, 6]]


def test_invalid_sound_is_rejected_not_dropped(tmp_path):
    with pytest.raises(TabletopError):
        normalize_map(_doc(sound={'ambient': 'plasma', 'boundaries': []}))


def test_saved_map_sound_survives_fresh_store_reload(tmp_path):
    # Review finding 8: the reload path, not only the same store instance's get().
    media = normalize_media([{'id': 'walkway', 'material': 'solid', 'cells': [{'x': 2, 'y': 3, 'z': 0}]}], 20, 14)
    TabletopMapStore(tmp_path / 'maps').save(_doc(sound={'ambient': 'air', 'boundaries': []}, resonant_media=media))
    reloaded = TabletopMapStore(tmp_path / 'maps').get('sound-persist')
    assert reloaded['sound']['ambient'] == 'air'
    assert reloaded['resonant_media'] == media
