"""Wind-Script roof collisions through real table commits and cold replay."""
import pytest

from combat import senses
from combat.ext import air_delivery
from combat.gate2_runtime_models import Position
from tests import worker2_support as S
from tests.mgr_t16_support import automatic
from tests.test_mgr_t16_review import fixture, scene


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('boundary', ['sealed', 'skylight', 'opening', 'around'])
def test_delivery_respects_roof_on_both_legs_after_table_reload(tmp_path, monkeypatch, ai, boundary):
    origin = Position(x=5, y=6)
    above = Position(x=5, y=6, z=3)
    permitted = boundary in ('opening', 'around')
    destination = above if permitted else Position(x=6, y=6)
    key = f'cell:{destination.x},{destination.y},{destination.z}'

    def arena(doc):
        doc['terrain_regions'] = []
        cells = ([{'x': 5, 'y': 6}] if boundary == 'around' else
                 [{'x': x, 'y': y} for x in range(doc['width_squares']) for y in range(doc['height_squares'])])
        roof = {'id': 'test:delivery-slab', 'height_ft': 10, 'cells': cells}
        if boundary in ('opening', 'skylight'):
            roof['openings'] = [{'x': 5, 'y': 6, 'open': boundary == 'opening', 'kind': 'skylight'}]
        doc['roof_surfaces'] = [roof]

    c, t, mid = fixture(tmp_path, [air_delivery.DELIVERY, 'AIR_BASE_GATHER_CURRENT'],
                        arena=arena, delivery=True,
                        positions={S.OWNER: {'x': 5, 'y': 6}, S.ALLY: {'x': 4, 'y': 6},
                                   S.FOE: {'x': 10, 'y': 9}})
    before = S.reload(tmp_path, mid)
    # A solid transparent skylight still blocks objects. A single slab cell can
    # be bypassed at Core Formation, but cannot be crossed by a straight route.
    straight = air_delivery.routes(before, origin, 0)
    assert ('cell:5,6,3' in straight) is (boundary == 'opening')
    assert ('cell:5,6,3' in air_delivery.routes(before, origin, 1)) is permitted
    if boundary == 'around':
        assert not senses.perceives_cell(before, before.state.actors[S.OWNER], above)

    native = air_delivery.ask
    seen = []

    def choose(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == 'choice:needle.wind_script_destination':
            seen.append(tuple(options))
            assert ('cell:5,6,3' in options) is permitted
            assert key in options
            assert kwargs.get('automatic_options') is None
            kwargs['preferred'] = [key]
        return native(engine, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(air_delivery, 'ask', choose)
    if ai:
        automatic(c, t, mid, S.OWNER, 'Gather Current: Carry', at=(5, 6))
    else:
        S.settle(t, mid, S.candidate(c, mid, 'Gather Current: Carry', at=(5, 6)).candidate_id,
                 picks={'choice:needle.wind_script_object': 'object:test.script',
                        'choice:needle.wind_script_destination': key})
    assert seen
    after = S.reload(tmp_path, mid)
    obj = after.state.objects['object:test.script']
    assert obj.position == destination
    assert obj.component['activated'] == 0
    assert ('cell:5,6,3' in air_delivery.routes(after, origin, 1)) is permitted
