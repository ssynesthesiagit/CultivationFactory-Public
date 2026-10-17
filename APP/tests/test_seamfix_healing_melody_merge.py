"""Scene catch difficulty and physical sound geometry share the map round trip."""
import pytest

from combat.gate2_grid import SquareGrid
from combat.tabletop import TabletopMapStore, battlefield_as_map, to_battlefield


@pytest.mark.parametrize('catch_dc', [None, 0, 12])
def test_catch_difficulty_and_resonant_medium_survive_together(tmp_path, catch_dc):
    media = [{'id': 'walkway', 'material': 'solid',
              'cells': [{'x': 3, 'y': 6, 'z': 0}, {'x': 4, 'y': 6, 'z': 0}]}]
    store = TabletopMapStore(tmp_path / 'maps')
    document = {'map_id': 'combined-scene', 'display_name': 'Stone walkway',
                'width_squares': 20, 'height_squares': 14, 'resonant_media': media}
    if catch_dc is not None:
        document['catch_dc'] = catch_dc
    store.save(document)
    arena = to_battlefield(store.get('combined-scene'))
    grid = SquareGrid(arena)
    assert grid.catch_dc == catch_dc
    assert grid.resonant_media == media
    restored = battlefield_as_map(arena)
    assert restored['resonant_media'] == media
    assert restored.get('catch_dc') == catch_dc
    assert ('catch_dc' in restored) == (catch_dc is not None)
