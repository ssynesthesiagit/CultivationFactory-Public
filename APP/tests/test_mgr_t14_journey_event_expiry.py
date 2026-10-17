"""Journey snapshots preserve standing events without admitting turn clocks."""
import json

import pytest

from combat.ext.journey_setup import encounter_snapshot
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ConditionInstance
from tests.h1_support import ROOT


def prone_actor():
    engine = Gate2Engine(ROOT, match_seed='journey-standing-boundary')
    actor = next(a for a in engine.state.actors.values()
                 if a.entity_id != engine.state.current_actor_id)
    engine._apply_condition(actor, 'condition:typed.prone', 'src.trip',
                            engine.state.current_actor_id, expires_on='STAND_UP')
    return engine, actor


@pytest.mark.parametrize('effects_ended', [False, True])
def test_standing_marker_roundtrips_and_still_requires_standing(effects_ended):
    engine, actor = prone_actor()
    before = actor.model_dump(mode='json')
    snapshot = encounter_snapshot(actor, effects_ended=effects_ended)
    assert actor.model_dump(mode='json') == before
    actor.conditions = {key: ConditionInstance.model_validate(json.loads(value))
                        for key, value in snapshot['conditions'].items()}
    assert [c.expires_on for c in actor.conditions.values()] == ['STAND_UP']
    actor.movement_remaining_ft = 30
    engine._expire_for_checkpoint('END_OF_TURN', engine.state.current_actor_id)
    assert actor.conditions
    engine._expire_for_checkpoint('START_OF_TURN', actor.entity_id)
    assert not actor.conditions
    # A turn start refreshes the full allowance before paying to stand.
    speed = engine._effective_speed(actor)
    assert actor.movement_remaining_ft == speed - speed // 2


@pytest.mark.parametrize('expiry,turn_count,data', [
    ('END_OF_TURN', None, {}),
    ('START_OF_NEXT_TURN', None, {}),
    ('STAND_UP', 2, {}),
    ('STAND_UP', None, {'unsupported': 1.5}),
    ('STAND_UP', None, {'unsupported': True}),
])
def test_event_exception_keeps_turn_clock_and_primitive_guards(expiry, turn_count, data):
    _engine, actor = prone_actor()
    condition = next(iter(actor.conditions.values()))
    condition.expires_on = expiry
    condition.expires_turn_count = turn_count
    condition.data.update(data)
    before = actor.model_dump(mode='json')
    with pytest.raises(ValueError, match='timed or unsupported condition'):
        encounter_snapshot(actor)
    assert actor.model_dump(mode='json') == before
