"""Sound whole-area and attack-path queries share effective zone geometry."""
import pytest

from combat.gate2_runtime_models import Position, ZoneState
from combat.spatial_areas import (
    positions_inside_zone, zone_contains, zone_contains_cells,
    zone_volume_cells, zone_volume_inside,
)
from tests.h1_support import duel, ME


@pytest.mark.parametrize('suppression', ['none', 'cells', 'all'])
def test_sound_volume_and_attack_path_share_suppressed_columns(suppression):
    engine = duel([])
    actor = engine.state.actors[ME]
    actor.position = Position(x=3, y=4, z=1)
    spec = {'footprint_height_ft': 10, 'footprint_is_authoritative': True}
    if suppression != 'none':
        spec['suppressed'] = ([{'all': 1}] if suppression == 'all'
                              else [{'cells': [[4, 4]]}])
    source = ZoneState(zone_id='test:sound-source', source_definition_id='test:sound-source',
        owner_id=ME, center=Position(x=3, y=4), radius_cells=0,
        affected_cells=(Position(x=3, y=4), Position(x=4, y=4)),
        concentration_link=False, created_round=1, trigger_profile=spec)
    # Use the native serialized zone shape, as a reloaded fight does.
    source = ZoneState.model_validate(source.model_dump(mode='json'))
    destination = source.model_copy(update={
        'zone_id': 'test:sound-destination',
        'affected_cells': (Position(x=3, y=4),),
        'trigger_profile': {'footprint_height_ft': 10, 'footprint_is_authoritative': True},
    })
    expected = (set() if suppression == 'all' else
                {(3, 4, 0), (3, 4, 1)} | ({(4, 4, 0), (4, 4, 1)} if suppression == 'none' else set()))
    assert set(zone_volume_cells(engine, source)) == expected
    assert zone_contains(engine, actor, source) == (suppression != 'all')
    for cell in [(3, 4, 1), (4, 4, 1), (3, 4, 2)]:
        assert positions_inside_zone(engine, [cell], source) == (cell in expected)
        assert zone_contains_cells(engine, [cell], source) == (cell in expected)
    # A fully suppressed source is not a nonempty delivery; partial suppression
    # can make the remaining whole source fit, without refilling its cut column.
    assert zone_volume_inside(engine, source, destination) == (suppression == 'cells')
    assert not zone_volume_inside(engine, destination, source.model_copy(update={
        'trigger_profile': {**spec, 'suppressed': [{'all': 1}]}}))
