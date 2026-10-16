"""F5R: calling a real bow preserves its body without making it an area target."""
import pytest

from tests.test_mgr_spirit_bow_native import (
    O, F, X, QI, bound_bow, fight, commit, option, native_option, cold, next_turn,
)


def test_release_call_next_turn_ordinary_line_preserves_bow_native(tmp_path):
    from combat.ext.hand_occupancy import weapon_grips
    from combat.ext.mgr_reserve_spirit_bow_cultivator_seeking_arrow import BOUND

    neighbor = {'name': 'Loose object beside the wielder', 'kind': 'custom',
                'material': 'wood', 'size': 'small', 'x': 3, 'y': 6,
                'ac': 10, 'hp': 1, 'blocks': False, 'unattended': True}
    c, t, j, real = bound_bow(tmp_path, objects=[neighbor])
    mid = fight(c, t, j)
    commit(t, mid, option(t, mid, 'Manifest Bound Spirit Bow', at=(9, 6)))
    released = cold(c, mid)
    bow = next(o for o in released.state.objects.values()
               if (o.component or {}).get('real_bow') == real)
    assert not bow.component['in_inventory']
    next_turn(t, mid)
    commit(t, mid, option(t, mid, 'Call Bound Spirit Bow'))
    called = cold(c, mid)
    assert called.state.objects[bow.object_id].component['in_inventory'] == 1
    assert called.state.objects[bow.object_id].position == called.state.actors[O].position
    assert real in weapon_grips(called, called.state.actors[O])
    next_turn(t, mid)
    before = cold(c, mid)
    bond = [v.model_dump(mode='json') for v in before.state.actors[O].conditions.values()
            if v.condition_id == BOUND]
    assert bond
    event_count = len(before.events)
    commit(t, mid, native_option(c, mid, 'Piercing Shot: Force', at=(20, 6), remote=False))
    after = cold(c, mid)  # Fresh service verifies the commit and mechanical replay.
    body = after.state.objects[bow.object_id]
    assert body.current_hp == bow.current_hp and not body.destroyed
    assert body.component['in_inventory'] == 1
    assert real in weapon_grips(after, after.state.actors[O])
    assert [v.model_dump(mode='json') for v in after.state.actors[O].conditions.values()
            if v.condition_id == BOUND] == bond
    loose = next(o for o in after.state.objects.values() if o.object_id != bow.object_id)
    assert loose.position == body.position and loose.destroyed
    assert all(after.state.actors[a].current_hp < before.state.actors[a].current_hp for a in (F, X))
    assert after.state.actors[O].resources[QI] == before.state.actors[O].resources[QI] - 4
    shot_events = after.events[event_count:]
    assert shot_events and not any(e.payload.get('effect_origin') for e in shot_events)


@pytest.mark.parametrize('shape', ['line', 'sphere'])
def test_area_inventory_eligibility_uses_item_state_not_square_or_attendance(shape):
    from combat.ext.objects import area_reaches
    from combat.gate2_runtime_models import Position, RuntimeObjectState
    from tests.h1_support import duel

    engine = duel([])
    origin, aim = Position(x=2, y=2), Position(x=4, y=2)
    obj = RuntimeObjectState(object_id='object:retained-item', object_kind='weapon',
                             position=aim, unattended=False, flammable=False, ac=10,
                             current_hp=10, maximum_hp=10, component={})
    area = {'shape': shape, 'size_ft': 30, 'width_ft': 5}
    # An attended floating/landed item still intersects, and absence is inert.
    assert area_reaches(engine, origin, aim, obj, area)
    for flag in (0, 1, 0):
        body = obj.model_copy(update={'component': {'in_inventory': flag}})
        assert area_reaches(engine, origin, aim, body, area) == (flag == 0)
        # No square-wide or ownership-wide immunity for a separate object.
        assert area_reaches(engine, origin, aim, obj, area)
